"""Tests for the Bluetooth device wrapper."""

import asyncio
from datetime import datetime, time

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
import pytest

from .conftest import (
    ADDRESS,
    DEFAULT_TIMERS,
    NAME,
    POWER_OFF_REPORT,
    POWER_ON_REPORT,
    power_report,
)
from custom_components.ble_christmas_lights.device import (
    CharacteristicMissingError,
    ChristmasLights,
    DeviceState,
)
from custom_components.ble_christmas_lights.protocol import ALL_MODES, Mode, Timer

DEVICE = "custom_components.ble_christmas_lights.device"


# The time the lights are given: 20:31:05, which is 14 1f 05 in the query.
NOW = datetime(2026, 12, 24, 20, 31, 5)
QUERY_POWER = "000003141f05"

UNSET = Timer()
NO_TIMERS = (UNSET, UNSET, UNSET)


@pytest.fixture
def lights():
    return ChristmasLights(BLEDevice(ADDRESS, NAME, {}), now=lambda: NOW)


async def test_update_reads_full_state(lights, controller):
    controller.brightness = 42
    controller.mode = 0x02
    controller.timers = DEFAULT_TIMERS
    assert await lights.update() == DeviceState(
        is_on=True,
        brightness=42,
        mode=Mode.PHASING,
        timers_enabled=False,
        timers=(Timer(time(18, 0), time(23, 59)), UNSET, UNSET),
    )
    assert [c.hex() for c in controller.written] == [QUERY_POWER, "020000"]


async def test_update_sets_the_clock_of_the_controller(controller):
    moment = datetime(2026, 12, 24, 23, 59, 58)
    lights = ChristmasLights(BLEDevice(ADDRESS, NAME, {}), now=lambda: moment)
    await lights.update()
    assert controller.clock == (23, 59, 58)

    # Every update gives the time again, so the clock does not drift.
    moment = datetime(2026, 12, 25, 0, 0, 28)
    await lights.update()
    assert controller.clock == (0, 0, 28)


async def test_update_reads_timers_enabled(lights, controller):
    controller.timers_enabled = True
    state = await lights.update()
    assert state.is_on is True
    assert state.timers_enabled is True


async def test_update_returns_state_without_callbacks(lights, controller):
    # The reports of one update must not show up as separate, partial changes.
    states = []
    lights.register_callback(states.append)
    assert (await lights.update()).is_on is True
    assert states == []


async def test_turn_on_sends_brightness_and_mode_before_power(lights, controller):
    await lights.turn_on(brightness=50, mode=Mode.WAVE)
    assert [c.hex() for c in controller.written] == [
        "03010132",
        "0501020301",
        "01010101",
    ]
    assert lights.state == DeviceState(True, 50, Mode.WAVE)


async def test_turn_on_is_one_state_change(lights, controller):
    await lights.update()
    await lights.turn_off()
    states = []
    lights.register_callback(states.append)
    await lights.turn_on(brightness=50, mode=Mode.WAVE)
    assert states == [DeviceState(True, 50, Mode.WAVE, False, NO_TIMERS)]


async def test_turn_off(lights, controller):
    await lights.turn_on()
    await lights.turn_off()
    assert controller.written[-1].hex() == "01010100"
    assert lights.state.is_on is False


async def test_set_brightness_and_mode(lights, controller):
    await lights.set_brightness(10)
    await lights.set_mode(Mode.STAY_ON | Mode.WAVE)
    assert [c.hex() for c in controller.written] == ["0301010a", "0501020341"]
    assert lights.state == DeviceState(None, 10, Mode.STAY_ON | Mode.WAVE)


async def test_callbacks_on_pushed_state(lights, controller):
    states = []
    unsubscribe = lights.register_callback(states.append)
    await lights.update()
    controller.notify(POWER_OFF_REPORT)
    assert states[-1].is_on is False
    unsubscribe()
    controller.notify(POWER_ON_REPORT)
    assert states[-1].is_on is False


async def test_disconnect_keeps_state_and_reconnects(lights, controller):
    drops = []
    unsubscribe = lights.register_disconnect_callback(lambda: drops.append(True))
    state = await lights.update()
    controller.drop_connection()
    assert drops == [True]
    assert not lights.is_connected
    # The last known state stays; whoever listens decides what to do with it.
    assert lights.state == state

    await lights.update()
    assert lights.is_connected
    assert controller.connects == 2

    unsubscribe()
    controller.drop_connection()
    assert drops == [True]


