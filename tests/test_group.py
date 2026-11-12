"""Tests for groups of lights."""

from unittest.mock import patch

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_ADDRESS,
    CONF_NAME,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import ADDRESS, NAME, FakeController
from custom_components.ble_christmas_lights.const import (
    CONF_MEMBERS,
    CONF_SETTINGS,
    DOMAIN,
)
from custom_components.ble_christmas_lights.diagnostics import (
    async_get_config_entry_diagnostics,
)

ADDRESS_2 = "11:22:33:44:55:66"

LIGHT = "light.tree"
SWITCH = "switch.tree_timer"
START_1 = "time.tree_timer_1_start"
BUTTON = "button.tree_restore_default_settings"
SYNC_BUTTON = "button.tree_send_settings_to_the_lights"
MEMBER_1 = "light.christmas_lights_eeff"
MEMBER_2 = "light.christmas_lights_5566"

# What a new group gives its lights: full brightness, one timer from 18:00
# to 23:59, "Auto Rotate", and then on without the timers.
SYNC = ["08010f63" + "1200173b" + "00" * 8 + "0180", "01010101"]


@pytest.fixture(autouse=True)
def ble_devices():
    with patch(
        "custom_components.ble_christmas_lights.bluetooth.async_ble_device_from_address",
        side_effect=lambda hass, address, connectable: BLEDevice(address, NAME, {}),
    ):
        yield


@pytest.fixture
def second(controllers):
    """The controller of the second set of lights."""
    return controllers.setdefault(ADDRESS_2, FakeController())


def add_lights(hass, address):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=address,
        title=f"Christmas lights {address.replace(':', '')[-4:]}",
        data={CONF_ADDRESS: address},
    )
    entry.add_to_hass(hass)
    return entry


def add_group(hass, members=(ADDRESS, ADDRESS_2), **data):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Tree", data={CONF_MEMBERS: list(members), **data}
    )
    entry.add_to_hass(hass)
    return entry


