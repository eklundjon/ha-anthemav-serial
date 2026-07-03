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
3. Pick how Home Assistant should reach the RS-232 port, then fill in that connection's fields.
4. Home Assistant probes the device and adds the integration if the connection succeeds.

### Connection type

The first step is a menu; each choice then asks only for the fields it needs:

| Choice | Fields | Use for |
|---|---|---|
| **Network socket** | Host, Port | Raw-TCP serial gateways (WaveShare, iTach, …) — builds a `socket://host:port` URL |
| **RFC 2217** | Host, Port | RFC 2217 (Telnet serial) gateways |
| **ESPHome** | Host, Port | ESPHome UART serial bridge |
| **Local serial** | Device path, Baud rate | A USB/serial adapter on the HA host (e.g. `/dev/ttyUSB0`) |

**Baud rate** is asked only for a local serial device (the Anthem Gen1 default is `9600`); the network choices don't need it.

### Changing the connection later

Use the integration's **Reconfigure** option (**Settings → Devices & Services →** the Anthem entry **→ ⋮ → Reconfigure**) to change the URL or baud rate — for example when moving from a legacy gateway to an ESPHome proxy. The device and **all entity history are preserved**, because the device identity is a stable internal id rather than the connection address.

> **Upgrading from an older version:** entries created with the old host/port fields are migrated automatically to a `socket://host:port` URL on first start. Existing entities and history are kept.

Entities are organized into sub-devices under one processor device — **Main**, **Zone 2**, **Zone 3**, **Tuner**, and **Headphone** — plus processor-wide controls, so an unused zone or feature can be disabled in one place. See [Entities](#entities).

---

## Entities

Entities are grouped into sub-devices hanging off a single **processor** device: **Main**, **Zone 2**, **Zone 3**, **Tuner**, and **Headphone**. This keeps each device page focused and lets you disable an unused zone or feature in one place.

State is **push-driven** — the device reports changes immediately, so the integration doesn't poll. Entities that reflect device state start **unavailable** until the first status message arrives, and zone-scoped entities go unavailable again while their zone is off.

Some entities are **disabled by default** (noted below); enable them from the entity page if you want them. Triggers are opt-in via an [option](#triggers).

### Zone media players — Main, Zone 2, Zone 3

Each zone is a `media_player`:

| Feature | Details |
|---|---|
| Power | Turn on / turn off |
| Volume | Set level (scaled to the configured min/max range) + step up/down |
| Mute | Mute / unmute |
| Source | Select from the configured source list |
| Sound mode | Listening / processing mode — **Main zone only** |

#### Extra state attributes

The Main zone exposes read-only DSP/decoder status as attributes (Zones 2/3 expose a subset), useful in automations and templates. Adjustable trims are separate `number` entities (see [Numbers](#numbers-db-trims)).

| Attribute | Description |
|---|---|
| `decoder`, `decoder_flags`, `source_type` | Active decoder / input flags / signal type |
| `audio_fx`, `dolby_*_fx`, `dts_*_fx`, … | Active listening / effect modes per signal type |
| `compression` | Dynamic-range compression setting |
| `tone_bypass` | Tone-control bypass state |
| `processing_mode` | Free-text processing-mode string |

### Tuner

The **Tuner** represents the built-in AM/FM tuner:

- State is **On** when at least one zone has the tuner selected, **Idle** otherwise.
- The current frequency shows as `media_title` (e.g. `FM 91.7 MHz`).
- **Next track** / **Previous track** seek stations.

### Switches

| Switch | Device | Notes |
|---|---|---|
| Tone defeat | Main | On = tone controls bypassed |
| Headphone mute | Headphone | |
| Front panel lock | Processor | *Disabled by default* |
| Auto on/off timers | Processor | Master enable for the unit's timers. *Disabled by default* |
| Trigger 1 / 2 / 3 | Processor | Only created when [trigger control](#triggers) is enabled |

### Selects

| Select | Device | Notes |
|---|---|---|
| Tuner mode | Tuner | Stereo / Hi-blend / Mono |
| Front panel brightness | Processor | Off / Low / Medium / High |
| Record output | Processor | Record-zone source (inputs + "Main"). *Disabled by default* |

### Numbers (dB trims)

Adjustable level and tone trims, all in dB:

| Device | Numbers |
|---|---|
| Headphone | Volume, Bass, Treble, Balance |
| Main | Bass, Treble, Balance (master); Front / Center / Surround / Back / Sub / LFE **level**; per-channel Bass / Treble / Balance (*disabled by default*) |
| Zone 2, Zone 3 | Bass, Treble, Balance |

Main and Zone 2/3 trims are unavailable while their zone is off; headphone trims are always available (the headphone output is independent of zone power).

### Remotes — Main, Zone 2, Zone 3

Each zone also has a `remote` entity for custom remote-control cards, **disabled by default** (its on/off duplicates the zone's power). Drive it with `remote.send_command`:

| Command | Action |
|---|---|
| `volume_up` / `volume_down` | One volume step (use `num_repeats` for larger jumps) |
| `mute_toggle` | Toggle mute |
| `source_seek_up` / `source_seek_down` | Step through sources |
| `power_on` / `power_off` | Zone power |
| `bypass` / `enable` | Tone controls — bypass or enable |
| `sleep_off` / `sleep_30` / `sleep_60` / `sleep_90` | Sleep timer (minutes) |
| `source_<key>` | Select a source by its protocol key, e.g. `source_5` for DVD1 |

`remote.turn_on` / `remote.turn_off` map to zone power, and the toggle reflects real zone power.

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

### Triggers

Enable **trigger control** to expose the unit's three 12 V trigger outputs as switches. Doing so takes the triggers under RS-232 control (detaching them from their built-in condition table), so it's off by default and gated behind this option rather than the entity list — turning it off hands the triggers back to their internal control. When enabled, `Trigger 1`/`2`/`3` switches appear on the processor device.

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

- **Zones 2 and 3** support fewer DSP attributes and trims than the main zone — this reflects hardware capability (they're downmix stereo), not a software limitation.
- Volume commands for **Zones 2 and 3** use 1.25 dB steps; the main zone uses 0.5 dB steps.
- A few write-only controls (front-panel brightness, panel lock, triggers) have no device query, so Home Assistant restores their last value across restarts rather than reading them back.
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
