"""Connection to a single Christmas light controller."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
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
    CMD_QUERY_POWER,
    CMD_QUERY_SETTINGS,
    CMD_TURN_OFF,
    CMD_TURN_ON,
    NOTIFY_CHAR_UUID,
    SERVICE_UUID,
    WRITE_CHAR_UUID,
    Mode,
    PowerReport,
    SettingsReport,
    brightness_command,
    mode_command,
    parse_notification,
)

_LOGGER = logging.getLogger(__name__)

# How long to wait for the controller to answer the state queries.
UPDATE_TIMEOUT = 10

BLEAK_EXCEPTIONS = (BleakError, BleakNotFoundError, EOFError, TimeoutError)


class CharacteristicMissingError(BleakError):
    """The device does not expose the expected GATT characteristics."""


@dataclass(frozen=True, slots=True)
class DeviceState:
    """Last known state of the controller."""

    is_on: bool | None = None
    brightness: int | None = None
    mode: Mode | None = None


class ChristmasLights:
    """A Christmas light controller, kept connected over Bluetooth."""

    def __init__(self, ble_device: BLEDevice) -> None:
        """Initialize the device."""
        self._ble_device = ble_device
        self._client: BleakClientWithServiceCache | None = None
        self._write_char: BleakGATTCharacteristic | None = None
        self._connect_lock = asyncio.Lock()
        self._power_received = asyncio.Event()
        self._settings_received = asyncio.Event()
        self._callbacks: list[Callable[[DeviceState], None]] = []
        self.state = DeviceState()

    @property
    def address(self) -> str:
        """Bluetooth address of the device."""
        return self._ble_device.address

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
        """Call callback whenever the state changes; returns an unsubscribe."""
        self._callbacks.append(callback)
        return lambda: self._callbacks.remove(callback)

    async def update(self) -> DeviceState:
        """Ask the controller for its full state and wait for the answer."""
        self._power_received.clear()
        self._settings_received.clear()
        await self._write(CMD_QUERY_POWER)
        await self._write(CMD_QUERY_SETTINGS)
        async with asyncio.timeout(UPDATE_TIMEOUT):
            await self._power_received.wait()
            await self._settings_received.wait()
        return self.state

    async def turn_on(
        self, brightness: int | None = None, mode: Mode | None = None
    ) -> None:
        """Turn the lights on, optionally with a new brightness and mode."""
        if brightness is not None:
            await self.set_brightness(brightness)
        if mode is not None:
            await self.set_mode(mode)
        await self._write(CMD_TURN_ON)
        self._set_state(is_on=True)

    async def turn_off(self) -> None:
        """Turn the lights off."""
        await self._write(CMD_TURN_OFF)
        self._set_state(is_on=False)

    async def set_brightness(self, brightness: int) -> None:
        """Set the brightness as a device level (10-99)."""
        await self._write(brightness_command(brightness))
        self._set_state(brightness=brightness)

    async def set_mode(self, mode: Mode) -> None:
        """Select the mode(s) the controller cycles through."""
        await self._write(mode_command(mode))
        self._set_state(mode=mode)

    async def stop(self) -> None:
        """Close the connection."""
        if client := self._client:
            self._client = None
            await client.disconnect()

    async def _write(self, command: bytes) -> None:
        """Send a command, connecting first when needed."""
        client = await self._ensure_connected()
        try:
            await client.write_gatt_char(self._write_char, command, response=True)
        except BLEAK_EXCEPTIONS:
            await self.stop()
            raise

    async def _ensure_connected(self) -> BleakClientWithServiceCache:
        """Return a connected client, connecting when needed."""
        if self.is_connected:
            return self._client
        async with self._connect_lock:
            if self.is_connected:
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
            except BaseException:
                await client.disconnect()
                raise
            self._client = client
            self._write_char = write_char
            _LOGGER.debug("%s: connected", self.address)
            return client

    def _on_disconnect(self, client: BleakClientWithServiceCache) -> None:
        """Forget the state when the connection drops unexpectedly."""
        if client is not self._client:
            # Closed by stop(), or a connection that never finished setting up.
            return
        _LOGGER.debug("%s: disconnected", self.address)
        self._client = None
        self.state = DeviceState()
        self._fire_callbacks()

    def _on_notify(self, _: BleakGATTCharacteristic, data: bytearray) -> None:
        """Handle a notification from the controller."""
        _LOGGER.debug("%s: received %s", self.address, data.hex())
        match parse_notification(bytes(data)):
            case PowerReport(is_on=is_on):
                self._set_state(is_on=is_on)
                self._power_received.set()
            case SettingsReport(brightness=brightness, mode=mode):
                self._set_state(brightness=brightness, mode=mode)
                self._settings_received.set()

    def _set_state(self, **changes: bool | int | Mode) -> None:
        """Update the state and tell the listeners when it changed."""
        state = replace(self.state, **changes)
        if state != self.state:
            self.state = state
            self._fire_callbacks()

    def _fire_callbacks(self) -> None:
        for callback in list(self._callbacks):
            callback(self.state)
