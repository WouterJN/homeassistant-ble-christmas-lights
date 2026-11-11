"""Tests for the diagnostics download."""

import json
from unittest.mock import patch

from homeassistant.const import CONF_ADDRESS

from .conftest import ADDRESS, NAME, make_service_info
from .test_light import ble_device, entry, setup  # noqa: F401
from custom_components.ble_christmas_lights.diagnostics import (
    async_get_config_entry_diagnostics,
)

BLUETOOTH = "custom_components.ble_christmas_lights.diagnostics.bluetooth"


async def test_diagnostics(hass, entry, ble_device, controller):  # noqa: F811
    controller.mode = 0x41
    await setup(hass, entry)
    controller._notify(None, bytearray.fromhex("0a0b0c"))

    with patch(
        f"{BLUETOOTH}.async_last_service_info", return_value=make_service_info()
    ):
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["advertisement"]["name"] == NAME
    assert diagnostics["connected"] is True
    assert diagnostics["state"] == {
        "is_on": True,
        "brightness": 99,
        "mode": "0x41",
        "modes": ["stay_on", "wave"],
    }
    assert diagnostics["notifications"] == {
        "power_report": "0000020100",
        "settings_report": "02000f63" + "00" * 12 + "0341",
        "unrecognised": ["0a0b0c"],
    }
    # Safe to attach to a public issue.
    assert entry.data[CONF_ADDRESS] == ADDRESS
    assert ADDRESS.lower() not in json.dumps(diagnostics).lower()


async def test_diagnostics_without_advertisement(
    hass,
    entry,  # noqa: F811
    ble_device,  # noqa: F811
    controller,
):
    await setup(hass, entry)
    with patch(f"{BLUETOOTH}.async_last_service_info", return_value=None):
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["advertisement"] is None
    json.dumps(diagnostics)
