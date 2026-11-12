# Bluetooth protocol of the Lights App controllers

This describes how the controllers of the "Lights App" Christmas lights talk
over Bluetooth Low Energy. It is what
[`protocol.py`](../custom_components/ble_christmas_lights/protocol.py)
implements.

## Where this comes from

- **The app.** The commands and the meaning of the bytes are taken from the
  Lights App for Android, `com.novolink.lightapp` version 2.2: what it sends
  and how it reads what comes back.
- **Captures.** The notifications in the examples were seen on real
  controllers.

The app shows what it does, not what the controller does with it. Where
something is a conclusion and not something the app spells out, this document
says so. The firmware of the controller itself was not looked at.

## Finding a controller

A controller advertises with a name such as `LED-4-02-00000000`.

| Part | Meaning |
| --- | --- |
| `LED` | Fixed. The app shows every device whose name starts with `LED-`. |
| `4` | Kind of lights. The app knows `4`, `5` and `6`. |
| `02` | Version of that kind. The app knows `01`, `02`, `03`, `04` and `08`. |
| `00000000` | Not used by the app. All controllers seen so far have eight zeros. |

The app uses the first three parts only to pick a picture. All kinds are
controlled in the same way.

A controller accepts one connection at a time, and it is assumed to stop
advertising while it is connected.

## Service and characteristics

Everything goes through one GATT service.

| | UUID | Use |
| --- | --- | --- |
| Service | `0000fff0-0000-1000-8000-00805f9b34fb` | |
| Write | `0000fff1-0000-1000-8000-00805f9b34fb` | Commands to the controller |
| Notify | `0000fff4-0000-1000-8000-00805f9b34fb` | Answers from the controller |

After connecting, enable notifications on `fff4` and then write commands to
`fff1`. The integration writes with response. There is no pairing, password
or checksum.

## Overview

All values are single bytes. Bytes are written here in hexadecimal.

