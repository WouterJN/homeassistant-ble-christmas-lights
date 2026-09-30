"""Tests for the byte-level protocol; these pin the bytes the controller expects."""

import pytest

from .conftest import settings_report
from custom_components.ble_christmas_lights.protocol import (
    ALL_MODES,
    CMD_QUERY_POWER,
    CMD_QUERY_SETTINGS,
    CMD_TURN_OFF,
    CMD_TURN_ON,
    Mode,
    PowerReport,
    SettingsReport,
    brightness_command,
    brightness_from_ha,
    brightness_to_ha,
    mode_command,
    parse_notification,
)


def test_fixed_commands():
    assert CMD_TURN_ON.hex() == "01010101"
    assert CMD_TURN_OFF.hex() == "01010100"
    assert CMD_QUERY_POWER.hex() == "000003112611"
    assert CMD_QUERY_SETTINGS.hex() == "020000"


@pytest.mark.parametrize(
    ("level", "expected"), [(10, "0301010a"), (50, "03010132"), (99, "03010163")]
)
def test_brightness_command(level, expected):
    assert brightness_command(level).hex() == expected


@pytest.mark.parametrize("level", [0, 9, 100, 255])
def test_brightness_command_out_of_range(level):
    with pytest.raises(ValueError):
        brightness_command(level)


@pytest.mark.parametrize(
    ("mode", "byte"),
    [
        (Mode.STAY_ON, 0x40),
        (Mode.FAST_TWINKLING, 0x20),
        (Mode.FADE_AWAY, 0x10),
        (Mode.TWINKLING_IN_PHASE, 0x08),
        (Mode.FADE_AWAY_IN_PHASE, 0x04),
        (Mode.PHASING, 0x02),
        (Mode.WAVE, 0x01),
        (ALL_MODES, 0x7F),
        (Mode.STAY_ON | Mode.WAVE, 0x41),
    ],
)
def test_mode_command(mode, byte):
    assert mode_command(mode) == bytes((0x05, 0x01, 0x02, 0x03, byte))


def test_mode_command_needs_a_mode():
    with pytest.raises(ValueError):
        mode_command(Mode(0))


@pytest.mark.parametrize(
    ("data", "is_on"), [("0000020100", True), ("0000020000", False)]
)
def test_parse_power_report(data, is_on):
    assert parse_notification(bytes.fromhex(data)) == PowerReport(is_on=is_on)


def test_parse_settings_report():
    assert parse_notification(settings_report(55, 0x20)) == SettingsReport(
        brightness=55, mode=Mode.FAST_TWINKLING
    )


def test_parse_settings_report_without_modes_means_all_modes():
    assert parse_notification(settings_report(99, 0x00)).mode == ALL_MODES


def test_parse_settings_report_ignores_high_bit():
    assert parse_notification(settings_report(99, 0xC0)).mode == Mode.STAY_ON


def test_parse_settings_report_with_timers():
    # Captured from a controller with two timers set (16:00-23:00, 06:15-07:59).
    data = bytes.fromhex("02000f6310001700060f073b000000000340")
    assert parse_notification(data) == SettingsReport(brightness=99, mode=Mode.STAY_ON)


@pytest.mark.parametrize("data", ["", "0102", "000002010000", "ff" * 18, "00" * 18])
def test_parse_unknown(data):
    assert parse_notification(bytes.fromhex(data)) is None


@pytest.mark.parametrize(("ha", "device"), [(0, 10), (1, 10), (128, 55), (255, 99)])
def test_brightness_from_ha(ha, device):
    assert brightness_from_ha(ha) == device


@pytest.mark.parametrize(("device", "ha"), [(10, 0), (99, 255), (0, 0), (120, 255)])
def test_brightness_to_ha(device, ha):
    assert brightness_to_ha(device) == ha


def test_brightness_round_trip():
    for level in range(10, 100):
        assert brightness_from_ha(brightness_to_ha(level)) == level
