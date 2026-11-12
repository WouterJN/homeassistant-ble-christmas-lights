"""Tests for the byte-level protocol; these pin the bytes the controller expects."""

from datetime import time

import pytest

from .conftest import DEFAULT_TIMERS, power_report, settings_report
from custom_components.ble_christmas_lights.protocol import (
    ALL_MODES,
    CMD_QUERY_SETTINGS,
    CMD_RESTORE_DEFAULTS,
    Mode,
    PowerReport,
    SettingsReport,
    Timer,
    brightness_command,
    brightness_from_ha,
    brightness_to_ha,
    mode_command,
    parse_notification,
    power_command,
    power_query,
    settings_command,
    timers_command,
)

UNSET = Timer()


def test_fixed_commands():
    assert CMD_QUERY_SETTINGS.hex() == "020000"
    assert CMD_RESTORE_DEFAULTS.hex() == "07010702631200173b01"


def test_power_query_carries_the_time():
    assert power_query(time(17, 38, 17)).hex() == "000003112611"
    assert power_query(time(0, 0, 0)).hex() == "000003000000"
    assert power_query(time(23, 59, 59, 999)).hex() == "000003173b3b"


@pytest.mark.parametrize(
    ("is_on", "timers_enabled", "expected"),
    [
        (False, False, "01010100"),
        (True, False, "01010101"),
        (False, True, "01010102"),
        (True, True, "01010103"),
    ],
)
def test_power_command(is_on, timers_enabled, expected):
    assert power_command(is_on, timers_enabled).hex() == expected


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
        (Mode.STAY_ON | Mode.WAVE, 0x41),
    ],
)
def test_mode_command(mode, byte):
    assert mode_command(mode) == bytes((0x05, 0x01, 0x02, 0x03, byte))


def test_mode_command_all_modes_is_auto_rotate():
    # What the app sends for "Auto Rotate", not a selection of all seven modes.
    assert mode_command(ALL_MODES).hex() == "0501020180"
    assert parse_notification(settings_report(99, 0x80, theme=0x01)).mode == ALL_MODES


def test_mode_command_needs_a_mode():
    with pytest.raises(ValueError):
        mode_command(Mode(0))


def test_timers_command():
    timers = (Timer(time(16, 0), time(23, 0)), Timer(time(6, 15), time(7, 59)), UNSET)
    assert (
        timers_command(timers).hex() == "04010c" + "10001700" + "060f073b" + "00000000"
    )


def test_settings_command():
    timers = (Timer(time(16, 0), time(23, 0)), Timer(time(6, 15), time(7, 59)), UNSET)
    assert (
        settings_command(55, Mode.STAY_ON, timers).hex()
        == "08010f" + "37" + "10001700" + "060f073b" + "00000000" + "0340"
    )
    # All modes is "Auto Rotate", as in mode_command().
    assert settings_command(99, ALL_MODES, timers).hex().endswith("0180")


def test_settings_command_is_what_the_settings_report_holds():
    timers = (Timer(time(16, 0), time(23, 0)), UNSET, UNSET)
    command = settings_command(55, Mode.WAVE | Mode.PHASING, timers)
    report = parse_notification(bytes.fromhex("02000f") + command[3:])
    assert report == SettingsReport(55, Mode.WAVE | Mode.PHASING, timers)


@pytest.mark.parametrize("brightness", [9, 100])
def test_settings_command_brightness_out_of_range(brightness):
    with pytest.raises(ValueError):
        settings_command(brightness, Mode.WAVE, (UNSET, UNSET, UNSET))


def test_settings_command_needs_a_mode_and_three_timers():
    with pytest.raises(ValueError):
        settings_command(99, Mode(0), (UNSET, UNSET, UNSET))
    with pytest.raises(ValueError):
        settings_command(99, Mode.WAVE, (UNSET,))


def test_timers_command_needs_three_timers():
    with pytest.raises(ValueError):
        timers_command((UNSET, UNSET))