| Command | Bytes | Answer |
| --- | --- | --- |
| [Ask for the power state and set the clock](#power-state-and-clock) | `00 00 03 hh mm ss` | Power report, 5 bytes |
| [Switch the lights and the timers](#switching-the-lights-and-the-timers) | `01 01 01 pp` | |
| [Ask for the settings](#settings) | `02 00 00` | Settings report, 18 bytes |
| [Set the brightness](#brightness) | `03 01 01 bb` | |
| [Set the timers](#timers) | `04 01 0C` + 12 bytes | |
| [Set the modes](#modes) | `05 01 02 tt mm` | |
| [Restore the default settings](#restoring-the-default-settings) | `07 01 07 02 63 12 00 17 3B 01` | |
| [Set everything at once](#setting-everything-at-once) | `08 01 0F` + 15 bytes | |

In every command that sets something, the third byte is the number of bytes
that follow it. The first byte says what the command is about; the same
number comes back as the first byte of the settings report (`02`).

The app does not wait for an answer to the commands that set something, and
does not read one. Whether the controller sends a notification after them is
not known. Ask for the state again to see the result.

## Power state and clock

### Asking

```
00 00 03 hh mm ss
```

`hh`, `mm` and `ss` are the current hour, minute and second, in local time.
The app fills in the time of the phone every time it asks.

That this sets the clock of the controller is a conclusion: it is the only
command with a time in it, and the controller needs a clock for its timers.
It means the time has to be the real local time, and that asking regularly
keeps the clock right. Sending a fixed time, as older implementations did
with `00 00 03 11 26 11` (17:38:17), makes the timers run at the wrong
moments.

Example, at 20:31:05:

```
00 00 03 14 1F 05
```

### Power report

The answer is a notification of 5 bytes. The app recognises it by its length
alone and looks at the fourth byte only.

```
00 00 02 pp 00
```

| `pp` | Lights | Timers |
| --- | --- | --- |
| `00` | off | not enabled |
| `01` | on | not enabled |
| `02` | off | enabled |
| `03` | on | enabled |

In other words: bit 0 is the lights, bit 1 is the timers. The app treats
every value other than `00`, `01` and `02` as `03`.

With the timers enabled, the lights are only lit within the period of a
timer. "On" then means that they are switched on, not that they are lit at
this moment.

The other four bytes were `00 00 02` and `00` in every capture. Their meaning
is not known.

### Switching the lights and the timers

```
01 01 01 pp
```

`pp` is the same value as in the power report. The lights and the timers are
always set together, so to change one of them, send the current state of the
other along:

| To do | Send |
| --- | --- |
| Lights on, timers stay off | `01 01 01 01` |
| Lights off, timers stay off | `01 01 01 00` |
| Lights on, timers stay enabled | `01 01 01 03` |
| Lights off, timers stay enabled | `01 01 01 02` |

Sending `01` or `00` without looking at the timers switches the timers off.

## Settings

### Asking

```
02 00 00
```

### Settings report

The answer is a notification of 18 bytes. The app recognises it by its length
alone.

| Byte | Meaning |
| --- | --- |
| 0–2 | Header, `02 00 0F` in every capture. `0F` is the number of bytes that follow. |
| 3 | [Brightness](#brightness) |
| 4–7 | [Timer](#timers) 1: start hour, start minute, end hour, end minute |
| 8–11 | Timer 2, in the same way |
| 12–15 | Timer 3, in the same way |
| 16 | [Mode theme](#modes) |
| 17 | [Modes](#modes) |

Example, from a controller with two timers (16:00–23:00 and 06:15–07:59), at
full brightness and on "Stay on":

```
02 00 0F  63  10 00 17 00  06 0F 07 3B  00 00 00 00  03  40
          │   └ timer 1 ┘  └ timer 2 ┘  └ timer 3 ┘  │   └ modes: stay on
          │                                          └ theme: selection
          └ brightness 99
```

## Brightness

```
03 01 01 bb
```

`bb` is the brightness, from `0A` (10, lowest) to `63` (99, highest). That is
the range of the slider in the app; what the controller does with other
values is not known.

Setting the brightness does not switch the lights on.

## Modes

The lights have seven modes. Each is one bit of the mode byte:

| Bit | Value | Mode |
| --- | --- | --- |
| 0 | `01` | Wave |
| 1 | `02` | Phasing |
| 2 | `04` | Fade away in phase |
| 3 | `08` | Twinkling in phase |
| 4 | `10` | Fade away |
| 5 | `20` | Fast twinkling |
| 6 | `40` | Stay on |
| 7 | `80` | Not a mode; see below |

With more than one bit set, the controller cycles through those modes.

The mode theme says how the mode byte is used:

| Theme | In the app | Meaning |
| --- | --- | --- |
| `01` | Auto Rotate | Cycle through all modes. The mode byte is not used. |
| `02` | Program | The modes in the mode byte. Sent when "Program" is chosen. |
| `03` | (a mode is switched on or off) | The modes in the mode byte. |

The app treats every theme other than `01` as a selection of modes.

```
05 01 02 tt mm
```

`tt` is the theme and `mm` the mode byte.

| To do | Send |
| --- | --- |
| Stay on | `05 01 02 03 40` |
| Cycle through Stay on and Wave | `05 01 02 03 41` |
| Auto Rotate | `05 01 02 01 80` |

Things to know when reading the modes from a settings report:

- **With theme `01`, ignore the mode byte.** The app leaves the selection of
  before in it when "Auto Rotate" is chosen, so it can hold `40` while the
  lights cycle through everything.
- **Bit 7 is not a mode.** The app starts with `80` as mode byte and clears
  bit 7 as soon as a mode is switched on or off. Mask it off before looking
  at the modes.
- **No bits set means all modes.** A mode byte of `00` or `80` was seen on
  controllers that cycle through everything.

## Timers

The controller has three timers. Each is a period in which the lights are
lit, as four bytes: start hour, start minute, end hour, end minute. There
are no seconds and no days of the week.

A timer of `00 00 00 00` is not in use. The app shows the first timer as
18:00–23:59 when it is not in use, and fills in 00:01–07:59 and 08:00–17:59
when a second and third timer are added.

```
04 01 0C  h1 m1 h1 m1  h2 m2 h2 m2  h3 m3 h3 m3
```

All three timers are always sent together. To change one, send the other two
as they are.

Example, 16:00–23:00 and 06:15–07:59, third timer not in use:

```
04 01 0C  10 00 17 00  06 0F 07 3B  00 00 00 00
```

The timers only do something while they are enabled; see
[Switching the lights and the timers](#switching-the-lights-and-the-timers).
They run on the clock of the controller; see
[Power state and clock](#power-state-and-clock).

To delete a timer, the app moves the timers after it one place up and clears
the last one.

## Restoring the default settings

```
07 01 07 02 63 12 00 17 3B 01
```

This is one fixed command. By what the app sets for a group at the same
moment, it gives:

- brightness 99 (`63`),
- timer 1 from 18:00 to 23:59 (`12 00 17 3B`), timers 2 and 3 not in use,
- "Auto Rotate" (`01`).

The meaning of the fourth byte (`02`) is not known. The power state is not
part of the command.

## Setting everything at once

```
08 01 0F  bb  h1 m1 h1 m1  h2 m2 h2 m2  h3 m3 h3 m3  tt mm
```

The 15 bytes after the header are bytes 3–17 of the
[settings report](#settings-report): brightness, the three timers, the mode
theme and the modes.

The app uses this for groups. When it connects to a set of lights that is in
a group, it sends this command with the settings of the group, waits until
that write has succeeded, and then sends the
[power command](#switching-the-lights-and-the-timers).

Example, full brightness, one timer from 18:00 to 23:59, Auto Rotate:

```
08 01 0F  63  12 00 17 3B  00 00 00 00  00 00 00 00  01 80
```

## How the app uses a connection

- It connects when the screen of a set of lights is opened and disconnects
  when that screen is closed. It never stays connected in the background.
- After connecting it enables notifications and asks for the power state,
  which also sets the clock. It asks for the settings when the settings
  screen is opened.
- It gives up on a connection attempt after 10 seconds and holds at most
  four connections at a time, which is why a group in the app has at most
  four sets of lights.
- Groups, names and photos exist in the app only. The controller knows
  nothing about them.

## Not known

- Whether the controller sends notifications on its own, for instance when a
  timer switches the lights.
- What the controller answers to the commands that set something.
- The meaning of bytes 0–2 and 4 of the power report, bytes 0–1 of the
  settings report, and the fourth byte of the command that restores the
  default settings.
- How the kinds `LED-5` and `LED-6` differ from `LED-4`, if at all.
- How long the clock of the controller keeps the time without power.
