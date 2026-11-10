"""Tests for the Bluetooth device wrapper."""

import asyncio

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
import pytest

from .conftest import ADDRESS, NAME, POWER_OFF_REPORT, POWER_ON_REPORT
from custom_components.ble_christmas_lights.device import (
    CharacteristicMissingError,
    ChristmasLights,
    DeviceState,
)
from custom_components.ble_christmas_lights.protocol import ALL_MODES, Mode

DEVICE = "custom_components.ble_christmas_lights.device"


@pytest.fixture
def lights():
    return ChristmasLights(BLEDevice(ADDRESS, NAME, {}))


async def test_update_reads_full_state(lights, controller):
    controller.brightness = 42
    controller.mode = 0x02
    assert await lights.update() == DeviceState(True, 42, Mode.PHASING)
    assert controller.written == [
        bytes.fromhex("000003112611"),
        bytes.fromhex("020000"),
    ]


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
    assert states == [DeviceState(True, 50, Mode.WAVE)]


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
        "000003112611",
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
    controller._notify(None, bytearray.fromhex("ff00000201"))
    assert lights.last_power_report == "0000020100"
    assert lights.last_settings_report.startswith("02000f63")
    assert list(lights.unrecognised_notifications) == ["ff00000201"]
    # Something that is not understood does not change the state.
    assert lights.state.is_on is True
