"""Tests for the Bluetooth device wrapper."""

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
import pytest

from .conftest import ADDRESS, NAME, POWER_OFF_REPORT
from custom_components.ble_christmas_lights.device import (
    CharacteristicMissingError,
    ChristmasLights,
    DeviceState,
)
from custom_components.ble_christmas_lights.protocol import ALL_MODES, Mode


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


async def test_turn_on_sends_brightness_and_mode_before_power(lights, controller):
    await lights.turn_on(brightness=50, mode=Mode.WAVE)
    assert [c.hex() for c in controller.written] == [
        "03010132",
        "0501020301",
        "01010101",
    ]
    assert lights.state == DeviceState(True, 50, Mode.WAVE)


async def test_turn_off(lights, controller):
    await lights.turn_on()
    await lights.turn_off()
    assert controller.written[-1].hex() == "01010100"
    assert lights.state.is_on is False


async def test_callbacks_on_pushed_state(lights, controller):
    states = []
    unsubscribe = lights.register_callback(states.append)
    await lights.update()
    controller.notify(POWER_OFF_REPORT)
    assert states[-1].is_on is False
    unsubscribe()
    controller.notify(bytes.fromhex("0000020100"))
    assert states[-1].is_on is False


async def test_disconnect_clears_state_and_reconnects(lights, controller):
    states = []
    lights.register_callback(states.append)
    await lights.update()
    controller.drop_connection()
    assert lights.state == DeviceState()
    assert states[-1] == DeviceState()
    assert not lights.is_connected
    await lights.update()
    assert lights.is_connected
    assert lights.state.mode == Mode.STAY_ON


async def test_write_error_disconnects(lights, controller, monkeypatch):
    await lights.update()

    async def fail(*args, **kwargs):
        raise BleakError("gone")

    monkeypatch.setattr(controller, "write_gatt_char", fail)
    with pytest.raises(BleakError):
        await lights.turn_on()
    controller.disconnect.assert_awaited()
    assert not lights.is_connected


async def test_missing_characteristics(lights, controller):
    controller.services.get_service.return_value = None
    with pytest.raises(CharacteristicMissingError):
        await lights.update()
    controller.disconnect.assert_awaited()


async def test_all_modes(lights, controller):
    controller.mode = 0x00
    assert (await lights.update()).mode == ALL_MODES


async def test_update_times_out_without_answer(lights, controller, monkeypatch):
    monkeypatch.setattr(
        "custom_components.ble_christmas_lights.device.UPDATE_TIMEOUT", 0.01
    )
    monkeypatch.setattr(controller, "notify", lambda data: None)
    with pytest.raises(TimeoutError):
        await lights.update()
