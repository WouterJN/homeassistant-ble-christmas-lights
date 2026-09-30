"""Test fixtures for the BLE Christmas Lights integration."""

from unittest.mock import AsyncMock, MagicMock

from bleak.backends.device import BLEDevice
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


def settings_report(brightness: int, mode: int) -> bytes:
    """Build an 18-byte settings reply as the controller sends it."""
    return (
        bytes.fromhex("02000f")
        + bytes((brightness,))
        + bytes(12)  # three unset timers
        + bytes.fromhex("03")
        + bytes((mode,))
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
        self.brightness = brightness
        self.mode = mode
        self.written: list[bytes] = []
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
        self.written.append(bytes(data))
        if data == bytes.fromhex("000003112611"):
            self.notify(POWER_ON_REPORT if self.is_on else POWER_OFF_REPORT)
        elif data == bytes.fromhex("020000"):
            self.notify(settings_report(self.brightness, self.mode))

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
def controller(monkeypatch):
    """Patch establish_connection to return a FakeController."""
    fake = FakeController()

    async def establish_connection(
        client_class, device, name, disconnected_callback=None, **kwargs
    ):
        fake.is_connected = True
        fake.disconnected_callback = disconnected_callback
        return fake

    monkeypatch.setattr(
        "custom_components.ble_christmas_lights.device.establish_connection",
        establish_connection,
    )
    return fake
