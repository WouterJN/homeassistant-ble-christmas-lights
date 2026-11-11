"""Tests for setting up the integration and the light entity."""

import asyncio
from datetime import timedelta
from unittest.mock import patch

from bleak.exc import BleakError
import probatio
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant.components.bluetooth import BluetoothChange
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_EFFECT_LIST,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_ADDRESS,
    EVENT_HOMEASSISTANT_STOP,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util

from .conftest import ADDRESS, POWER_OFF_REPORT, make_service_info, settings_report
from custom_components.ble_christmas_lights.const import (
    CONF_STAY_CONNECTED,
    DOMAIN,
    IDLE_UPDATE_INTERVAL,
    RECONNECT_GRACE,
    UPDATE_INTERVAL,
)

ENTITY_ID = "light.christmas_lights_eeff"
BLUETOOTH = "custom_components.ble_christmas_lights.bluetooth"


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
        f"{BLUETOOTH}.async_ble_device_from_address",
        return_value=make_service_info().device,
    ):
        yield


@pytest.fixture
def advertise():
    """Return a function that makes the lights show up in a Bluetooth scan."""
    callbacks = []

    def register(hass, callback, matcher, mode):
        callbacks.append(callback)
        return lambda: callbacks.remove(callback)

    def advertise():
        for callback in callbacks:
            callback(make_service_info(), BluetoothChange.ADVERTISEMENT)

    with patch(f"{BLUETOOTH}.async_register_callback", side_effect=register):
        yield advertise


@pytest.fixture
def state_changes(hass):
    """Collect (state, brightness) for every state the light gets."""
    changes = []

    def listen():
        def changed(event):
            if event.data["entity_id"] == ENTITY_ID:
                changes.append(
                    (
                        event.data["new_state"].state,
                        event.data["new_state"].attributes.get(ATTR_BRIGHTNESS),
                    )
                )

        hass.bus.async_listen("state_changed", changed)
        return changes

    return listen


async def setup(hass, entry):
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def settle(hass):
    """Wait for everything, also for a reconnect running in the background."""
    await hass.async_block_till_done(wait_background_tasks=True)


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
    assert state.attributes["modes"] == ["fast_twinkling"]
    assert "all_modes" in state.attributes[ATTR_EFFECT_LIST]
    assert entry.runtime_data.update_interval == UPDATE_INTERVAL

    await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    controller.disconnect.assert_awaited()


