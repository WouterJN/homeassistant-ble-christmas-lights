"""Test fixtures for the BLE Christmas Lights integration."""

from unittest.mock import AsyncMock, MagicMock

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
import pytest

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

from custom_components.ble_christmas_lights.protocol import (
    NOTIFY_CHAR_UUID,
    WRITE_CHAR_UUID,
    parse_notification,
)

pytest_plugins = "pytest_homeassistant_custom_component"

ADDRESS = "AA:BB:CC:DD:EE:FF"
NAME = "LED-4-02-00000000"

POWER_ON_REPORT = bytes.fromhex("0000020100")
POWER_OFF_REPORT = bytes.fromhex("0000020000")


NO_TIMERS = bytes(12)
# What "Restore Default Settings" gives: one timer from 18:00 to 23:59.
DEFAULT_TIMERS = bytes((18, 0, 23, 59)) + bytes(8)


def power_report(is_on: bool, timers_enabled: bool = False) -> bytes:
    """Build a 5-byte power reply as the controller sends it."""
    return bytes((0x00, 0x00, 0x02, int(is_on) | int(timers_enabled) << 1, 0x00))


def settings_report(
    brightness: int, mode: int, theme: int = 0x03, timers: bytes = NO_TIMERS
) -> bytes:
    """Build an 18-byte settings reply as the controller sends it."""
    assert len(timers) == 12
    return (
        bytes.fromhex("02000f") + bytes((brightness,)) + timers + bytes((theme, mode))
    )


@pytest.fixture(autouse=True)
def auto_enable(enable_custom_integrations, mock_bluetooth):
    """Load custom_components/ and keep the real Bluetooth stack out."""
    yield


def make_service_info(address: str = ADDRESS, name: str = NAME):
    """Return discovery data for a controller."""
    return BluetoothServiceInfoBleak(
        name=name,
        address=address,
        rssi=-60,
        manufacturer_data={},
        service_data={},
        service_uuids=[],
        source="local",
        device=BLEDevice(address, name, {}),
        advertisement=None,
        connectable=True,
        time=0,
        tx_power=None,
    )


class FakeController:
    """A BleakClient stand-in that answers queries like the real controller."""

    def __init__(self, is_on=True, brightness=99, mode=0x40, has_service=True):
        self.is_on = is_on
        self.timers_enabled = False
        self.brightness = brightness
        self.theme = 0x03
        self.mode = mode
        self.timers = NO_TIMERS
        # The time of day the controller was last given, as (hour, minute, second).
        self.clock: tuple[int, int, int] | None = None
        self.written: list[bytes] = []
        # How many times a connection was made, and an error to fail the
        # next attempts with.
        self.connects = 0
        self.connect_error: Exception | None = None
        # How many of the next writes fail, as on a connection gone stale.
        self.failing_writes = 0
        self.is_connected = True
        self.disconnected_callback = None
        self._notify = None
        write_char = MagicMock(uuid=WRITE_CHAR_UUID)
        notify_char = MagicMock(uuid=NOTIFY_CHAR_UUID)
        service = MagicMock()
        service.get_characteristic.side_effect = {
            WRITE_CHAR_UUID: write_char,
            NOTIFY_CHAR_UUID: notify_char,
        }.get
        self.services = MagicMock()
        self.services.get_service.return_value = service if has_service else None
        self.disconnect = AsyncMock(side_effect=self._disconnect)

    async def start_notify(self, char, callback):
        self._notify = callback

    async def write_gatt_char(self, char, data, response):
        assert response is True
        if self.failing_writes:
            self.failing_writes -= 1
            raise BleakError("write failed")
        data = bytes(data)
        self.written.append(data)
        if len(data) == 6 and data.startswith(bytes.fromhex("000003")):
            self.clock = (data[3], data[4], data[5])
            self.notify(power_report(self.is_on, self.timers_enabled))
        elif data == bytes.fromhex("020000"):
            self.notify(
                settings_report(self.brightness, self.mode, self.theme, self.timers)
            )
        elif len(data) == 4 and data.startswith(bytes.fromhex("010101")):
            self.is_on = bool(data[3] & 1)
            self.timers_enabled = bool(data[3] & 2)
        elif len(data) == 4 and data.startswith(bytes.fromhex("030101")):
            self.brightness = data[3]
        elif len(data) == 5 and data.startswith(bytes.fromhex("050102")):
            self.theme, self.mode = data[3], data[4]
        elif len(data) == 15 and data.startswith(bytes.fromhex("04010c")):
            self.timers = data[3:]
        elif len(data) == 18 and data.startswith(bytes.fromhex("08010f")):
            self.brightness, self.timers = data[3], data[4:16]
            self.theme, self.mode = data[16], data[17]
        elif data == bytes.fromhex("07010702631200173b01"):
            self.brightness, self.theme, self.mode = 99, 0x01, 0x80
            self.timers = DEFAULT_TIMERS
        else:
            raise AssertionError(f"The controller does not know {data.hex()}")

    def notify(self, data: bytes) -> None:
        assert parse_notification(data) is not None
        self._notify(None, bytearray(data))

    async def _disconnect(self):
        self.is_connected = False
        if self.disconnected_callback:
            self.disconnected_callback(self)

    def drop_connection(self):
        """Simulate the lights going out of range."""
        self.is_connected = False
        self.disconnected_callback(self)


@pytest.fixture
def controllers(monkeypatch):
    """Patch establish_connection to return a FakeController per address."""
    fakes: dict[str, FakeController] = {ADDRESS: FakeController()}

    async def establish_connection(
        client_class, device, name, disconnected_callback=None, **kwargs
    ):
        fake = fakes.setdefault(device.address, FakeController())
        if fake.connect_error:
            raise fake.connect_error
        fake.connects += 1
        fake.is_connected = True
        fake.disconnected_callback = disconnected_callback
        return fake

    monkeypatch.setattr(
        "custom_components.ble_christmas_lights.device.establish_connection",
        establish_connection,
    )
    return fakes


@pytest.fixture
def controller(controllers):
    """The controller of the lights most tests use."""
    return controllers[ADDRESS]
