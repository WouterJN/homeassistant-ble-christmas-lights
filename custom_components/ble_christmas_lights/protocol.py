"""Byte-level protocol of the "Lights App" Bluetooth controller.

This module is deliberately free of Home Assistant and Bleak imports so it
can be unit tested on its own.

The controller exposes one GATT service with a write and a notify
characteristic. Commands are written with response; the controller answers
state queries through notifications.

The commands and the meaning of the bytes follow the Lights App itself
(com.novolink.lightapp 2.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
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

# How the controller uses the modes: it either cycles through all of them
# ("Auto Rotate" in the app), or through the ones that are selected.
_THEME_AUTO_ROTATE = 0x01
_THEME_SELECTION = 0x03
# The mode byte the app has when no selection was ever made.
_MODE_AUTO_ROTATE = 0x80

TIMER_COUNT = 3

CMD_QUERY_SETTINGS = bytes.fromhex("020000")
# "Restore Default Settings" in the app: full brightness, cycling through all
# modes, and one timer from 18:00 to 23:59.
CMD_RESTORE_DEFAULTS = bytes.fromhex("07010702631200173b01")

_POWER_REPORT_LENGTH = 5
_SETTINGS_REPORT_LENGTH = 18


@dataclass(frozen=True, slots=True)
class Timer:
    """A period in which the controller keeps the lights on.

    A timer from 00:00 to 00:00 is not set.
    """

    start: time = time(0, 0)
    end: time = time(0, 0)

    @property
    def is_set(self) -> bool:
        """Whether this timer is in use."""
        return self != Timer()


type Timers = tuple[Timer, Timer, Timer]


@dataclass(frozen=True, slots=True)
class PowerReport:
    """Reply to power_query(), and to power_command().

    With the timers enabled, the lights are only lit within a timer period,
    also when is_on is true.
    """

    is_on: bool
    timers_enabled: bool


@dataclass(frozen=True, slots=True)
class SettingsReport:
    """Reply to CMD_QUERY_SETTINGS.

    Layout of the 18 bytes: 0-2 header, 3 brightness, 4-15 three timers of
    start hour/minute and stop hour/minute (all zero when unset), 16 mode
    theme, 17 mode.
    """

    brightness: int
    mode: Mode
    timers: Timers


def power_query(now: time) -> bytes:
    """Return the command that asks for the power state.

    It carries the current time, which the controller uses as its clock for
    the timers. So this has to be the local time, and sending it regularly
    keeps the clock right.
    """
    return bytes((0x00, 0x00, 0x03, now.hour, now.minute, now.second))


def power_command(is_on: bool, timers_enabled: bool = False) -> bytes:
    """Return the command that switches the lights and the timers on or off.

    Both are set at once, so pass the current state of the one to keep.
    """
    return bytes((0x01, 0x01, 0x01, int(is_on) | int(timers_enabled) << 1))


def brightness_command(level: int) -> bytes:
    """Return the command that sets the brightness to a device level."""
    if not BRIGHTNESS_MIN <= level <= BRIGHTNESS_MAX:
        raise ValueError(
            f"Brightness must be between {BRIGHTNESS_MIN} and {BRIGHTNESS_MAX}"
        )
    return bytes((0x03, 0x01, 0x01, level))


def mode_command(mode: Mode) -> bytes:
    """Return the command that selects one or more modes.

    All modes together is "Auto Rotate" in the app, which has its own theme.
    """
    mode &= ALL_MODES
    if not mode:
        raise ValueError("At least one mode must be selected")
    if mode == ALL_MODES:
        return bytes((0x05, 0x01, 0x02, _THEME_AUTO_ROTATE, _MODE_AUTO_ROTATE))
    return bytes((0x05, 0x01, 0x02, _THEME_SELECTION, int(mode)))


def timers_command(timers: Timers) -> bytes:
    """Return the command that sets all three timers."""
    if len(timers) != TIMER_COUNT:
        raise ValueError(f"There must be {TIMER_COUNT} timers")
    data = bytearray((0x04, 0x01, 0x0C))
    for timer in timers:
        data += bytes(
            (timer.start.hour, timer.start.minute, timer.end.hour, timer.end.minute)
        )
    return bytes(data)


def parse_notification(data: bytes) -> PowerReport | SettingsReport | None:
    """Decode a notification, or return None when it is not recognised.

    Like the app, this goes by the length of the notification alone.
    """
    if len(data) == _POWER_REPORT_LENGTH:
        # 0: off, 1: on, 2: off with timers, anything else: on with timers.
        state = data[3]
        return PowerReport(is_on=state not in (0, 2), timers_enabled=state > 1)
    if len(data) == _SETTINGS_REPORT_LENGTH:
        if data[16] == _THEME_AUTO_ROTATE:
            # The mode byte is left over from an earlier selection.
            mode = ALL_MODES
        else:
            # Without any mode selected the controller cycles through them all.
            mode = Mode(data[17] & ALL_MODES) or ALL_MODES
        return SettingsReport(
            brightness=data[3],
            mode=mode,
            timers=tuple(
                Timer(
                    _time(data[offset], data[offset + 1]),
                    _time(data[offset + 2], data[offset + 3]),
                )
                for offset in range(4, 16, 4)
            ),
        )
    return None


def _time(hour: int, minute: int) -> time:
    """Return a time of day, also for bytes that are out of range."""
    return time(min(hour, 23), min(minute, 59))


# Home Assistant brightness runs from 1 to 255; 0 would mean "off".
_HA_BRIGHTNESS_MIN = 1
_HA_BRIGHTNESS_MAX = 255
_HA_STEPS = _HA_BRIGHTNESS_MAX - _HA_BRIGHTNESS_MIN
_DEVICE_STEPS = BRIGHTNESS_MAX - BRIGHTNESS_MIN


def brightness_to_ha(level: int) -> int:
    """Convert a device brightness level (10-99) to Home Assistant (1-255)."""
    level = max(BRIGHTNESS_MIN, min(BRIGHTNESS_MAX, level))
    return _HA_BRIGHTNESS_MIN + round(
        (level - BRIGHTNESS_MIN) / _DEVICE_STEPS * _HA_STEPS
    )


def brightness_from_ha(value: int) -> int:
    """Convert a Home Assistant brightness (1-255) to a device level (10-99)."""
    value = max(_HA_BRIGHTNESS_MIN, min(_HA_BRIGHTNESS_MAX, value))
    return BRIGHTNESS_MIN + round(
        (value - _HA_BRIGHTNESS_MIN) / _HA_STEPS * _DEVICE_STEPS
    )
