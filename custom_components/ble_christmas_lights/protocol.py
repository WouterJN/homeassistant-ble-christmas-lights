"""Byte-level protocol of the "Lights App" Bluetooth controller.

This module is deliberately free of Home Assistant and Bleak imports so it
can be unit tested on its own.

The controller exposes one GATT service with a write and a notify
characteristic. Commands are written with response; the controller answers
state queries through notifications.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntFlag

SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
WRITE_CHAR_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR_UUID = "0000fff4-0000-1000-8000-00805f9b34fb"

# The controller accepts brightness levels from 10 up to and including 99.
BRIGHTNESS_MIN = 10
BRIGHTNESS_MAX = 99


class Mode(IntFlag):
    """Light modes; the controller cycles through every mode that is set."""

    WAVE = 0x01
    PHASING = 0x02
    FADE_AWAY_IN_PHASE = 0x04
    TWINKLING_IN_PHASE = 0x08
    FADE_AWAY = 0x10
    FAST_TWINKLING = 0x20
    STAY_ON = 0x40


ALL_MODES = Mode(0x7F)

CMD_TURN_ON = bytes.fromhex("01010101")
CMD_TURN_OFF = bytes.fromhex("01010100")
CMD_QUERY_POWER = bytes.fromhex("000003112611")
CMD_QUERY_SETTINGS = bytes.fromhex("020000")

_POWER_REPORT_LENGTH = 5
_POWER_REPORT_MARKER = b"\x00\x00\x02"
_SETTINGS_REPORT_LENGTH = 18
_SETTINGS_REPORT_MARKER = bytes(8)


@dataclass(frozen=True, slots=True)
class PowerReport:
    """Reply to CMD_QUERY_POWER."""

    is_on: bool


@dataclass(frozen=True, slots=True)
class SettingsReport:
    """Reply to CMD_QUERY_SETTINGS."""

    brightness: int
    mode: Mode


def brightness_command(level: int) -> bytes:
    """Return the command that sets the brightness to a device level."""
    if not BRIGHTNESS_MIN <= level <= BRIGHTNESS_MAX:
        raise ValueError(
            f"Brightness must be between {BRIGHTNESS_MIN} and {BRIGHTNESS_MAX}"
        )
    return bytes((0x03, 0x01, 0x01, level))


def mode_command(mode: Mode) -> bytes:
    """Return the command that selects one or more modes."""
    mode &= ALL_MODES
    if not mode:
        raise ValueError("At least one mode must be selected")
    return bytes((0x05, 0x01, 0x02, 0x03, int(mode)))


def parse_notification(data: bytes) -> PowerReport | SettingsReport | None:
    """Decode a notification, or return None when it is not recognised."""
    if len(data) == _POWER_REPORT_LENGTH and _POWER_REPORT_MARKER in data:
        return PowerReport(is_on=data[3] == 0x01)
    if len(data) == _SETTINGS_REPORT_LENGTH and _SETTINGS_REPORT_MARKER in data:
        # The controller reports "no modes" when it is cycling through all of them.
        mode = Mode(data[-1] & ALL_MODES) or ALL_MODES
        return SettingsReport(brightness=data[3], mode=mode)
    return None


def brightness_to_ha(level: int) -> int:
    """Convert a device brightness level (10-99) to Home Assistant (0-255)."""
    level = max(BRIGHTNESS_MIN, min(BRIGHTNESS_MAX, level))
    return round((level - BRIGHTNESS_MIN) / (BRIGHTNESS_MAX - BRIGHTNESS_MIN) * 255)


def brightness_from_ha(value: int) -> int:
    """Convert a Home Assistant brightness (0-255) to a device level (10-99)."""
    value = max(0, min(255, value))
    return BRIGHTNESS_MIN + round(value / 255 * (BRIGHTNESS_MAX - BRIGHTNESS_MIN))
