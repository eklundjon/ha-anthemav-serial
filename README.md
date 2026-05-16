# Anthem A/V Gen1 Serial

<img src="https://brands.home-assistant.io/anthemav/logo.png" alt="Anthem" width="200">

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.1.0+-blue.svg)](https://www.home-assistant.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A Home Assistant custom integration for controlling **Anthem first-generation A/V receivers and processors** over their RS-232 control port. Connect via a network serial gateway, an ESPHome serial proxy, or a directly-attached USB/serial adapter. Tested on an AVM-50V but should work with D2v and earlier AVM processors and contemporary MRX receivers.

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

- A way to reach the receiver's or processor's RS-232 port. Any of:
  - A **network serial gateway** presenting the port as a raw TCP socket — e.g. [WaveShare Serial Server](https://www.waveshare.com/rs232-485-422-to-poe-eth-b.htm) or [GlobalCache iTach](https://www.globalcache.com/products/itach/)
  - A device speaking **RFC 2217** (Telnet serial)
  - An **ESPHome** node exposing a UART serial bridge
  - A **directly-attached USB/serial adapter** on the Home Assistant host
- Home Assistant **2024.1.0** or later

Connection handling is provided by the [`serialx`](https://pypi.org/project/serialx/) library, which is installed automatically.

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
3. Enter the **Connection URL** and **Baud rate**.
4. Home Assistant will probe the device and add the integration if the connection succeeds.

### Connection URL

The URL scheme selects the transport:

| Scheme | Example | Use for |
|---|---|---|
| `socket://` | `socket://192.168.1.50:14000` | Raw-TCP serial gateways (WaveShare, iTach, …) |
| `rfc2217://` | `rfc2217://192.168.1.50:4000` | RFC 2217 (Telnet serial) gateways |
| `esphome://` | `esphome://anthem-bridge.local:6053` | ESPHome UART serial bridge |
| *(device path)* | `/dev/ttyUSB0` | USB/serial adapter on the HA host |

**Baud rate** matters only for a directly-attached serial adapter (the Anthem Gen1 default is `9600`). It is ignored for the `socket://`, `rfc2217://`, and `esphome://` schemes but is still required by the form.

### Changing the connection later

Use the integration's **Reconfigure** option (**Settings → Devices & Services →** the Anthem entry **→ ⋮ → Reconfigure**) to change the URL or baud rate — for example when moving from a legacy gateway to an ESPHome proxy. The device and **all entity history are preserved**, because the device identity is a stable internal id rather than the connection address.

> **Upgrading from an older version:** entries created with the old host/port fields are migrated automatically to a `socket://host:port` URL on first start. Existing entities and history are kept.

Three media player entities are created immediately: **Main**, **Zone 2**, and **Zone 3**. A **Tuner** entity is also created and activates automatically when any zone selects the tuner as its source. Three **Remote** entities (one per zone) are also created — see [Entities](#entities).

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
- The `tuner_mode` attribute reports Stereo / Hi-blend / Mono (visible while the tuner entity is available).

### Remote entities — Main, Zone 2, Zone 3

Each zone also gets a `remote` entity, intended for custom remote-control cards. Drive it with `remote.send_command`:

| Command | Action |
|---|---|
| `volume_up` / `volume_down` | One volume step (use `num_repeats` for larger jumps) |
| `mute_toggle` | Toggle mute |
| `source_seek_up` / `source_seek_down` | Step through sources |
| `power_on` / `power_off` | Zone power |
| `source_<key>` | Select a source by its protocol key, e.g. `source_5` for DVD1 |

`remote.turn_on` / `remote.turn_off` map to zone power.

```yaml
action: remote.send_command
target:
  entity_id: remote.avm_50v_main
data:
  command: volume_up
  num_repeats: 3
```

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
- The Gen1 protocol exposes no hardware serial number, so the integration cannot auto-detect a duplicate device — adding the same unit twice creates two entries.

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
