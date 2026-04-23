# Anthem A/V Gen1 Serial

<img src="https://brands.home-assistant.io/anthemav/logo.png" alt="Anthem" width="200">

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.1.0+-blue.svg)](https://www.home-assistant.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A Home Assistant custom integration for controlling **Anthem first-generation A/V receivers and processors** over a TCP-to-serial bridge. This is tested on an AVM-50V but should work with D2v and earlier AVM processors and contemporary MRX receivers.

Anthem's newer IP-based receivers are supported by the built-in [`anthemav`](https://www.home-assistant.io/integrations/anthemav/) integration. This integration fills the gap for older models that communicate only via RS-232 serial.

---

## Supported Hardware

| Model | Status |
|---|---|
| AVM 50v | Confirmed |
| AVM 20, AVM 30, AVM 40, AVM 50 | Likely compatible — same Gen1 serial protocol |
| MRX 300, MRX 500, MRX 700 | Likely compatible |

If you confirm compatibility with another model, please open an issue.

---

## Prerequisites

- A **TCP-to-serial bridge** that exposes the receiver's or processor's RS-232 port on your network. Common options:
  - [WaveShare Serial Server](https://www.waveshare.com/rs232-485-422-to-poe-eth-b.htm)
  - [GlobalCache iTach](https://www.globalcache.com/products/itach/)
  - Any device that presents the serial port as a raw TCP socket
- Home Assistant **2024.1.0** or later

---

## Installation

### HACS (recommended)

1. Open HACS in your Home Assistant instance.
2. Go to **Integrations** → **⋮** → **Custom repositories**.
3. Add the URL of this repository and select **Integration** as the category.
4. Search for **Anthem A/V Gen1 Serial** and click **Download**.
5. Restart Home Assistant.

### Manual

1. Download or clone this repository.
2. Copy the `custom_components/anthemav_serial` directory into your Home Assistant `config/custom_components/` directory.
3. Restart Home Assistant.

---

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**.
2. Search for **Anthem A/V Gen1 Serial**.
3. Enter the **host** (IP address or hostname of your serial bridge) and **port** (default: `14000`).
4. Home Assistant will test the connection. If successful, the integration is added.

Three media player entities are created immediately: **Main**, **Zone 2**, and **Zone 3**. A **Tuner** entity is also created and activates automatically when any zone selects the tuner as its source.

---

## Entities

### Zone entities — Main, Zone 2, Zone 3

Each zone appears as a `media_player` entity with the following features:

| Feature | Details |
|---|---|
| Power | Turn on / turn off |
| Volume | Set level (scaled to configured min/max range) |
| Mute | Mute / unmute |
| Source | Select from the configured source list |

State is **push-driven**: the device sends updates immediately when anything changes, so the integration does not poll.

Entities start as **unavailable** on startup and become available once the first status message is received from the device.

#### Extra state attributes

The Main zone exposes a rich set of additional attributes from the device's DSP and decoder status. Zones 2 and 3 expose a subset. These appear as entity attributes and can be used in automations and templates.

| Attribute | Description |
|---|---|
| `decoder` | Active decoder (Stereo, Dolby Digital, DTS, …) |
| `decoder_flags` | Decoder input flags |
| `source_type` | Digital / analog / PCM / etc. |
| `audio_fx` | Active listening mode |
| `compression` | Dynamic range compression setting |
| `tone_bypass` | Tone control bypass state |
| `bass` / `treble` | Per-channel tone trim (dB) |
| `balance` | Balance trim (dB) |
| `volume_trim_*` | Per-speaker level trim (dB) |
| `processing_mode` | Free-text processing mode string |
| *(and more)* | Various FX and DSP mode attributes |

### Tuner entity

The **Tuner** entity represents the AVM50's built-in AM/FM tuner.

- State is **On** when at least one zone has the tuner selected as its source; **Idle** otherwise.
- The current frequency is shown as `media_title` (e.g. `FM 91.7 MHz` or `AM 810 kHz`).
- **Next track** / **Previous track** buttons seek to the next or previous station.

---

## Options

Open the integration's **Configure** dialog to adjust the following settings.

### Sources

Each of the AVM50's 18 input sources can be:

- **Renamed** — give inputs friendly names that match your actual equipment.
- **Hidden** — remove unused inputs from the source list shown in the UI and voice assistants.

### Per-zone volume limits

By default, the full hardware volume range (−95.5 dB to +31.5 dB) is mapped to the 0–100% slider in Home Assistant. If your setup never uses the extremes, you can narrow the range per zone so the slider covers a more useful window.

| Setting | Default |
|---|---|
| Main zone minimum | −95.5 dB |
| Main zone maximum | +31.5 dB |
| Zone 2 minimum | −95.5 dB |
| Zone 2 maximum | +31.5 dB |
| Zone 3 minimum | −95.5 dB |
| Zone 3 maximum | +31.5 dB |

### Clock display format

Controls whether the AVM50's front-panel clock shows **12-hour** or **24-hour** time. This setting is read from the device when you first open the options dialog, so the default reflects whatever the device is currently set to.

---

## Actions (Services)

### `anthemav_serial.sync_time`

Sets the AVM50's internal clock (day of week, time, and 12/24-hour display format) to match the current time on the Home Assistant host.

This action takes no parameters. The 12/24-hour format is taken from the **Clock display format** option.

#### Example — sync at midnight every day

```yaml
automation:
  - alias: "Sync Anthem clock"
    trigger:
      - platform: time
        at: "00:00:00"
    action:
      - action: anthemav_serial.sync_time
```

---

## Known Limitations

- **Zone 4 (Rec output)** sends source-change messages that are silently discarded. It is not exposed as an entity.
- **Headphone output** is not yet exposed as an entity.
- **Zones 2 and 3** support fewer DSP attributes than the main zone — this reflects hardware capability, not a software limitation.
- Volume commands for **Zones 2 and 3** use 1.25 dB steps; the main zone uses 0.5 dB steps.
- The integration requires a **TCP-to-serial bridge** — direct USB-to-serial adapters are not supported.

---

## Contributing

Bug reports and pull requests are welcome. Please open an issue first for anything beyond a small fix.

When submitting a pull request, run the test suite locally before opening it:

```bash
pip install -r requirements.test.txt
pytest tests/ -v
```

---

## License

MIT