async def test_setup_retries_when_not_found(hass, entry):
    with patch(f"{BLUETOOTH}.async_ble_device_from_address", return_value=None):
        await setup(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_retries_when_unreachable(hass, entry, ble_device, controller):
    controller.failing_writes = 10
    await setup(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    controller.disconnect.assert_awaited()


async def test_lowest_brightness_is_not_zero(hass, entry, ble_device, controller):
    controller.brightness = 10
    await setup(hass, entry)
    state = hass.states.get(ENTITY_ID)
    assert state.state == STATE_ON
    assert state.attributes[ATTR_BRIGHTNESS] == 1


async def test_turn_on_with_brightness_and_effect(hass, entry, ble_device, controller):
    await setup(hass, entry)
    controller.written.clear()

    await call(hass, "turn_on", brightness=128, effect="wave")
    assert [c.hex() for c in controller.written] == [
        "03010136",
        "0501020301",
        "01010101",
    ]
    state = hass.states.get(ENTITY_ID)
    assert state.attributes[ATTR_EFFECT] == "wave"
    # The controller has 90 levels, so 128 comes back as the nearest step.
    assert state.attributes[ATTR_BRIGHTNESS] == 127


async def test_turn_on_with_unknown_effect(hass, entry, ble_device, controller):
    await setup(hass, entry)
    controller.written.clear()
    with pytest.raises(ServiceValidationError) as error:
        await call(hass, "turn_on", effect="disco")
    assert error.value.translation_key == "unknown_effect"
    assert controller.written == []


async def test_turn_off(hass, entry, ble_device, controller):
    await setup(hass, entry)
    await call(hass, "turn_off")
    assert controller.written[-1].hex() == "01010100"
    assert hass.states.get(ENTITY_ID).state == STATE_OFF


async def test_pushed_state(hass, entry, ble_device, controller):
    await setup(hass, entry)
    controller.notify(settings_report(10, 0x41))
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY_ID)
    # A mix of modes set from the phone app is not one of the effects.
    assert state.attributes.get(ATTR_EFFECT) is None
    assert state.attributes["modes"] == ["stay_on", "wave"]

    controller.notify(POWER_OFF_REPORT)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_OFF


async def test_all_modes_effect(hass, entry, ble_device, controller):
    controller.mode = 0x00
    await setup(hass, entry)
    state = hass.states.get(ENTITY_ID)
    assert state.attributes[ATTR_EFFECT] == "all_modes"
    assert len(state.attributes["modes"]) == 7
    await call(hass, "turn_on", effect="all_modes")
    assert controller.written[-2].hex() == "0501020180"


async def test_set_modes_service(hass, entry, ble_device, controller):
    await setup(hass, entry)
    controller.written.clear()
    await hass.services.async_call(
        DOMAIN,
        "set_modes",
        {ATTR_ENTITY_ID: ENTITY_ID, "modes": ["wave", "stay_on"]},
        blocking=True,
    )
    assert [c.hex() for c in controller.written] == ["0501020341"]
    state = hass.states.get(ENTITY_ID)
    assert state.attributes.get(ATTR_EFFECT) is None
    assert state.attributes["modes"] == ["stay_on", "wave"]

    # A single mode is the same as picking that effect.
    await hass.services.async_call(
        DOMAIN, "set_modes", {ATTR_ENTITY_ID: ENTITY_ID, "modes": "phasing"}, True
    )
    assert hass.states.get(ENTITY_ID).attributes[ATTR_EFFECT] == "phasing"


@pytest.mark.parametrize("modes", [[], ["disco"], ["all_modes"]])
async def test_set_modes_service_rejects_bad_modes(
    hass, entry, ble_device, controller, modes
):
    await setup(hass, entry)
    controller.written.clear()
    with pytest.raises(probatio.Invalid):
        await hass.services.async_call(
            DOMAIN, "set_modes", {ATTR_ENTITY_ID: ENTITY_ID, "modes": modes}, True
        )
    assert controller.written == []


async def test_reconnects_at_once_after_a_drop(
    hass, entry, ble_device, controller, state_changes
):
    await setup(hass, entry)
    changes = state_changes()
    controller.is_on = False
    controller.drop_connection()
    await settle(hass)

    assert controller.connects == 2
    # Never unavailable in between, and the new state in one piece.
    assert changes == [(STATE_OFF, None)]

    # Reconnected in time, so nothing happens when the grace period is over.
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=RECONNECT_GRACE + 1)
    )
    await settle(hass)
    assert changes == [(STATE_OFF, None)]


async def test_unavailable_while_reconnecting_takes_long(
    hass, entry, ble_device, controller, state_changes, monkeypatch
):
    await setup(hass, entry)
    changes = state_changes()
    connected = asyncio.Event()

    async def slow_establish(client_class, device, name, **kwargs):
        await connected.wait()
        controller.is_connected = True
        controller.disconnected_callback = kwargs["disconnected_callback"]
        return controller

    monkeypatch.setattr(
        "custom_components.ble_christmas_lights.device.establish_connection",
        slow_establish,
    )
    # The reconnect does not finish, so only let the event loop run for a bit
    # instead of waiting for everything to be done.
    controller.drop_connection()
    await asyncio.sleep(0.01)
    # Within the grace period the last state is still shown.
    assert changes == []

    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=RECONNECT_GRACE + 1)
    )
    await asyncio.sleep(0.01)
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE

    # The attempt was not given up, and the light comes back when it
    # succeeds, also though the state is the same as before the drop.
    connected.set()
    await settle(hass)
    assert changes == [(STATE_UNAVAILABLE, None), (STATE_ON, 255)]


