# BLE Christmas Lights for Home Assistant

<img src="custom_components/ble_christmas_lights/brand/icon@2x.png" alt="" width="128" align="right">

[![Validate](https://github.com/WouterJN/homeassistant-ble-christmas-lights/actions/workflows/validate.yml/badge.svg)](https://github.com/WouterJN/homeassistant-ble-christmas-lights/actions/workflows/validate.yml)
[![Tests](https://github.com/WouterJN/homeassistant-ble-christmas-lights/actions/workflows/tests.yml/badge.svg)](https://github.com/WouterJN/homeassistant-ble-christmas-lights/actions/workflows/tests.yml)
[![Latest Home Assistant](https://github.com/WouterJN/homeassistant-ble-christmas-lights/actions/workflows/latest.yml/badge.svg)](https://github.com/WouterJN/homeassistant-ble-christmas-lights/actions/workflows/latest.yml)

Control Bluetooth (BLE) Christmas lights from Home Assistant: the cluster
lights and light strings that you normally control with the
[Lights App](https://play.google.com/store/apps/details?id=com.novolink.lightapp)
on your phone. In the Netherlands and Belgium these are sold at Action,
among others, as *kerstverlichting / clusterverlichting / lichtsnoer met
Bluetooth en app*.

No cloud and no extra hub needed: Home Assistant talks to the lights directly
over Bluetooth.

## Supported lights

Lights that show up in the Lights App and advertise over Bluetooth as
names like `LED-4-01-00000000` or `LED-4-02-00000000` (names that start with
`LED-<digit>-<two digits>`), such as the 5.5 m and 48 m versions. The Lights
App knows the kinds `LED-4`, `LED-5` and `LED-6`, each in the versions `01`,
`02`, `03`, `04` and `08`.

Do your lights advertise with another name? Please
[open an issue](https://github.com/WouterJN/homeassistant-ble-christmas-lights/issues)
with the name you see in a Bluetooth scanner app (such as nRF Connect).

## What you get

Per set of lights:

- A **light**, with on/off, brightness (the lights have 90 brightness steps)
  and the light modes from the app as effects.
- A **Timer** switch and the start and end time of three timers; see
  [Timers](#timers).
- A **Restore default settings** button: full brightness, cycling through all
  modes, and one timer from 18:00 to 23:59.

| Effect | Dutch name in Home Assistant |
| --- | --- |
| Stay on | Continu aan |
| Fast twinkling | Snel twinkelen |
| Fade away | Uitfaden |
| Twinkling in phase | Twinkelen in fase |
| Fade away in phase | Uitfaden in fase |
| Phasing | Faseren |
| Wave | Golf |
| All modes (cycles through all of them) | Alle modi |

The `modes` attribute of the light lists the modes that are active.

### A mix of modes

The lights can also cycle through a selection of modes. Use the action
`ble_christmas_lights.set_modes` for that:

```yaml
action: ble_christmas_lights.set_modes
target:
  entity_id: light.christmas_lights_eeff
data:
  modes:
    - stay_on
    - fade_away
    - wave
```

The modes are `stay_on`, `fast_twinkling`, `fade_away`, `twinkling_in_phase`,
`fade_away_in_phase`, `phasing` and `wave`. With a mix of modes, whether set
here or in the phone app, the light shows no effect; the `modes` attribute
shows the mix.

## Timers

The controller of the lights can switch them on and off by itself, also when
Home Assistant is not connected. It has three timers, each with a start and
an end time.

- The **Timer** switch decides whether the timers are used. While it is on,
  the lights are only lit between the start and the end of a timer. The light
  in Home Assistant then still shows as on outside those times: it shows
  whether the lights are switched on, not whether they are lit right now.
- **Timer 1 start** and **Timer 1 end** set the first timer. The second and
  third timer are disabled entities; enable them on the device page if you
  need them. A timer from 00:00 to 00:00 is not in use.

Home Assistant sets the clock of the controller to its own local time every
time it reads the state, so the timers follow the time zone and the summer
time of Home Assistant.

## Groups

Several sets of lights can be put in a group, as in the Lights App. Choose
**Add integration → BLE Christmas Lights → Make a group of lights**, give the
group a name and pick up to four sets of lights that are set up already.

A group gets the same entities as a set of lights: a light, the Timer switch,
the timers and the Restore default settings button. It works like a group in
the app:

- A group has its own settings. A new group starts on, at full brightness,
  cycling through all modes, with one timer from 18:00 to 23:59.
- Every change you make on the group is sent to all its lights.
- Lights that connect are given the settings of the group, also when they
  were changed on their own in the meantime. So a change made on one set of
  lights lasts until those lights connect again; with **Stay connected**
  turned off that is at most 5 minutes.
- The group does not follow its lights: it shows its own settings, and it is
  available as long as one of its lights can be reached.

To change which lights are in a group, delete the group and make it again.

## Installation

### HACS (recommended)

1. In HACS, open the menu (⋮) → **Custom repositories**.
2. Add `https://github.com/WouterJN/homeassistant-ble-christmas-lights` with
   type **Integration**.
3. Search for **BLE Christmas Lights**, install it and restart Home Assistant.

### Manual

Copy `custom_components/ble_christmas_lights` to the `custom_components`
folder in your Home Assistant configuration folder and restart Home Assistant.

## Setup

1. Switch the lights on and **close the Lights App on your phone**. The lights
   accept only one Bluetooth connection at a time.
2. Home Assistant discovers the lights by itself and shows them under
   **Settings → Devices & services**. You can also add them yourself with
   **Add integration → BLE Christmas Lights**.

Home Assistant needs a Bluetooth adapter within range of the lights. Outdoor
lights are often too far from the Home Assistant server; an
[ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html)
close to the lights solves that.

### Using the phone app as well

Home Assistant normally keeps its connection to the lights open, so the phone
app cannot connect. To use both, open the lights under
**Settings → Devices & services → BLE Christmas Lights**, choose **Configure**
and turn off **Stay connected**. Home Assistant then only connects to send a
command and to read the state every 5 minutes, and closes the connection again
after 10 seconds. This also frees up a connection on a Bluetooth proxy.

The price: commands take a little longer, a change made with the phone app
can take up to 5 minutes to show, and the light can be unavailable in Home
Assistant while the phone app is connected.

## Troubleshooting

- **The light is unavailable**: the lights are out of range, switched off at
  the plug, or connected to your phone. Home Assistant reconnects as soon as
  it sees the lights again, and otherwise tries every 30 seconds. After a
  short drop the light keeps its state for up to 15 seconds while Home
  Assistant reconnects.
- **Reporting a problem or another controller**: open the lights under
  **Settings → Devices & services → BLE Christmas Lights**, choose
  **Download diagnostics** from the menu (⋮) and attach the file to your
  [issue](https://github.com/WouterJN/homeassistant-ble-christmas-lights/issues).
  It holds the advertised name and the raw data the controller sent, not the
  Bluetooth address.
- **Debug logging**: add this to `configuration.yaml`:

  ```yaml
  logger:
    logs:
      custom_components.ble_christmas_lights: debug
  ```

## Moving from the "Lights App" integration

This integration replaces the `lights_app` custom integration. The two are not
compatible: remove the old integration (and its HACS repository), install this
one and set up your lights again. The seven mode switches from the old
integration are now effects of the light, so update automations and scenes
that used them.

## Development

```bash
python3.14 -m venv .venv
source .venv/bin/activate
scripts/setup
pytest
ruff check . && ruff format --check .
```

`requirements-dev.txt` pins the test framework, and with it the Home Assistant
version the tests run against. `scripts/setup` installs the Bluetooth
libraries at the versions that Home Assistant version needs.

Once a week the tests also run against the newest Home Assistant
(`scripts/setup --latest`). When that fails, fix what broke and raise the pin
in `requirements-dev.txt`.

`protocol.py` describes the Bluetooth protocol and has no Home Assistant
dependencies.

## Credits

The Bluetooth protocol was first worked out by
[Juraj Nyíri](https://github.com/JurajNyiri) and contributors in
[HomeAssistant-Lights-App](https://github.com/JurajNyiri/HomeAssistant-Lights-App).
This project is a new implementation, written from scratch.

## License

[MIT](LICENSE)
