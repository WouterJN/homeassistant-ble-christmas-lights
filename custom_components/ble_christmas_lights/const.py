"""Constants for the BLE Christmas Lights integration."""

from datetime import timedelta
import re

from .protocol import ALL_MODES, Mode

DOMAIN = "ble_christmas_lights"

# Bluetooth names the controllers advertise with, e.g. "LED-4-02-00000000".
# The first three parts say which kind of lights it is; like the app, the
# rest of the name is not looked at.
SUPPORTED_NAME = re.compile(r"(LED-\d-\d\d)(-.*)?")

# Option: keep the Bluetooth connection open (the default), or close it when
# idle so the phone app or another device can use it.
CONF_STAY_CONNECTED = "stay_connected"
DEFAULT_STAY_CONNECTED = True

# How often the state is read while connected, and how often a controller
# that cannot be reached is tried again.
UPDATE_INTERVAL = timedelta(seconds=30)

# How long the lights keep showing their last state while reconnecting after
# the connection dropped. A slow attempt carries on after that, but the lights
# show as unavailable until it succeeds.
RECONNECT_GRACE = 15

# With the connection closed when idle: how often to connect to read the
# state, and how long the connection stays open after the last command.
IDLE_UPDATE_INTERVAL = timedelta(minutes=5)
IDLE_DISCONNECT_DELAY = 10

# A group has the addresses of its lights and its own settings; see group.py.
CONF_MEMBERS = "members"
CONF_SETTINGS = "settings"
# The app allows this many sets of lights in a group.
MAX_GROUP_MEMBERS = 4

SERVICE_SET_MODES = "set_modes"
ATTR_MODES = "modes"

# The light modes, keyed by their translation key.
MODES: dict[str, Mode] = {
    "stay_on": Mode.STAY_ON,
    "fast_twinkling": Mode.FAST_TWINKLING,
    "fade_away": Mode.FADE_AWAY,
    "twinkling_in_phase": Mode.TWINKLING_IN_PHASE,
    "fade_away_in_phase": Mode.FADE_AWAY_IN_PHASE,
    "phasing": Mode.PHASING,
    "wave": Mode.WAVE,
}

# Light effects: every single mode, plus cycling through all of them.
EFFECTS: dict[str, Mode] = {**MODES, "all_modes": ALL_MODES}
