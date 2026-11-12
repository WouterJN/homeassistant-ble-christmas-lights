"""Base entity for the BLE Christmas Lights integration."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import override

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ChristmasLightsCoordinator
from .device import BLEAK_EXCEPTIONS
from .group import ChristmasLightsGroupCoordinator


class ChristmasLightsEntity(
    CoordinatorEntity[ChristmasLightsCoordinator | ChristmasLightsGroupCoordinator]
):
    """An entity of a set of Christmas lights, or of a group of them."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ChristmasLightsCoordinator | ChristmasLightsGroupCoordinator,
        key: str | None = None,
    ) -> None:
        """Initialize the entity; key tells the entities of one set apart."""
        super().__init__(coordinator)
        # The light came first and has the ID of the lights alone as unique ID.
        self._attr_unique_id = (
            coordinator.unique_id if key is None else f"{coordinator.unique_id}_{key}"
        )
        self._attr_device_info = coordinator.device_info

    @property
    @override
    def available(self) -> bool:
        """Available while the state is known and the lights can be reached."""
        return (
            super().available
            and self.coordinator.reachable
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
