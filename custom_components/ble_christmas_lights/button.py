"""Button platform for the BLE Christmas Lights integration."""

from __future__ import annotations

from typing import override

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
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
    """Set up the button."""
    coordinator = entry.runtime_data
    entities: list[ButtonEntity] = [ChristmasLightsRestoreDefaultsButton(coordinator)]
    if isinstance(coordinator, ChristmasLightsGroupCoordinator):
        entities.append(ChristmasLightsGroupSyncButton(coordinator))
    async_add_entities(entities)


class ChristmasLightsRestoreDefaultsButton(ChristmasLightsEntity, ButtonEntity):
    """Puts the brightness, modes and timers back to the factory settings."""

    _attr_translation_key = "restore_defaults"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: ChristmasLightsCoordinator | ChristmasLightsGroupCoordinator
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, "restore_defaults")

    @override
    async def async_press(self) -> None:
        """Restore the default settings and read what they are."""
        await self._async_call(self.coordinator.device.restore_defaults())
        await self.coordinator.async_request_refresh()


class ChristmasLightsGroupSyncButton(ChristmasLightsEntity, ButtonEntity):
    """Gives all lights of a group the settings of the group again."""

    _attr_translation_key = "sync"

    def __init__(self, coordinator: ChristmasLightsGroupCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator, "sync")
        self._group = coordinator

    @override
    async def async_press(self) -> None:
        """Send the settings of the group to its lights."""
        await self._async_call(self._group.device.sync())
