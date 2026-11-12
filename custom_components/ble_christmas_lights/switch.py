"""Switch platform for the BLE Christmas Lights integration."""

from __future__ import annotations

from typing import Any, override

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ChristmasLightsConfigEntry, ChristmasLightsCoordinator
from .entity import ChristmasLightsEntity
from .group import ChristmasLightsGroupCoordinator

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ChristmasLightsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switch."""
    async_add_entities([ChristmasLightsTimerSwitch(entry.runtime_data)])


class ChristmasLightsTimerSwitch(ChristmasLightsEntity, SwitchEntity):
    """Whether the timers of the controller decide when the lights are lit."""

    _attr_translation_key = "timer"

    def __init__(
        self, coordinator: ChristmasLightsCoordinator | ChristmasLightsGroupCoordinator
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "timer")

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether the timers are enabled."""
        return self.coordinator.data.timers_enabled

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the timers."""
        await self._async_call(self.coordinator.device.set_timers_enabled(True))

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the timers."""
        await self._async_call(self.coordinator.device.set_timers_enabled(False))
