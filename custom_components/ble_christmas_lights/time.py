"""Time platform for the BLE Christmas Lights integration: the timers."""

from __future__ import annotations

from dataclasses import replace
from datetime import time
from typing import override

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import ChristmasLightsConfigEntry, ChristmasLightsCoordinator
from .entity import ChristmasLightsEntity
from .group import ChristmasLightsGroupCoordinator
from .protocol import TIMER_COUNT

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ChristmasLightsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the start and end time of every timer."""
    async_add_entities(
        ChristmasLightsTimerTime(entry.runtime_data, index, field)
        for index in range(TIMER_COUNT)
        for field in ("start", "end")
    )


class ChristmasLightsTimerTime(ChristmasLightsEntity, TimeEntity):
    """The start or end of a period in which the lights are lit.

    A timer that starts and ends at 00:00 is not in use.
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: ChristmasLightsCoordinator | ChristmasLightsGroupCoordinator,
        index: int,
        field: str,
    ) -> None:
        """Initialize the time; index counts the timers from 0."""
        super().__init__(coordinator, f"timer_{index + 1}_{field}")
        self._index = index
        self._field = field
        self._attr_translation_key = f"timer_{field}"
        self._attr_translation_placeholders = {"number": str(index + 1)}
        # Most people have enough with one timer.
        self._attr_entity_registry_enabled_default = index == 0

    @property
    @override
    def native_value(self) -> time | None:
        """Return the start or end of the timer."""
        if (timers := self.coordinator.data.timers) is None:
            return None
        timer = timers[self._index]
        return timer.start if self._field == "start" else timer.end

    @override
    async def async_set_value(self, value: time) -> None:
        """Change the start or end of the timer; the controller has no seconds."""
        if (timers := self.coordinator.data.timers) is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="timers_unknown"
            )
        changed = list(timers)
        changed[self._index] = replace(
            timers[self._index], **{self._field: time(value.hour, value.minute)}
        )
        await self._async_call(
            self.coordinator.device.set_timers((changed[0], changed[1], changed[2]))
        )
