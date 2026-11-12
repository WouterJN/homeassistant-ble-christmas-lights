"""The BLE Christmas Lights integration."""

from __future__ import annotations

import probatio

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.match import ADDRESS, BluetoothCallbackMatcher
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import CONF_ADDRESS, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, service
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import ATTR_MODES, DOMAIN, IDLE_DISCONNECT_DELAY, MODES, SERVICE_SET_MODES
from .coordinator import (
    ChristmasLightsConfigEntry,
    ChristmasLightsCoordinator,
    stay_connected,
)
from .device import ChristmasLights
from .group import ChristmasLightsGroupCoordinator, async_groups_of, is_group

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.LIGHT,
    Platform.SWITCH,
    Platform.TIME,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services."""
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SET_MODES,
        entity_domain=LIGHT_DOMAIN,
        schema={
            probatio.Required(ATTR_MODES): probatio.All(
                cv.ensure_list, [probatio.In(list(MODES))], probatio.Length(min=1)
            )
        },
        func="async_set_modes",
    )
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: ChristmasLightsConfigEntry
) -> bool:
    """Set up a set of lights, or a group of them, from a config entry."""
    if is_group(entry):
        group = ChristmasLightsGroupCoordinator(hass, entry)
        entry.runtime_data = group
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        # Lights that were set up before their group.
        for member in group.member_coordinators:
            group.async_member_connected(member.device)
        return True

    address: str = entry.data[CONF_ADDRESS]
    ble_device = bluetooth.async_ble_device_from_address(hass, address, True)
    if not ble_device:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="device_not_found",
            translation_placeholders={"address": address},
        )

    device = ChristmasLights(
        ble_device,
        idle_disconnect_delay=None if stay_connected(entry) else IDLE_DISCONNECT_DELAY,
        # The controller runs its timers on the time it is given here.
        now=dt_util.now,
    )
    coordinator = ChristmasLightsCoordinator(hass, entry, device)

    @callback
    def _async_connected() -> None:
        """Give the lights the settings of the groups they are in."""
        for group in async_groups_of(hass, address):
            group.async_member_connected(device)

    @callback
    def _async_changed() -> None:
        """Let the groups know these lights came, went or changed."""
        for group in async_groups_of(hass, address):
            group.async_member_changed()

    entry.async_on_unload(device.register_connect_callback(_async_connected))
    entry.async_on_unload(coordinator.async_add_listener(_async_changed))

    @callback
    def _async_update_ble(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Keep the BLEDevice up to date and reconnect to lights that are back."""
        device.set_ble_device(service_info.device)
        coordinator.async_device_seen()

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_update_ble,
            BluetoothCallbackMatcher({ADDRESS: address}),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        await device.stop()
        raise
    entry.runtime_data = coordinator

    async def _async_stop(event: Event) -> None:
        """Close the connection when Home Assistant stops."""
        await device.stop()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # A group that was set up before its lights now has lights to control.
    _async_changed()
    entry.async_on_unload(_async_changed)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ChristmasLightsConfigEntry
) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.device.stop()
    return unload_ok
