"""Diagnostics for the BLE Christmas Lights integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .const import CONF_MEMBERS, CONF_SETTINGS, MODES
from .coordinator import ChristmasLightsConfigEntry
from .group import is_group


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ChristmasLightsConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    The Bluetooth address is left out; everything else is what is needed to
    add support for a controller that behaves differently.
    """
    coordinator = entry.runtime_data
    if is_group(entry):
        return {
            "group": {
                "members": len(entry.data[CONF_MEMBERS]),
                "members_set_up": len(coordinator.member_coordinators),
                "settings": entry.data.get(CONF_SETTINGS),
            }
        }
    device = coordinator.device
    state = device.state
    service_info = bluetooth.async_last_service_info(
        hass, device.address, connectable=True
    )

    return {
        "options": dict(entry.options),
        "advertisement": service_info
        and {
            "name": service_info.name,
            "rssi": service_info.rssi,
            "service_uuids": service_info.service_uuids,
            "manufacturer_data": {
                str(company): data.hex()
                for company, data in service_info.manufacturer_data.items()
            },
            "service_data": {
                uuid: data.hex() for uuid, data in service_info.service_data.items()
            },
        },
        "connected": device.is_connected,
        "last_update_success": coordinator.last_update_success,
        "state": {
            "is_on": state.is_on,
            "brightness": state.brightness,
            "mode": None if state.mode is None else f"0x{int(state.mode):02x}",
            "modes": None
            if state.mode is None
            else [name for name, flag in MODES.items() if flag in state.mode],
            "timers_enabled": state.timers_enabled,
            "timers": state.timers
            and [f"{timer.start:%H:%M}-{timer.end:%H:%M}" for timer in state.timers],
        },
        "notifications": {
            "power_report": device.last_power_report,
            "settings_report": device.last_settings_report,
            "unrecognised": list(device.unrecognised_notifications),
        },
    }