async def settle(hass):
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.fixture
async def group(hass, controller, second):
    """Two sets of lights in a group, all set up."""
    for address in (ADDRESS, ADDRESS_2):
        await hass.config_entries.async_setup(add_lights(hass, address).entry_id)
    entry = add_group(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await settle(hass)
    return entry


def written(fake):
    return [command.hex() for command in fake.written]


async def call(hass, domain, service, entity_id, **data):
    await hass.services.async_call(
        domain, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
    )


async def test_setup(hass, group, controller, second):
    assert group.state is ConfigEntryState.LOADED
    entities = sorted(
        entity.entity_id
        for entity in er.async_entries_for_config_entry(
            er.async_get(hass), group.entry_id
        )
    )
    assert entities == [
        BUTTON,
        SYNC_BUTTON,
        LIGHT,
        SWITCH,
        "time.tree_timer_1_end",
        START_1,
        "time.tree_timer_2_end",
        "time.tree_timer_2_start",
        "time.tree_timer_3_end",
        "time.tree_timer_3_start",
    ]
    (device,) = dr.async_entries_for_config_entry(dr.async_get(hass), group.entry_id)
    assert device.name == "Tree"
    assert device.model == "Group of lights"

    # A new group starts with the defaults of the app...
    state = hass.states.get(LIGHT)
    assert state.state == STATE_ON
    assert state.attributes["brightness"] == 255
    assert state.attributes["effect"] == "all_modes"
    assert hass.states.get(SWITCH).state == STATE_OFF
    assert hass.states.get(START_1).state == "18:00:00"

    # ...and gives them to its lights.
    for fake in (controller, second):
        assert written(fake)[-2:] == SYNC
    assert hass.states.get(MEMBER_1).attributes["effect"] == "all_modes"

    assert await hass.config_entries.async_unload(group.entry_id)
    # The connections belong to the lights, not to the group.
    assert hass.states.get(MEMBER_1).state == STATE_ON


async def test_group_set_up_before_its_lights(hass, controller, second):
    group = add_group(hass)
    await hass.config_entries.async_setup(group.entry_id)
    await settle(hass)
    assert hass.states.get(LIGHT).state == STATE_UNAVAILABLE

    await hass.config_entries.async_setup(add_lights(hass, ADDRESS).entry_id)
    await settle(hass)
    assert hass.states.get(LIGHT).state == STATE_ON
    assert written(controller)[-2:] == SYNC
    assert second.written == []


async def test_commands_go_to_all_lights(hass, group, controller, second):
    for fake in (controller, second):
        fake.written.clear()

    await call(hass, "light", "turn_on", LIGHT, brightness=128, effect="wave")
    for fake in (controller, second):
        assert written(fake) == ["03010136", "0501020301", "01010101"]
    state = hass.states.get(LIGHT)
    assert state.attributes["brightness"] == 127
    assert state.attributes["effect"] == "wave"
    assert hass.states.get(MEMBER_2).attributes["effect"] == "wave"

    await call(hass, "switch", "turn_on", SWITCH)
    await call(hass, "light", "turn_off", LIGHT)
    await call(hass, "time", "set_value", START_1, time="16:30:00")
    await hass.services.async_call(
        DOMAIN,
        "set_modes",
        {ATTR_ENTITY_ID: LIGHT, "modes": ["stay_on", "wave"]},
        blocking=True,
    )
    for fake in (controller, second):
        assert written(fake)[3:] == [
            "01010103",
            # Off, with the timers of the group still enabled.
            "01010102",
            "04010c" + "101e173b" + "00" * 8,
            "0501020341",
        ]
    assert hass.states.get(LIGHT).state == STATE_OFF
    assert hass.states.get(LIGHT).attributes.get("effect") is None
    assert hass.states.get(SWITCH).state == STATE_ON
    assert hass.states.get(START_1).state == "16:30:00"
    assert hass.states.get(MEMBER_1).state == STATE_OFF


async def test_group_overrides_the_timers_of_its_lights(
    hass, group, controller, second
):
    # One set of lights had its timers enabled on its own.
    await call(hass, "switch", "turn_on", "switch.christmas_lights_eeff_timer")
    assert written(controller)[-1] == "01010103"
    await call(hass, "light", "turn_off", LIGHT)
    assert written(controller)[-1] == "01010100"
    assert written(second)[-1] == "01010100"


async def test_settings_are_remembered(hass, group, controller, second):
    await call(hass, "light", "turn_on", LIGHT, brightness=1, effect="stay_on")
    await call(hass, "light", "turn_off", LIGHT)
    assert group.data[CONF_SETTINGS] == {
        "is_on": False,
        "timers_enabled": False,
        "brightness": 10,
        "mode": 0x40,
        "timers": [[18, 0, 23, 59], [0, 0, 0, 0], [0, 0, 0, 0]],
    }

    await hass.config_entries.async_reload(group.entry_id)
    await settle(hass)
    assert hass.states.get(LIGHT).state == STATE_OFF
    # Loading the group gives its lights the settings once more.
    assert written(second)[-2:] == [
        "08010f0a" + "1200173b" + "00" * 8 + "0340",
        "01010100",
    ]


async def test_lights_that_reconnect_get_the_settings(hass, group, controller, second):
    await call(hass, "light", "turn_on", LIGHT, effect="phasing")
    # Changed on the lights themselves, for instance with the phone app.
    controller.mode = 0x40
    controller.written.clear()
    second.written.clear()

    controller.drop_connection()
    await settle(hass)
    assert written(controller)[-2:] == [
        "08010f63" + "1200173b" + "00" * 8 + "0302",
        "01010101",
    ]
    assert hass.states.get(MEMBER_1).attributes["effect"] == "phasing"
    assert second.written == []


async def test_one_of_the_lights_out_of_reach(hass, group, controller, second):
    second.connect_error = BleakError("out of range")
    second.drop_connection()
    await settle(hass)
    assert hass.states.get(MEMBER_2).state == STATE_UNAVAILABLE
    assert hass.states.get(LIGHT).state == STATE_ON

    await call(hass, "light", "turn_off", LIGHT)
    assert written(controller)[-1] == "01010100"
    assert hass.states.get(LIGHT).state == STATE_OFF

    # Back in reach: it gets what it missed.
    second.connect_error = None
    await hass.config_entries.async_reload(
        hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, ADDRESS_2).entry_id
    )
    await settle(hass)
    assert written(second)[-1] == "01010100"
    assert hass.states.get(MEMBER_2).state == STATE_OFF


async def test_all_lights_out_of_reach(hass, group, controller, second):
    for fake in (controller, second):
        fake.failing_writes = 100
    with pytest.raises(HomeAssistantError) as error:
        await call(hass, "light", "turn_off", LIGHT)
    assert error.value.translation_key == "communication_error"
    await settle(hass)
    # Not changed, and no lights left to control.
    assert group.data.get(CONF_SETTINGS) is None
    assert hass.states.get(LIGHT).state == STATE_UNAVAILABLE
    assert hass.states.get(SWITCH).state == STATE_UNAVAILABLE


async def test_group_without_lights_set_up(hass, controller):
    group = add_group(hass)
    await hass.config_entries.async_setup(group.entry_id)
    await settle(hass)
    assert hass.states.get(LIGHT).state == STATE_UNAVAILABLE
    assert await async_get_config_entry_diagnostics(hass, group) == {
        "group": {"members": 2, "members_set_up": 0, "settings": None}
    }


