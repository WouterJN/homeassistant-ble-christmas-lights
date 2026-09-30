"""Constants for the BLE Christmas Lights integration."""

from datetime import timedelta

from .protocol import ALL_MODES, Mode

DOMAIN = "ble_christmas_lights"

# Bluetooth names the controllers advertise with, e.g. "LED-4-02-00000000".
SUPPORTED_NAME_PREFIXES = ("LED-4-01-", "LED-4-02-")

# Also reconnects after the controller went out of range.
UPDATE_INTERVAL = timedelta(seconds=30)

# Light effects, keyed by their translation key.
EFFECTS: dict[str, Mode] = {
    "stay_on": Mode.STAY_ON,
    "fast_twinkling": Mode.FAST_TWINKLING,
    "fade_away": Mode.FADE_AWAY,
    "twinkling_in_phase": Mode.TWINKLING_IN_PHASE,
    "fade_away_in_phase": Mode.FADE_AWAY_IN_PHASE,
    "phasing": Mode.PHASING,
    "wave": Mode.WAVE,
    "all_modes": ALL_MODES,
}