@pytest.mark.parametrize(
    ("data", "is_on", "timers_enabled"),
    [
        ("0000020000", False, False),
        ("0000020100", True, False),
        ("0000020200", False, True),
        ("0000020300", True, True),
        # The app only looks at the length and the fourth byte.
        ("ffffff01ff", True, False),
    ],
)
def test_parse_power_report(data, is_on, timers_enabled):
    assert parse_notification(bytes.fromhex(data)) == PowerReport(
        is_on=is_on, timers_enabled=timers_enabled
    )


@pytest.mark.parametrize("is_on", [False, True])
@pytest.mark.parametrize("timers_enabled", [False, True])
def test_power_report_is_what_power_command_sets(is_on, timers_enabled):
    report = parse_notification(power_report(is_on, timers_enabled))
    assert report == PowerReport(is_on=is_on, timers_enabled=timers_enabled)
    assert (
        power_command(is_on, timers_enabled)[3]
        == power_report(is_on, timers_enabled)[3]
    )


def test_parse_settings_report():
    assert parse_notification(settings_report(55, 0x20)) == SettingsReport(
        brightness=55, mode=Mode.FAST_TWINKLING, timers=(UNSET, UNSET, UNSET)
    )


def test_parse_settings_report_without_modes_means_all_modes():
    assert parse_notification(settings_report(99, 0x00)).mode == ALL_MODES


def test_parse_settings_report_ignores_high_bit():
    assert parse_notification(settings_report(99, 0xC0)).mode == Mode.STAY_ON


@pytest.mark.parametrize("mode", [0x80, 0x40, 0x41, 0x00])
def test_parse_settings_report_auto_rotate_means_all_modes(mode):
    # With "Auto Rotate" the mode byte is a leftover from an earlier selection.
    assert parse_notification(settings_report(99, mode, theme=0x01)).mode == ALL_MODES


@pytest.mark.parametrize("theme", [0x02, 0x03])
def test_parse_settings_report_selection(theme):
    report = parse_notification(settings_report(99, 0x41, theme=theme))
    assert report.mode == Mode.STAY_ON | Mode.WAVE


def test_parse_settings_report_with_timers():
    # Captured from a controller with two timers set (16:00-23:00, 06:15-07:59).
    data = bytes.fromhex("02000f6310001700060f073b000000000340")
    assert parse_notification(data) == SettingsReport(
        brightness=99,
        mode=Mode.STAY_ON,
        timers=(
            Timer(time(16, 0), time(23, 0)),
            Timer(time(6, 15), time(7, 59)),
            UNSET,
        ),
    )
    assert [timer.is_set for timer in parse_notification(data).timers] == [
        True,
        True,
        False,
    ]


def test_parse_settings_report_after_restoring_defaults():
    report = parse_notification(settings_report(99, 0x80, 0x01, DEFAULT_TIMERS))
    assert report == SettingsReport(
        brightness=99,
        mode=ALL_MODES,
        timers=(Timer(time(18, 0), time(23, 59)), UNSET, UNSET),
    )


def test_parse_settings_report_with_impossible_times():
    report = parse_notification(settings_report(99, 0x40, timers=b"\xff" * 12))
    assert report.timers == (Timer(time(23, 59), time(23, 59)),) * 3


def test_timers_round_trip():
    data = bytes.fromhex("02000f6310001700060f073b000000000340")
    assert timers_command(parse_notification(data).timers)[3:] == data[4:16]


@pytest.mark.parametrize("data", ["", "0102", "000002010000", "ff" * 17, "00" * 19])
def test_parse_unknown(data):
    assert parse_notification(bytes.fromhex(data)) is None


@pytest.mark.parametrize(
    ("ha", "device"), [(0, 10), (1, 10), (3, 11), (128, 54), (254, 99), (255, 99)]
)
def test_brightness_from_ha(ha, device):
    assert brightness_from_ha(ha) == device


@pytest.mark.parametrize(("device", "ha"), [(10, 1), (99, 255), (0, 1), (120, 255)])
def test_brightness_to_ha(device, ha):
    assert brightness_to_ha(device) == ha


def test_brightness_round_trip():
    for level in range(10, 100):
        assert brightness_from_ha(brightness_to_ha(level)) == level


def test_brightness_is_never_zero_while_on():
    # Home Assistant brightness 0 means "off", so every level must map above it.
    assert min(brightness_to_ha(level) for level in range(10, 100)) == 1