async def test_restore_defaults(hass, group, controller, second):
    await call(hass, "light", "turn_on", LIGHT, brightness=1, effect="stay_on")
    await call(hass, "time", "set_value", START_1, time="16:30:00")
    await call(hass, "button", "press", BUTTON)
    await settle(hass)
    for fake in (controller, second):
        assert "07010702631200173b01" in written(fake)
    state = hass.states.get(LIGHT)
    assert state.attributes["brightness"] == 255
    assert state.attributes["effect"] == "all_modes"
    assert hass.states.get(START_1).state == "18:00:00"
    # The lights were asked what they are set to now.
    member = hass.states.get(MEMBER_1)
    assert member.attributes["brightness"] == 255
    assert member.attributes["effect"] == "all_modes"


async def test_diagnostics(hass, group, controller, second):
    diagnostics = await async_get_config_entry_diagnostics(hass, group)
    assert diagnostics["group"]["members"] == 2
    assert diagnostics["group"]["members_set_up"] == 2
    assert ADDRESS not in str(diagnostics)


async def test_flow_offers_a_group_once_there_are_lights(hass, controller):
    add_lights(hass, ADDRESS)
    add_lights(hass, ADDRESS_2)
    with patch(
        "custom_components.ble_christmas_lights.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.MENU
        assert result["menu_options"] == ["device", "group"]

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "group"}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "group"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NAME: "Tree", CONF_MEMBERS: []}
        )
        assert result["errors"] == {CONF_MEMBERS: "no_members"}

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NAME: "Tree", CONF_MEMBERS: [ADDRESS, ADDRESS_2]}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Tree"
    assert result["data"] == {CONF_MEMBERS: [ADDRESS, ADDRESS_2]}


async def test_flow_group_of_at_most_four(hass, controller):
    addresses = [f"11:22:33:44:55:0{number}" for number in range(5)]
    for address in addresses:
        add_lights(hass, address)
    # A group is not something to put in a group.
    add_group(hass)
    with patch(
        "custom_components.ble_christmas_lights.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "group"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NAME: "Tree", CONF_MEMBERS: addresses}
        )
        assert result["errors"] == {CONF_MEMBERS: "too_many_members"}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NAME: "Tree", CONF_MEMBERS: addresses[:4]}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_flow_can_still_add_lights(hass, controller):
    add_lights(hass, ADDRESS_2)
    with patch(
        "custom_components.ble_christmas_lights.config_flow.async_discovered_service_info",
        return_value=[],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "device"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_only_lights_have_options(hass, group):
    lights = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, ADDRESS)
    assert lights.supports_options is True
    assert group.supports_options is False


async def test_change_the_lights_of_a_group(
    hass, group, controller, second, controllers
):
    third_address = "11:22:33:44:55:77"
    third = controllers.setdefault(third_address, FakeController())
    await hass.config_entries.async_setup(add_lights(hass, third_address).entry_id)
    await call(hass, "light", "turn_on", LIGHT, effect="wave")
    await settle(hass)

    result = await group.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Garden", CONF_MEMBERS: []}
    )
    assert result["errors"] == {CONF_MEMBERS: "no_members"}

    second.written.clear()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Garden", CONF_MEMBERS: [ADDRESS, third_address]},
    )
    await settle(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert group.title == "Garden"
    assert group.data[CONF_MEMBERS] == [ADDRESS, third_address]
    # The group kept its settings, and the lights that joined got them.
    assert group.data[CONF_SETTINGS]["mode"] == 0x01
    assert written(third)[-2:] == [
        "08010f63" + "1200173b" + "00" * 8 + "0301",
        "01010101",
    ]
    # The lights that left are left alone from here on.
    assert second.written == []
    await call(hass, "light", "turn_off", LIGHT)
    assert written(third)[-1] == "01010100"
    assert second.written == []


async def test_lights_cannot_be_reconfigured(hass, group):
    lights = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, ADDRESS)
    result = await lights.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_lights"


async def test_send_settings_to_the_lights(hass, group, controller, second):
    await call(hass, "light", "turn_on", LIGHT, effect="phasing")
    # Changed on the lights themselves, without the connection being lost.
    await call(hass, "light", "turn_on", MEMBER_1, effect="stay_on")
    for fake in (controller, second):
        fake.written.clear()

    await call(hass, "button", "press", SYNC_BUTTON)
    for fake in (controller, second):
        assert written(fake) == [
            "08010f63" + "1200173b" + "00" * 8 + "0302",
            "01010101",
        ]
    assert hass.states.get(MEMBER_1).attributes["effect"] == "phasing"

    for fake in (controller, second):
        fake.failing_writes = 100
    with pytest.raises(HomeAssistantError):
        await call(hass, "button", "press", SYNC_BUTTON)


async def test_lights_have_no_sync_button(hass, group):
    assert hass.states.get("button.christmas_lights_eeff_restore_default_settings")
    assert (
        hass.states.get("button.christmas_lights_eeff_send_settings_to_the_lights")
        is None
    )
