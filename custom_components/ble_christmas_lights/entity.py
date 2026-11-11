"""Base entity for the BLE Christmas Lights integration."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import override

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SUPPORTED_NAME
from .coordinator import ChristmasLightsCoordinator
from .device import BLEAK_EXCEPTIONS


class ChristmasLightsEntity(CoordinatorEntity[ChristmasLightsCoordinator]):
    """An entity of a set of Christmas lights."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: ChristmasLightsCoordinator, key: str | None = None
    ) -> None:
        """Initialize the entity; key tells the entities of one set apart."""
        super().__init__(coordinator)
        address = coordinator.device.address
        # The light came first and has the address alone as its unique ID.
        self._attr_unique_id = address if key is None else f"{address}_{key}"
        # The start of the advertised name says which kind of lights it is.
        kind = SUPPORTED_NAME.fullmatch(coordinator.device.name or "")
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, address)},
            name=coordinator.config_entry.title,
            model="Lights App controller",
            model_id=kind and kind.group(1),
        )

    @property
    @override
    def available(self) -> bool:
        """Available while the state is known and the lights can be reached."""
        return (
            super().available
            and not self.coordinator.reconnect_overdue
            and self.coordinator.data.is_on is not None
        )

    async def _async_call(self, command: Awaitable[None]) -> None:
        """Send a command and turn Bluetooth errors into a readable error."""
        try:
            await command
        except BLEAK_EXCEPTIONS as err:
            # The connection is closed by now. Find out whether the lights
            # can still be reached, so the state shown is not a stale one.
            self.coordinator.async_reconnect()
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={"error": str(err)},
            ) from err
