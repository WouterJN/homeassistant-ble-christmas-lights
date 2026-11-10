"""Coordinator for the BLE Christmas Lights integration."""

from __future__ import annotations

import logging
from typing import override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_STAY_CONNECTED,
    DEFAULT_STAY_CONNECTED,
    IDLE_UPDATE_INTERVAL,
    UPDATE_INTERVAL,
)
from .device import BLEAK_EXCEPTIONS, ChristmasLights, DeviceState

_LOGGER = logging.getLogger(__name__)

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
            always_update=False,
        )
        self.device = device
        entry.async_on_unload(device.register_callback(self.async_set_updated_data))
        entry.async_on_unload(device.register_disconnect_callback(self.async_reconnect))

    @override
    async def _async_update_data(self) -> DeviceState:
        """Ask the controller for its state, reconnecting when needed."""
        try:
            state = await self.device.update()
        except BLEAK_EXCEPTIONS as err:
            # Keep trying at the short interval until the lights are back.
            self.update_interval = UPDATE_INTERVAL
            raise UpdateFailed(f"Could not reach the lights: {err}") from err
        self.update_interval = self._poll_interval
        return state

    @callback
    def async_reconnect(self) -> None:
        """Reconnect and read the state now, instead of at the next poll.

        The lights keep their last state in the meantime and only become
        unavailable when this fails.
        """
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
