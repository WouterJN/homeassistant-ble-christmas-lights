"""Tests for the timer switch, the timer times and the restore button."""

from datetime import time
from unittest.mock import PropertyMock, patch

from bleak.exc import BleakError
import pytest

from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    EntityCategory,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import ADDRESS, DEFAULT_TIMERS
from .test_light import ENTITY_ID, ble_device, entry, settle, setup  # noqa: F401

pytestmark = pytest.mark.usefixtures("ble_device")

SWITCH = "switch.christmas_lights_eeff_timer"
START_1 = "time.christmas_lights_eeff_timer_1_start"
END_1 = "time.christmas_lights_eeff_timer_1_end"
START_2 = "time.christmas_lights_eeff_timer_2_start"
BUTTON = "button.christmas_lights_eeff_restore_default_settings"


@pytest.fixture
def all_entities_enabled():
    """Also set up the second and third timer."""
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        new_callable=PropertyMock,
        return_value=True,
    ):
        yield


async def test_entities(hass, entry, controller):  # noqa: F811
    await setup(hass, entry)
    registry = er.async_get(hass)
    entities = {
        entity.entity_id: entity
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert sorted(entities) == [
        BUTTON,
        ENTITY_ID,
        SWITCH,
        END_1,
        START_1,
        "time.christmas_lights_eeff_timer_2_end",
        START_2,
        "time.christmas_lights_eeff_timer_3_end",
        "time.christmas_lights_eeff_timer_3_start",
    ]
    # The light keeps the unique ID it had before there were other entities.
    assert entities[ENTITY_ID].unique_id == ADDRESS
    assert len({entity.unique_id for entity in entities.values()}) == len(entities)
    assert entities[SWITCH].entity_category is None
    assert entities[START_1].entity_category is EntityCategory.CONFIG
    assert entities[BUTTON].entity_category is EntityCategory.CONFIG
    # One timer is enough for most people.
    assert entities[START_1].disabled_by is None
    assert entities[START_2].disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(START_2) is None

    (device,) = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert device.model_id == "LED-4-02"


async def test_clock_is_set_to_the_time_of_home_assistant(
    hass,
    entry,  # noqa: F811
    controller,
    freezer,
):
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-12-24 19:31:05+00:00")
    await setup(hass, entry)
    assert controller.clock == (20, 31, 5)


async def test_timer_switch(hass, entry, controller):  # noqa: F811
    await setup(hass, entry)
    assert hass.states.get(SWITCH).state == STATE_OFF

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: SWITCH}, blocking=True
    )
    # On with timers: the lights stay on.
    assert controller.written[-1].hex() == "01010103"
    assert hass.states.get(SWITCH).state == STATE_ON
    assert hass.states.get(ENTITY_ID).state == STATE_ON

    # Switching the lights keeps the timers enabled.
    await hass.services.async_call(
        "light", "turn_off", {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
    )
    assert controller.written[-1].hex() == "01010102"
    assert hass.states.get(SWITCH).state == STATE_ON
    assert hass.states.get(ENTITY_ID).state == STATE_OFF

    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: SWITCH}, blocking=True
    )
    assert controller.written[-1].hex() == "01010100"
    assert hass.states.get(SWITCH).state == STATE_OFF
    assert hass.states.get(ENTITY_ID).state == STATE_OFF


async def test_light_is_on_with_timers_enabled(hass, entry, controller):  # noqa: F811
    # "On with timers" used to be read as off.
    controller.timers_enabled = True
    await setup(hass, entry)
    assert hass.states.get(ENTITY_ID).state == STATE_ON
    assert hass.states.get(SWITCH).state == STATE_ON


async def test_timer_times(hass, entry, controller, all_entities_enabled):  # noqa: F811
    controller.timers = DEFAULT_TIMERS
    await setup(hass, entry)
    assert hass.states.get(START_1).state == "18:00:00"
    assert hass.states.get(END_1).state == "23:59:00"
    # A timer that is not in use.
    assert hass.states.get(START_2).state == "00:00:00"

    await hass.services.async_call(
        "time",
        "set_value",
        {ATTR_ENTITY_ID: START_1, "time": time(16, 30, 45)},
        blocking=True,
    )
    # All three timers are sent; the controller has no seconds.
    assert controller.written[-1].hex() == "04010c" + "101e173b" + "00" * 8
    assert hass.states.get(START_1).state == "16:30:00"
    assert hass.states.get(END_1).state == "23:59:00"

    await hass.services.async_call(
        "time",
        "set_value",
        {ATTR_ENTITY_ID: START_2, "time": "06:15:00"},
        blocking=True,
    )
    assert controller.written[-1].hex() == "04010c" + "101e173b" + "060f0000" + "00" * 4
    assert hass.states.get(START_2).state == "06:15:00"
    assert hass.states.get(START_1).state == "16:30:00"


async def test_timer_time_error(hass, entry, controller):  # noqa: F811
    await setup(hass, entry)
    controller.failing_writes = 100
    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call(
            "time",
            "set_value",
            {ATTR_ENTITY_ID: END_1, "time": "22:00:00"},
            blocking=True,
        )
    assert error.value.translation_key == "communication_error"
    await settle(hass)
    assert hass.states.get(END_1).state == STATE_UNAVAILABLE
    assert hass.states.get(SWITCH).state == STATE_UNAVAILABLE


async def test_restore_defaults_button(hass, entry, controller):  # noqa: F811
    controller.brightness = 20
    controller.mode = 0x41
    await setup(hass, entry)
    assert hass.states.get(ENTITY_ID).attributes["brightness"] != 255

    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: BUTTON}, blocking=True
    )
    await settle(hass)
    assert bytes.fromhex("07010702631200173b01") in controller.written
    # The new settings were read from the controller.
    state = hass.states.get(ENTITY_ID)
    assert state.attributes["brightness"] == 255
    assert state.attributes["effect"] == "all_modes"
    assert hass.states.get(START_1).state == "18:00:00"
    assert hass.states.get(END_1).state == "23:59:00"


async def test_restore_defaults_button_error(hass, entry, controller):  # noqa: F811
    await setup(hass, entry)
    controller.connect_error = BleakError("out of range")
    controller.failing_writes = 1
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button", "press", {ATTR_ENTITY_ID: BUTTON}, blocking=True
        )
