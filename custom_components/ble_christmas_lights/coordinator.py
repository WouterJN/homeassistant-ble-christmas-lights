"""Coordinator for the BLE Christmas Lights integration."""

from __future__ import annotations

import logging
from typing import override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import UPDATE_INTERVAL
from .device import BLEAK_EXCEPTIONS, ChristmasLights, DeviceState

_LOGGER = logging.getLogger(__name__)

type ChristmasLightsConfigEntry = ConfigEntry[ChristmasLightsCoordinator]


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
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=UPDATE_INTERVAL,
            always_update=False,
        )
        self.device = device
        entry.async_on_unload(device.register_callback(self._async_device_updated))

    @override
    async def _async_update_data(self) -> DeviceState:
        """Ask the controller for its state, reconnecting when needed."""
        try:
            return await self.device.update()
        except BLEAK_EXCEPTIONS as err:
            raise UpdateFailed(f"Could not reach the lights: {err}") from err

    @callback
    def _async_device_updated(self, state: DeviceState) -> None:
        """Handle state pushed by the controller."""
        if state.is_on is None:
            # The connection dropped; show the lights as unavailable until
            # the next poll reconnects.
            self.async_set_update_error(UpdateFailed("Connection lost"))
        else:
            self.async_set_updated_data(state)
