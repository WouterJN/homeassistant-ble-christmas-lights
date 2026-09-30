<img src="custom_components/ble_christmas_lights/brand/icon@2x.png" alt="" width="128" align="right">

# BLE Christmas Lights for Home Assistant

[![Validate](https://github.com/WouterJN/homeassistant-ble-christmas-lights/actions/workflows/validate.yml/badge.svg)](https://github.com/WouterJN/homeassistant-ble-christmas-lights/actions/workflows/validate.yml)
[![Tests](https://github.com/WouterJN/homeassistant-ble-christmas-lights/actions/workflows/tests.yml/badge.svg)](https://github.com/WouterJN/homeassistant-ble-christmas-lights/actions/workflows/tests.yml)

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
names like `LED-4-01-00000000` or `LED-4-02-00000000` (the pattern
`LED-<digit>-<two digits>-00000000`), such as the 5.5 m and 48 m versions.

Do your lights advertise with another name? Please
[open an issue](https://github.com/WouterJN/homeassistant-ble-christmas-lights/issues)
with the name you see in a Bluetooth scanner app (such as nRF Connect).

## What you get

One light entity per set of lights, with:

- **On/off**
- **Brightness**: the lights have 90 brightness steps
- **Effects**: the light modes from the app

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

If you pick a mix of modes in the phone app, the light shows no effect until
you pick one in Home Assistant.

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

## Troubleshooting

- **The light is unavailable**: the lights are out of range, switched off at
  the plug, or connected to your phone. Home Assistant tries to reconnect
  every 30 seconds.
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
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

`protocol.py` describes the Bluetooth protocol and has no Home Assistant
dependencies.

## Credits

The Bluetooth protocol was first worked out by
[Juraj Nyíri](https://github.com/JurajNyiri) and contributors in
[HomeAssistant-Lights-App](https://github.com/JurajNyiri/HomeAssistant-Lights-App).
This project is a new implementation, written from scratch.

## License

[MIT](LICENSE)
