"""Connection to a single Christmas light controller."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
import logging

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    BleakNotFoundError,
    establish_connection,
)

from .protocol import (
    ALL_MODES,
    CMD_QUERY_SETTINGS,
    CMD_RESTORE_DEFAULTS,
    NOTIFY_CHAR_UUID,
    SERVICE_UUID,
    WRITE_CHAR_UUID,
    Mode,
    PowerReport,
    SettingsReport,
    Timers,
    brightness_command,
    mode_command,
    parse_notification,
    power_command,
    power_query,
    settings_command,
    timers_command,
)

_LOGGER = logging.getLogger(__name__)

# How long to wait for the controller to answer the state queries.
UPDATE_TIMEOUT = 10

# How many notifications that were not understood are kept for diagnostics.
UNRECOGNISED_HISTORY = 10

BLEAK_EXCEPTIONS = (BleakError, BleakNotFoundError, EOFError, TimeoutError)


class CharacteristicMissingError(BleakError):
    """The device does not expose the expected GATT characteristics."""


@dataclass(frozen=True, slots=True)
class DeviceState:
    """Last known state of the controller."""

    is_on: bool | None = None
    brightness: int | None = None
    mode: Mode | None = None
    # With the timers enabled the lights are only lit within a timer period,
    # also when is_on is true.
    timers_enabled: bool | None = None
    timers: Timers | None = None


class ChristmasLights:
    """A Christmas light controller, reached over Bluetooth.

    The connection is opened when it is first needed. It then stays open,
    unless idle_disconnect_delay is given: in that case it is closed after
    that many seconds without a command or state query.

    Commands and state queries run one at a time. One that fails on an
    existing connection is tried once more on a new connection.

    Every state query also sets the clock of the controller, which it needs
    for its timers. now has to return the local time for that.
    """

    def __init__(
        self,
        ble_device: BLEDevice,
        idle_disconnect_delay: float | None = None,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        """Initialize the device."""
        self._ble_device = ble_device
        self._idle_disconnect_delay = idle_disconnect_delay
        self._now = now
        self._client: BleakClientWithServiceCache | None = None
        self._write_char: BleakGATTCharacteristic | None = None
        self._operation_lock = asyncio.Lock()
        self._stopped = False
        # Set while update() waits for the controller to report its state.
        self._reports: asyncio.Future[None] | None = None
        self._awaited_reports: set[type] = set()
        self._idle_timer: asyncio.TimerHandle | None = None
        self._idle_task: asyncio.Task[None] | None = None
        self._state_callbacks: list[Callable[[DeviceState], None]] = []
        self._connect_callbacks: list[Callable[[], None]] = []
        self._disconnect_callbacks: list[Callable[[], None]] = []
        self.state = DeviceState()
        # Raw notifications as hex, for diagnostics.
        self.last_power_report: str | None = None
        self.last_settings_report: str | None = None
        self.unrecognised_notifications: deque[str] = deque(maxlen=UNRECOGNISED_HISTORY)

    @property
    def address(self) -> str:
        """Bluetooth address of the device."""
        return self._ble_device.address

    @property
    def name(self) -> str | None:
        """Name the device advertises with, such as LED-4-02-00000000."""
        return self._ble_device.name

    @property
    def is_connected(self) -> bool:
        """Whether there is an open connection to the device."""
        return self._client is not None and self._client.is_connected

    def set_ble_device(self, ble_device: BLEDevice) -> None:
        """Use a newer BLEDevice, for example one seen by another adapter."""
        self._ble_device = ble_device

    def register_callback(
        self, callback: Callable[[DeviceState], None]
    ) -> Callable[[], None]:
        """Call callback when the state changes; returns an unsubscribe.

        The callback is called for changes made by a command and for state
        the controller reports on its own. The state read by update() is
        returned by update() instead.
        """
        self._state_callbacks.append(callback)
        return lambda: self._state_callbacks.remove(callback)

    def register_connect_callback(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Call callback after every new connection; returns an unsubscribe.

        The command or state query that made the connection is still running
        then, so anything the callback sends has to wait for it: start it as
        a task instead of waiting for it in the callback.
        """
        self._connect_callbacks.append(callback)
        return lambda: self._connect_callbacks.remove(callback)

    def register_disconnect_callback(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Call callback when the connection drops; returns an unsubscribe.

        The callback is not called when the connection is closed on purpose,
        by stop() or because it was idle.
        """
        self._disconnect_callbacks.append(callback)
        return lambda: self._disconnect_callbacks.remove(callback)

    async def update(self) -> DeviceState:
        """Ask the controller for its full state and wait for the answer."""
        return await self._run(self._query)

    async def turn_on(
        self,
        brightness: int | None = None,
        mode: Mode | None = None,
        timers_enabled: bool | None = None,
    ) -> None:
        """Turn the lights on, optionally with a new brightness and mode.

        The timers stay enabled or disabled as they are, unless
        timers_enabled says otherwise.
        """
        if timers_enabled is None:
            timers_enabled = self._timers_enabled

        async def turn_on() -> None:
            changes: dict[str, bool | int | Mode | Timers] = {}
            try:
                if brightness is not None:
                    await self._write(brightness_command(brightness))
                    changes["brightness"] = brightness
                if mode is not None:
                    await self._write(mode_command(mode))
                    changes["mode"] = mode & ALL_MODES
                await self._write(power_command(True, timers_enabled))
                changes["is_on"] = True
                changes["timers_enabled"] = timers_enabled
            finally:
                # Report what did reach the controller as one change.
                self._set_state(**changes)

        await self._run(turn_on)

    async def turn_off(self, timers_enabled: bool | None = None) -> None:
        """Turn the lights off; see turn_on() for timers_enabled."""
        if timers_enabled is None:
            timers_enabled = self._timers_enabled

        async def turn_off() -> None:
            await self._write(power_command(False, timers_enabled))
            self._set_state(is_on=False, timers_enabled=timers_enabled)

        await self._run(turn_off)

    async def set_timers_enabled(
        self, enabled: bool, is_on: bool | None = None
    ) -> None:
        """Let the timers decide when the lights are lit, or stop that.

        The lights stay on or off as they are, unless is_on says otherwise.
        """
        if is_on is None:
            is_on = bool(self.state.is_on)

        async def set_timers_enabled() -> None:
            await self._write(power_command(is_on, enabled))
            self._set_state(is_on=is_on, timers_enabled=enabled)

        await self._run(set_timers_enabled)

    async def set_timers(self, timers: Timers) -> None:
        """Set the three periods in which the lights are lit."""

        async def set_timers() -> None:
            await self._write(timers_command(timers))
            self._set_state(timers=timers)

        await self._run(set_timers)

    async def apply_settings(
        self,
        is_on: bool,
        timers_enabled: bool,
        brightness: int,
        mode: Mode,
        timers: Timers,
    ) -> None:
        """Set everything at once, as the app does for the lights in a group."""

        async def apply_settings() -> None:
            await self._write(settings_command(brightness, mode, timers))
            self._set_state(brightness=brightness, mode=mode & ALL_MODES, timers=timers)
            await self._write(power_command(is_on, timers_enabled))
            self._set_state(is_on=is_on, timers_enabled=timers_enabled)

        await self._run(apply_settings)

    async def restore_defaults(self) -> None:
        """Put the brightness, modes and timers back to the factory settings.

        The state is not updated: call update() to read the new settings.
        """

        async def restore_defaults() -> None:
            await self._write(CMD_RESTORE_DEFAULTS)

        await self._run(restore_defaults)

    async def set_brightness(self, brightness: int) -> None:
        """Set the brightness as a device level (10-99)."""

        async def set_brightness() -> None:
            await self._write(brightness_command(brightness))
            self._set_state(brightness=brightness)

        await self._run(set_brightness)

    async def set_mode(self, mode: Mode) -> None:
        """Select the mode(s) the controller cycles through."""

        async def set_mode() -> None:
            await self._write(mode_command(mode))
            self._set_state(mode=mode & ALL_MODES)

        await self._run(set_mode)

    async def stop(self) -> None:
        """Close the connection for good.

        A connection that is still being set up is closed as soon as it is
        there, so the controller is never left with a connection nobody uses.
        """
        self._stopped = True
        self._cancel_idle_disconnect()
        await self._disconnect()

    async def _run[T](self, operation: Callable[[], Awaitable[T]]) -> T:
        """Run an operation on its own, once more on a new connection if needed."""
        async with self._operation_lock:
            self._cancel_idle_disconnect()
            try:
                if self.is_connected:
                    try:
                        return await operation()
                    except BLEAK_EXCEPTIONS as err:
                        if self._stopped:
                            raise
                        # The connection may have gone stale without notice.
                        _LOGGER.debug(
                            "%s: reconnecting to try again after: %r",
                            self.address,
                            err,
                        )
                        await self._disconnect()
                try:
                    return await operation()
                except BLEAK_EXCEPTIONS:
                    await self._disconnect()
                    raise
            finally:
                self._schedule_idle_disconnect()

    async def _query(self) -> DeviceState:
        """Send the state queries and wait for both reports."""
        reports = asyncio.get_running_loop().create_future()
        self._reports = reports
        self._awaited_reports = {PowerReport, SettingsReport}
        try:
            await self._write(power_query(self._now().time()))
            await self._write(CMD_QUERY_SETTINGS)
            async with asyncio.timeout(UPDATE_TIMEOUT):
                await reports
        finally:
            self._reports = None
            if reports.done() and not reports.cancelled():
                # Mark an error that was not awaited as seen.
                reports.exception()
        return self.state

    async def _write(self, command: bytes) -> None:
        """Send a command, connecting first when needed."""
        client = await self._ensure_connected()
        _LOGGER.debug("%s: sending %s", self.address, command.hex())
        await client.write_gatt_char(self._write_char, command, response=True)

    async def _ensure_connected(self) -> BleakClientWithServiceCache:
        """Return a connected client, connecting when needed."""
        if self._stopped:
            raise BleakError(f"{self.address}: the connection was closed")
        if self._client is not None and self._client.is_connected:
            return self._client
        _LOGGER.debug("%s: connecting", self.address)
        client = await establish_connection(
            BleakClientWithServiceCache,
            self._ble_device,
            self._ble_device.name or self.address,
            disconnected_callback=self._on_disconnect,
            use_services_cache=True,
            ble_device_callback=lambda: self._ble_device,
        )
        try:
            service = client.services.get_service(SERVICE_UUID)
            write_char = service and service.get_characteristic(WRITE_CHAR_UUID)
            notify_char = service and service.get_characteristic(NOTIFY_CHAR_UUID)
            if not write_char or not notify_char:
                raise CharacteristicMissingError(
                    f"{self.address} does not look like a Lights App controller"
                )
            await client.start_notify(notify_char, self._on_notify)
            if self._stopped:
                raise BleakError(f"{self.address}: closed while connecting")
        except BaseException:
            await client.disconnect()
            raise
        self._client = client
        self._write_char = write_char
        _LOGGER.debug("%s: connected", self.address)
        for callback in list(self._connect_callbacks):
            callback()
        return client

    async def _disconnect(self) -> None:
        """Close the connection on purpose; the state is kept."""
        if client := self._client:
            self._client = None
            self._write_char = None
            try:
                await client.disconnect()
            except BLEAK_EXCEPTIONS as err:
                _LOGGER.debug("%s: error while disconnecting: %r", self.address, err)

    def _schedule_idle_disconnect(self) -> None:
        """Close the connection later, unless it is used again before then."""
        if (
            self._idle_disconnect_delay is None
            or self._stopped
            or not self.is_connected
        ):
            return
        self._idle_timer = asyncio.get_running_loop().call_later(
            self._idle_disconnect_delay, self._on_idle
        )

    def _cancel_idle_disconnect(self) -> None:
        if self._idle_timer:
            self._idle_timer.cancel()
            self._idle_timer = None

    def _on_idle(self) -> None:
        self._idle_timer = None
        self._idle_task = asyncio.get_running_loop().create_task(
            self._disconnect_when_idle()
        )

    async def _disconnect_when_idle(self) -> None:
        async with self._operation_lock:
            # A new timer means the connection was used while waiting.
            if self._idle_timer is None and not self._stopped:
                _LOGGER.debug("%s: closing the idle connection", self.address)
                await self._disconnect()

    def _on_disconnect(self, client: BleakClientWithServiceCache) -> None:
        """Handle a connection that dropped unexpectedly."""
        if client is not self._client:
            # Closed on purpose, or a connection that never finished setting up.
            return
        _LOGGER.debug("%s: connection lost", self.address)
        self._client = None
        self._write_char = None
        self._cancel_idle_disconnect()
        if (reports := self._reports) and not reports.done():
            reports.set_exception(BleakError(f"{self.address}: connection lost"))
        for callback in list(self._disconnect_callbacks):
            callback()

    def _on_notify(self, _: BleakGATTCharacteristic, data: bytearray) -> None:
        """Handle a notification from the controller."""
        raw = bytes(data)
        _LOGGER.debug("%s: received %s", self.address, raw.hex())
        match parse_notification(raw):
            case PowerReport(is_on=is_on, timers_enabled=timers_enabled):
                self.last_power_report = raw.hex()
                self._set_state(is_on=is_on, timers_enabled=timers_enabled)
                self._report_received(PowerReport)
            case SettingsReport(brightness=brightness, mode=mode, timers=timers):
                self.last_settings_report = raw.hex()
                self._set_state(brightness=brightness, mode=mode, timers=timers)
                self._report_received(SettingsReport)
            case _:
                self.unrecognised_notifications.append(raw.hex())

    def _report_received(self, report: type) -> None:
        """Let update() continue once it has every report it asked for."""
        self._awaited_reports.discard(report)
        if (
            not self._awaited_reports
            and (reports := self._reports)
            and not reports.done()
        ):
            reports.set_result(None)

    @property
    def _timers_enabled(self) -> bool:
        """Whether the timers are enabled, to keep that when switching the lights."""
        return bool(self.state.timers_enabled)

    def _set_state(self, **changes: bool | int | Mode | Timers) -> None:
        """Update the state and tell the listeners when it changed."""
        state = replace(self.state, **changes)
        if state == self.state:
            return
        self.state = state
        if self._reports is not None:
            # update() is collecting the state and returns it in one piece.
            return
        for callback in list(self._state_callbacks):
            callback(state)
