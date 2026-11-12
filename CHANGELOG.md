# Changelog

All notable changes are listed here. Versions follow
[Semantic Versioning](https://semver.org/): while the version starts
with `0.`, any release may still contain breaking changes.

## [0.4.1] - 2026-11-12

- German and French translations.

## [0.4.0] - 2026-11-12

Compared with the Lights App itself (version 2.2), which showed what the
bytes of the controller mean.

### Added

- **Timer** switch: whether the timers of the controller decide when the
  lights are lit.
- Start and end time of the three timers. The second and third timer are
  disabled by default.
- **Restore default settings** button.
- Groups of up to four sets of lights, as in the app. A group has its own
  light, Timer switch, timers and Restore default settings button; changes go
  to all its lights, and lights that connect are given the settings of the
  group. The name and the lights of a group can be changed afterwards, and
  a button sends the settings of the group to its lights again.
- The device page shows which kind of lights it is, such as `LED-4-02`.

### Changed

- Controllers are recognised by the start of their name
  (`LED-<digit>-<two digits>`), like the app does, instead of only when the
  name ends in `-00000000`.
- The integration is listed as polling the lights, which is what it does,
  instead of as being pushed their state.
- Notifications from the controller are recognised by their length alone,
  like the app does.
- The effect "All modes" is sent as the "Auto Rotate" of the app, instead of
  as a selection of all seven modes.

### Fixed

- Reading the state set the clock of the controller to 17:38:17 every time,
  so timers set in the app ran at the wrong moments. The clock is now set to
  the local time of Home Assistant.
- Lights that were on with the timers enabled showed as off.
- Switching the lights on or off from Home Assistant disabled the timers.
- After choosing "Auto Rotate" in the app, the light could show the effect
  that was selected before, instead of "All modes".

## [0.3.0] - 2026-11-11

### Added

- Option **Stay connected** (on by default). Turn it off to leave the lights
  free for the phone app or to free up a connection on a Bluetooth proxy:
  Home Assistant then only connects to send a command and to read the state
  every 5 minutes.
- Action `ble_christmas_lights.set_modes` to let the lights cycle through a
  mix of modes, and a `modes` attribute that shows the active modes, also for
  a mix set in the phone app.
- Diagnostics download with the advertised name and the raw data the
  controller sent, to help add support for other controllers. It does not
  contain the Bluetooth address.
- Icon for the light (a light string).

### Changed

- When the Bluetooth connection drops, Home Assistant reconnects right away.
  The lights keep their last state in the meantime and only become
  unavailable when reconnecting fails or takes longer than 15 seconds,
  instead of after every drop.
- Lights that were out of reach are reconnected as soon as they are seen
  again, without waiting for the next attempt.
- A command that fails on a connection that went stale is tried once more on
  a new connection, instead of failing the first time.
- Brightness now runs from 1 to 255 instead of 0 to 255, so the lowest level
  no longer shows as 0 while the lights are on. The same brightness value can
  select a level that is one step lower than before.
- Bluetooth discovery only starts for names that match
  `LED-<digit>-<two digits>-00000000`, not for every name starting with `LED-`.

### Fixed

- Reloading the integration while it was reconnecting could leave a
  connection open that nobody used. The lights then refused every new
  connection until Home Assistant was restarted.
- A state query and a command could run at the same time, after which the
  answer to the query could overwrite the result of the command.
- After reconnecting, the light briefly showed as on without a brightness.
- After a command that failed, the light kept showing its old state until the
  next attempt to read it.
- Choosing an effect that does not exist now gives a clear error.

## [0.2.1] - 2026-09-30

- New icon: a light string wound around a Christmas tree.

## [0.2.0] - 2026-09-30

- Support every controller whose Bluetooth name matches
  `LED-<digit>-<two digits>-00000000`, not only `LED-4-01` and `LED-4-02`.
- Fix brightness and mode never being read when timers are set in the
  Lights App.

## [0.1.0] - 2026-09-30

First release, a rewrite of the Lights App integration.

- One light entity with on/off, brightness and the light modes as effects.
- Bluetooth discovery and a manual device picker in the setup flow.
- Reconnects on its own when the lights come back in range.
- English and Dutch translations.
