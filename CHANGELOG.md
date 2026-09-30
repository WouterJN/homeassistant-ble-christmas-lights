# Changelog

All notable changes are listed here. Versions follow
[Semantic Versioning](https://semver.org/lang/nl/): while the version starts
with `0.`, any release may still contain breaking changes.

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