async def test_retries_on_stale_connection(lights, controller):
    await lights.update()
    controller.failing_writes = 1
    await lights.turn_off()
    assert controller.connects == 2
    assert controller.written[-1].hex() == "01010100"
    assert lights.state.is_on is False


async def test_write_error_disconnects(lights, controller):
    await lights.update()
    drops = []
    lights.register_disconnect_callback(lambda: drops.append(True))
    controller.failing_writes = 10
    with pytest.raises(BleakError):
        await lights.turn_on()
    # Tried on the existing connection and once more on a new one.
    assert controller.connects == 2
    assert controller.failing_writes == 8
    controller.disconnect.assert_awaited()
    assert not lights.is_connected
    # Closing the connection ourselves is not an unexpected drop.
    assert drops == []


async def test_no_second_try_on_a_new_connection(lights, controller):
    controller.failing_writes = 10
    with pytest.raises(BleakError):
        await lights.turn_on()
    assert controller.connects == 1
    assert controller.failing_writes == 9


async def test_out_of_range_brightness_keeps_connection(lights, controller):
    await lights.update()
    with pytest.raises(ValueError):
        await lights.set_brightness(5)
    assert lights.is_connected


async def test_missing_characteristics(lights, controller):
    controller.services.get_service.return_value = None
    with pytest.raises(CharacteristicMissingError):
        await lights.update()
    controller.disconnect.assert_awaited()


async def test_all_modes(lights, controller):
    controller.mode = 0x00
    assert (await lights.update()).mode == ALL_MODES


async def test_update_times_out_without_answer(lights, controller, monkeypatch):
    monkeypatch.setattr(f"{DEVICE}.UPDATE_TIMEOUT", 0.01)
    monkeypatch.setattr(controller, "notify", lambda data: None)
    with pytest.raises(TimeoutError):
        await lights.update()
    assert not lights.is_connected


async def test_update_fails_at_once_when_connection_drops(
    lights, controller, monkeypatch
):
    monkeypatch.setattr(controller, "notify", lambda data: None)
    update = asyncio.create_task(lights.update())
    while len(controller.written) < 2:
        await asyncio.sleep(0)
    controller.drop_connection()
    # Well within UPDATE_TIMEOUT, and not as a timeout.
    with pytest.raises(BleakError, match="connection lost"):
        await asyncio.wait_for(update, 1)


async def test_operations_do_not_interleave(lights, controller, monkeypatch):
    await lights.update()
    controller.written.clear()
    release = asyncio.Event()
    write = controller.write_gatt_char

    async def slow_write(char, data, response):
        await release.wait()
        await write(char, data, response)

    monkeypatch.setattr(controller, "write_gatt_char", slow_write)
    update = asyncio.create_task(lights.update())
    await asyncio.sleep(0)
    turn_off = asyncio.create_task(lights.turn_off())
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(update, turn_off)

    # The turn-off waits for the state query, so the answer to the query
    # cannot overwrite the result of the turn-off.
    assert [c.hex() for c in controller.written] == [
        QUERY_POWER,
        "020000",
        "01010100",
    ]
    assert lights.state.is_on is False


async def test_stop_while_connecting_closes_the_new_connection(
    lights, controller, monkeypatch
):
    release = asyncio.Event()

    async def slow_establish(client_class, device, name, **kwargs):
        await release.wait()
        controller.disconnected_callback = kwargs["disconnected_callback"]
        return controller

    monkeypatch.setattr(f"{DEVICE}.establish_connection", slow_establish)
    update = asyncio.create_task(lights.update())
    await asyncio.sleep(0)
    await lights.stop()
    release.set()

    with pytest.raises(BleakError):
        await update
    # Without this the controller would stay connected to nobody, and refuse
    # every new connection until Home Assistant restarts.
    controller.disconnect.assert_awaited_once()
    assert not lights.is_connected


async def test_stop_is_final(lights, controller):
    await lights.update()
    await lights.stop()
    controller.disconnect.assert_awaited_once()
    with pytest.raises(BleakError):
        await lights.update()
    assert controller.connects == 1


async def test_stop_survives_disconnect_error(lights, controller):
    await lights.update()
    controller.disconnect.side_effect = BleakError("already gone")
    await lights.stop()
    assert not lights.is_connected