async def test_grace_period_ends_when_unloaded(hass, entry, ble_device, controller):
    await setup(hass, entry)
    controller.connect_error = BleakError("out of range")
    entry.runtime_data.async_reconnect()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await settle(hass)


async def test_unavailable_when_reconnect_fails_and_back(
    hass, entry, ble_device, controller, state_changes, caplog
):
    await setup(hass, entry)
    changes = state_changes()
    controller.connect_error = BleakError("out of range")
    controller.drop_connection()
    await settle(hass)
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE
    assert "out of range" in caplog.text

    controller.connect_error = None
    controller.brightness = 10
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await settle(hass)
    # No half-filled state (on, but brightness unknown) while reconnecting.
    assert changes == [(STATE_UNAVAILABLE, None), (STATE_ON, 1)]


async def test_reconnects_when_lights_are_seen_again(
    hass, entry, ble_device, controller, advertise
):
    await setup(hass, entry)

    # Seen while everything is fine: nothing to do.
    advertise()
    await settle(hass)
    assert controller.connects == 1

    controller.connect_error = BleakError("out of range")
    controller.drop_connection()
    await settle(hass)
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE

    # Plugged back in: no need to wait for the next poll.
    controller.connect_error = None
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await settle(hass)
    advertise()
    await settle(hass)
    assert hass.states.get(ENTITY_ID).state == STATE_ON
    assert controller.connects == 2


async def test_command_retries_on_stale_connection(hass, entry, ble_device, controller):
    await setup(hass, entry)
    controller.failing_writes = 1
    await call(hass, "turn_off")
    assert controller.connects == 2
    assert hass.states.get(ENTITY_ID).state == STATE_OFF


async def test_command_error(hass, entry, ble_device, controller):
    await setup(hass, entry)
    controller.failing_writes = 100
    with pytest.raises(HomeAssistantError) as error:
        await call(hass, "turn_off")
    assert error.value.translation_key == "communication_error"

    # The lights cannot be reached, so the old state is no longer shown.
    await settle(hass)
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE


async def test_connection_closed_when_home_assistant_stops(
    hass, entry, ble_device, controller
):
    await setup(hass, entry)
    controller.disconnect.assert_not_awaited()
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    controller.disconnect.assert_awaited_once()


async def test_not_staying_connected(
    hass, ble_device, controller, advertise, monkeypatch
):
    monkeypatch.setattr(
        "custom_components.ble_christmas_lights.IDLE_DISCONNECT_DELAY", 0.01
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDRESS,
        title="Christmas lights EEFF",
        data={CONF_ADDRESS: ADDRESS},
        options={CONF_STAY_CONNECTED: False},
    )
    entry.add_to_hass(hass)
    await setup(hass, entry)
    assert entry.runtime_data.update_interval == IDLE_UPDATE_INTERVAL

    await asyncio.sleep(0.05)
    await settle(hass)
    controller.disconnect.assert_awaited_once()
    assert not entry.runtime_data.device.is_connected
    # Closing the idle connection keeps the light available...
    assert hass.states.get(ENTITY_ID).state == STATE_ON

    # ...and the lights advertising again is no reason to connect.
    advertise()
    await settle(hass)
    assert controller.connects == 1

    await call(hass, "turn_off")
    controller.is_on = False
    assert controller.connects == 2
    assert hass.states.get(ENTITY_ID).state == STATE_OFF

    # While the lights cannot be reached, try again at the short interval.
    await asyncio.sleep(0.05)
    controller.connect_error = BleakError("out of range")
    async_fire_time_changed(hass, dt_util.utcnow() + IDLE_UPDATE_INTERVAL)
    await settle(hass)
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE
    assert entry.runtime_data.update_interval == UPDATE_INTERVAL

    controller.connect_error = None
    async_fire_time_changed(hass, dt_util.utcnow() + UPDATE_INTERVAL)
    await settle(hass)
    assert hass.states.get(ENTITY_ID).state == STATE_OFF
    assert entry.runtime_data.update_interval == IDLE_UPDATE_INTERVAL

    await hass.config_entries.async_unload(entry.entry_id)
