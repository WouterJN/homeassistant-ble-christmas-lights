"""Light platform for the BLE Christmas Lights integration."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, override

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, EFFECTS
from .coordinator import ChristmasLightsConfigEntry, ChristmasLightsCoordinator
from .device import BLEAK_EXCEPTIONS
from .protocol import brightness_from_ha, brightness_to_ha

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ChristmasLightsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the light."""
    async_add_entities([ChristmasLightsLight(entry.runtime_data)])


class ChristmasLightsLight(CoordinatorEntity[ChristmasLightsCoordinator], LightEntity):
    """The Christmas lights, with brightness and the light modes as effects."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "christmas_lights"
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = list(EFFECTS)

    def __init__(self, coordinator: ChristmasLightsCoordinator) -> None:
        """Initialize the light."""
        super().__init__(coordinator)
        address = coordinator.device.address
        self._attr_unique_id = address
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, address)},
            name=coordinator.config_entry.title,
            model="Lights App controller",
        )

    @property
    @override
    def available(self) -> bool:
        """Only available while the controller reports its state."""
        return super().available and self.coordinator.data.is_on is not None

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether the lights are on."""
        return self.coordinator.data.is_on

    @property
    @override
    def brightness(self) -> int | None:
        """Return the brightness (0-255)."""
        level = self.coordinator.data.brightness
        return None if level is None else brightness_to_ha(level)

    @property
    @override
    def effect(self) -> str | None:
        """Return the active effect, or None for a custom mix of modes."""
        mode = self.coordinator.data.mode
        return next((name for name, flag in EFFECTS.items() if flag == mode), None)

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the lights on, optionally with a brightness and effect."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        effect = kwargs.get(ATTR_EFFECT)
        await self._async_call(
            self.coordinator.device.turn_on(
                brightness=None
                if brightness is None
                else brightness_from_ha(brightness),
                mode=None if effect is None else EFFECTS[effect],
            )
        )

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the lights off."""
        await self._async_call(self.coordinator.device.turn_off())

    async def _async_call(self, command: Awaitable[None]) -> None:
        """Send a command and turn Bluetooth errors into a readable error."""
        try:
            await command
        except BLEAK_EXCEPTIONS as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={"error": str(err)},
            ) from err
