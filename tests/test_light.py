"""Tests for setting up the integration and the light entity."""

from datetime import timedelta
from unittest.mock import patch

from bleak.exc import BleakError
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_EFFECT_LIST,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_ADDRESS,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .conftest import ADDRESS, POWER_OFF_REPORT, make_service_info, settings_report
from custom_components.ble_christmas_lights.const import DOMAIN

ENTITY_ID = "light.christmas_lights_eeff"


@pytest.fixture
def entry(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDRESS,
        title="Christmas lights EEFF",
        data={CONF_ADDRESS: ADDRESS},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def ble_device():
    with patch(
        "custom_components.ble_christmas_lights.bluetooth.async_ble_device_from_address",
        return_value=make_service_info().device,
    ):
        yield


async def setup(hass, entry):
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def call(hass, service, **data):
    await hass.services.async_call(
        "light", service, {ATTR_ENTITY_ID: ENTITY_ID, **data}, blocking=True
    )


async def test_setup_and_state(hass, entry, ble_device, controller):
    controller.brightness = 99
    controller.mode = 0x20
    await setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    state = hass.states.get(ENTITY_ID)
    assert state.state == STATE_ON
    assert state.attributes[ATTR_BRIGHTNESS] == 255
    assert state.attributes[ATTR_EFFECT] == "fast_twinkling"
    assert "all_modes" in state.attributes[ATTR_EFFECT_LIST]

    await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    controller.disconnect.assert_awaited()


async def test_setup_retries_when_not_found(hass, entry):
    with patch(
        "custom_components.ble_christmas_lights.bluetooth.async_ble_device_from_address",
        return_value=None,
    ):
        await setup(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_retries_when_unreachable(
    hass, entry, ble_device, controller, monkeypatch
):
    async def fail(*args, **kwargs):
        raise BleakError("out of range")

    monkeypatch.setattr(controller, "write_gatt_char", fail)
    await setup(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_turn_on_with_brightness_and_effect(hass, entry, ble_device, controller):
    await setup(hass, entry)
    controller.written.clear()

    await call(hass, "turn_on", brightness=128, effect="wave")
    assert [c.hex() for c in controller.written] == [
        "03010137",
        "0501020301",
        "01010101",
    ]
    state = hass.states.get(ENTITY_ID)
    assert state.attributes[ATTR_EFFECT] == "wave"
    # The controller has 90 levels, so 128 comes back as the nearest step.
    assert state.attributes[ATTR_BRIGHTNESS] == 129


async def test_turn_off(hass, entry, ble_device, controller):
    await setup(hass, entry)
    await call(hass, "turn_off")
    assert controller.written[-1].hex() == "01010100"
    assert hass.states.get(ENTITY_ID).state == STATE_OFF


async def test_pushed_state(hass, entry, ble_device, controller):
    await setup(hass, entry)
    controller.notify(POWER_OFF_REPORT)
    controller.notify(settings_report(10, 0x41))
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY_ID)
    assert state.state == STATE_OFF
    # A mix of modes set from the phone app is not one of the effects.
    assert hass.states.get(ENTITY_ID).attributes.get(ATTR_EFFECT) is None


async def test_all_modes_effect(hass, entry, ble_device, controller):
    controller.mode = 0x00
    await setup(hass, entry)
    assert hass.states.get(ENTITY_ID).attributes[ATTR_EFFECT] == "all_modes"
    await call(hass, "turn_on", effect="all_modes")
    assert controller.written[-2].hex() == "050102037f"


async def test_unavailable_after_disconnect_and_back(
    hass, entry, ble_device, controller
):
    await setup(hass, entry)
    controller.drop_connection()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_ON


async def test_command_error(hass, entry, ble_device, controller, monkeypatch):
    await setup(hass, entry)

    async def fail(*args, **kwargs):
        raise BleakError("gone")

    monkeypatch.setattr(controller, "write_gatt_char", fail)
    with pytest.raises(HomeAssistantError):
        await call(hass, "turn_off")
