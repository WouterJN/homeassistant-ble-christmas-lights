"""The BLE Christmas Lights integration."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.match import ADDRESS, BluetoothCallbackMatcher
from homeassistant.const import CONF_ADDRESS, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .coordinator import ChristmasLightsConfigEntry, ChristmasLightsCoordinator
from .device import ChristmasLights

PLATFORMS: list[Platform] = [Platform.LIGHT]


async def async_setup_entry(
    hass: HomeAssistant, entry: ChristmasLightsConfigEntry
) -> bool:
    """Set up the lights from a config entry."""
    address: str = entry.data[CONF_ADDRESS]
    ble_device = bluetooth.async_ble_device_from_address(hass, address, True)
    if not ble_device:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="device_not_found",
            translation_placeholders={"address": address},
        )

    device = ChristmasLights(ble_device)

    @callback
    def _async_update_ble(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Keep the device's BLEDevice up to date."""
        device.set_ble_device(service_info.device)

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_update_ble,
            BluetoothCallbackMatcher({ADDRESS: address}),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
    )

    coordinator = ChristmasLightsCoordinator(hass, entry, device)
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
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ChristmasLightsConfigEntry
) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.device.stop()
    return unload_ok
