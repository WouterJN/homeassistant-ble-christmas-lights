"""Coordinator for the BLE Christmas Lights integration."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_STAY_CONNECTED,
    DEFAULT_STAY_CONNECTED,
    IDLE_UPDATE_INTERVAL,
    RECONNECT_GRACE,
    SUPPORTED_NAME,
    UPDATE_INTERVAL,
)
from .device import BLEAK_EXCEPTIONS, ChristmasLights, DeviceState

_LOGGER = logging.getLogger(__name__)

# The config entry of a set of lights. A group has a config entry too, with a
# ChristmasLightsGroupCoordinator; the platforms treat both alike.
type ChristmasLightsConfigEntry = ConfigEntry[ChristmasLightsCoordinator]


def stay_connected(entry: ChristmasLightsConfigEntry) -> bool:
    """Return whether the connection to the lights is kept open."""
    return entry.options.get(CONF_STAY_CONNECTED, DEFAULT_STAY_CONNECTED)


class ChristmasLightsCoordinator(DataUpdateCoordinator[DeviceState]):
    """Polls the controller and passes on the state it pushes."""

    config_entry: ChristmasLightsConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ChristmasLightsConfigEntry,
        device: ChristmasLights,
    ) -> None:
        """Initialize the coordinator."""
        self._poll_interval = (
            UPDATE_INTERVAL if stay_connected(entry) else IDLE_UPDATE_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=self._poll_interval,
            # Tell the light about every state that was read, also when it
            # is the same as before: the light may have become unavailable
            # in between because reconnecting took too long.
            always_update=True,
        )
        self.device = device
        self.unique_id = device.address
        # The start of the advertised name says which kind of lights it is.
        kind = SUPPORTED_NAME.fullmatch(device.name or "")
        self.device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, device.address)},
            name=entry.title,
            model="Lights App controller",
            model_id=kind and kind.group(1),
        )
        # Set when reconnecting takes longer than RECONNECT_GRACE.
        self.reconnect_overdue = False
        self._cancel_grace: CALLBACK_TYPE | None = None
        entry.async_on_unload(self._async_end_grace)
        entry.async_on_unload(device.register_callback(self.async_set_updated_data))
        entry.async_on_unload(device.register_disconnect_callback(self.async_reconnect))

    @property
    def reachable(self) -> bool:
        """Whether the lights are not taking too long to reconnect."""
        return not self.reconnect_overdue

    @override
    async def _async_update_data(self) -> DeviceState:
        """Ask the controller for its state, reconnecting when needed."""
        try:
            state = await self.device.update()
        except BLEAK_EXCEPTIONS as err:
            # Keep trying at the short interval until the lights are back.
            self.update_interval = UPDATE_INTERVAL
            raise UpdateFailed(f"Could not reach the lights: {err}") from err
        finally:
            # From here on the outcome of this attempt decides whether the
            # lights are available.
            self._async_end_grace()
        self.update_interval = self._poll_interval
        return state

    @callback
    def async_reconnect(self) -> None:
        """Reconnect and read the state now, instead of at the next poll.

        The lights keep their last state in the meantime. They become
        unavailable when this fails, or when it takes longer than
        RECONNECT_GRACE.
        """
        if self._cancel_grace is None:
            self._cancel_grace = async_call_later(
                self.hass, RECONNECT_GRACE, self._async_grace_expired
            )
        self.config_entry.async_create_background_task(
            self.hass,
            self.async_request_refresh(),
            name=f"{self.name} reconnect",
        )

    @callback
    def async_device_seen(self) -> None:
        """Try again right away when lights that were unreachable show up."""
        if not self.last_update_success:
            self.async_reconnect()

    @callback
    def _async_grace_expired(self, _: datetime) -> None:
        """Stop showing the last state: reconnecting takes too long."""
        self._cancel_grace = None
        if self.last_update_success and not self.reconnect_overdue:
            _LOGGER.debug("%s: still reconnecting, now unavailable", self.name)
            self.reconnect_overdue = True
            self.async_update_listeners()

    @callback
    def _async_end_grace(self) -> None:
        if self._cancel_grace:
            self._cancel_grace()
            self._cancel_grace = None
        self.reconnect_overdue = False