async def test_idle_disconnect(controller):
    lights = ChristmasLights(BLEDevice(ADDRESS, NAME, {}), idle_disconnect_delay=0.01)
    drops = []
    lights.register_disconnect_callback(lambda: drops.append(True))
    state = await lights.update()
    assert lights.is_connected

    await asyncio.sleep(0.05)
    assert not lights.is_connected
    controller.disconnect.assert_awaited_once()
    # Closed on purpose: not a drop, and the state is still good.
    assert drops == []
    assert lights.state == state

    await lights.turn_off()
    assert controller.connects == 2
    assert lights.state.is_on is False
    await lights.stop()


async def test_idle_disconnect_waits_for_the_last_command(controller):
    lights = ChristmasLights(BLEDevice(ADDRESS, NAME, {}), idle_disconnect_delay=0.05)
    await lights.update()
    await asyncio.sleep(0.03)
    await lights.turn_off()
    await asyncio.sleep(0.03)
    # 0.06 s after connecting, but only 0.03 s after the last command.
    assert lights.is_connected
    await asyncio.sleep(0.05)
    assert not lights.is_connected
    assert controller.connects == 1
    await lights.stop()


async def test_stop_cancels_idle_disconnect(controller):
    lights = ChristmasLights(BLEDevice(ADDRESS, NAME, {}), idle_disconnect_delay=0.01)
    await lights.update()
    await lights.stop()
    await asyncio.sleep(0.03)
    controller.disconnect.assert_awaited_once()


async def test_notifications_kept_for_diagnostics(lights, controller):
    await lights.update()
    controller._notify(None, bytearray.fromhex("0a0b0c"))
    assert lights.last_power_report == "0000020100"
    assert lights.last_settings_report.startswith("02000f63")
    assert list(lights.unrecognised_notifications) == ["0a0b0c"]
    # Something that is not understood does not change the state.
    assert lights.state.is_on is True


@pytest.mark.parametrize("is_on", [False, True])
async def test_switching_the_lights_keeps_the_timers_enabled(lights, controller, is_on):
    controller.is_on = not is_on
    controller.timers_enabled = True
    await lights.update()
    await (lights.turn_on() if is_on else lights.turn_off())
    assert controller.written[-1] == bytes((1, 1, 1, 2 | is_on))
    assert controller.timers_enabled is True
    assert lights.state.is_on is is_on
    assert lights.state.timers_enabled is True


@pytest.mark.parametrize("is_on", [False, True])
async def test_set_timers_enabled_keeps_the_lights_as_they_are(
    lights, controller, is_on
):
    controller.is_on = is_on
    await lights.update()
    states = []
    lights.register_callback(states.append)

    await lights.set_timers_enabled(True)
    assert controller.written[-1] == bytes((1, 1, 1, 2 | is_on))
    assert lights.state.timers_enabled is True
    assert lights.state.is_on is is_on
    assert len(states) == 1

    await lights.set_timers_enabled(False)
    assert controller.written[-1] == bytes((1, 1, 1, int(is_on)))
    assert lights.state.timers_enabled is False
    assert lights.state.is_on is is_on


async def test_pushed_power_report_with_timers(lights, controller):
    await lights.update()
    controller.notify(power_report(True, True))
    assert lights.state.is_on is True
    assert lights.state.timers_enabled is True
    controller.notify(power_report(False, True))
    assert lights.state.is_on is False
    assert lights.state.timers_enabled is True


async def test_set_timers(lights, controller):
    await lights.update()
    timers = (Timer(time(16, 0), time(23, 0)), Timer(time(6, 15), time(7, 59)), UNSET)
    await lights.set_timers(timers)
    assert controller.written[-1].hex() == "04010c10001700060f073b00000000"
    assert lights.state.timers == timers
    # The controller agrees when asked.
    assert (await lights.update()).timers == timers


async def test_restore_defaults(lights, controller):
    controller.brightness = 20
    controller.mode = 0x41
    await lights.update()
    await lights.restore_defaults()
    assert controller.written[-1].hex() == "07010702631200173b01"
    # What the new settings are has to be read.
    assert lights.state.brightness == 20
    state = await lights.update()
    assert state.brightness == 99
    assert state.mode == ALL_MODES
    assert state.timers == (Timer(time(18, 0), time(23, 59)), UNSET, UNSET)


async def test_auto_rotate_is_all_modes(lights, controller):
    # "Auto Rotate" in the app leaves the modes of an earlier selection behind.
    controller.theme = 0x01
    controller.mode = 0x40
    assert (await lights.update()).mode == ALL_MODES


async def test_name(lights):
    assert lights.name == NAME
