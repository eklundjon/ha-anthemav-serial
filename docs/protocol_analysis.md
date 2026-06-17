# Anthem Gen1 RS-232 — Protocol Analysis by Sub-Device

Derived from the vendor command reference
([Anthem 3-zone AVP - RS-232.csv](Anthem%203-zone%20AVP%20-%20RS-232.csv), dated
21-Jan-09) cross-referenced against what this project has **experimentally
confirmed** on a live AVM 50v via the `scripts/probe_*.py` tools and live
unsolicited-message monitoring.

## Legend

**Query** — a `?` form exists that returns the current value.
**Write-only** — settable but not queryable (HA must be the source of truth).
**Push** — the device emits an *unsolicited* status message when the value changes
at the front panel / IR remote (no query needed).

**Confirmed** column:
- **Exp** — experimentally verified on the device this project (probe or live monitor).
- **Impl** — implemented + unit-tested in the integration (implies it works on-device).
- **Doc** — only from the vendor CSV; not yet exercised.

Push notes: the device is "report-on-change" for the live zone controls
(power/source/volume/mute), confirmed by monitoring while changing inputs. For
config-style settings the integration *queries on add* rather than relying on a
push, because a push was never confirmed for them — so "Push: ?" below means
"not confirmed, treated as query-driven."

---

## Global device facts (confirmed)

- **No hardware serial number.** `?` returns only `model,Version x.xx,build date`
  (e.g. `AVM 50v,Version 1.00,...`) — no unit-unique id. (Exp)
- **64-byte incoming buffer** (note 10). Long/parallel queries overflow it; the
  integration staggers and batches per-zone queries. (Doc + Impl)
- **Zone-off text** (notes 4–7): a command/query to a powered-off path returns
  `Main Off` / `Zone2 Off` / `Zone3 Off` (Rec → `Main Off`), or `Unit Off` when
  no zone is on — *instead of* the normal reply. (Exp: `P1TE?`, `P4S?`,
  `P{z}B?/T?/L?` trims)
- **Terminators:** commands end in `<lf>` (0x0a) or `;`. Replies end in `<lf>`. (Impl)
- **Errors:** `Invalid Command`, `Parameter Out-of-range`; out-of-range *levels*
  clamp silently to min/max (note 1). (Exp: `FP?` → `Parameter Out-of-range`)
- **Simulcast:** source queries can answer `P{z}X{video}{audio}` instead of
  `P{z}S{x}`; the integration tracks the audio char. (Doc + Impl for Rec `P4X`)

---

## Processor (parent device — global / system settings)

| Command(s) | Function | Query | Write-only | Push | Confirmed |
|---|---|---|---|---|---|
| `FP` | Front-panel display brightness (Off/Lo/Med/Hi) | **No** (`FP?`→`Parameter Out-of-range`) | **Yes** | No | **Exp** (write-only verified; persists across power cycles) |
| `FPL` | Front-panel lock (resets Off on power-off) | No | Yes (state-trackable: only clears via our cmd or power-off, which we observe) | No | **Impl** |
| `STE` / `STE?` | Master enable: all auto on/off timers | **Yes** | No | ? | **Impl** |
| `StE` | Triggers global mode (0=off,1=auto,2=RS-232) — **case-distinct from `STE`** | No | Yes | No | **Impl** (must be `2` for `t{n}T` to drive outputs) |
| `t1T`/`t2T`/`t3T` | 12V trigger outputs | No | Yes | No | **Impl** (outputs reset off on power-up → re-applied) |
| `St{n}S`/`St{n}C` | Trigger condition table (path/source) | No | Yes | No | Doc |
| `STF`/`STF?` | Clock format (12/24 hr) | **Yes** | No | ? | **Impl** (queried in options flow) |
| `STC`/`STC?`, `STD`/`STD?` | Current time / day-of-week | **Yes** | No | ? | **Impl** (set by `sync_time` service) |
| `SN` | **Rename a source** | **Destructive** — see note | Yes | No | **Exp** ⚠️ querying `SN…?` *renames* the input; never probe live |
| `SVM` | **Master** mute attenuation, all zones+HP (0–30 dB) | No | Yes | No | Doc |
| `SSB`/`SSB?`, `SSF`/`SSF?`, `SST`/`SST?` | Serial baud / flow / Tx status | **Yes** | No | No | Doc (don't change baud over the live link) |
| `Sf SU/LU/SI/LI/LF/SC/P` | Save / restore / factory-reset settings | — (actions) | Yes | No | Doc |
| `SC*` / `SU*` | Per-source input setup (video in, digital in, EQ, room-EQ, Dolby Vol…) | some `?` | mostly | No | Doc (config-time, keyed by setup slot not runtime) |
| `SHP` | Headphone mutes main speakers | No | Yes | No | Doc |
| `SD*`, `SI*` | Digital-out routing, IR-receiver enable | some | mostly | No | Doc |
| `?` | Identity (model, version, build date) | **Yes** | — | No | **Exp** |

> **`SN` warning:** the `?` form of `SN` is *not* a read — it writes a rename
> using `?` as the name. Confirmed destructively on the live device. See
> `reference_anthem_sn_destructive`.

---

## Main zone

| Command(s) | Function | Query | Write-only | Push | Confirmed |
|---|---|---|---|---|---|
| `P1P` / `P1P?` | Power | **Yes** | No | **Yes** | **Impl/Exp** |
| `P1S` / `P1S?` (`P1X` simulcast) | Source select | **Yes** | No | **Yes** | **Impl/Exp** |
| `P1VM` / `P1VM?` (`P1VMU/D`) | Master volume (MainMaxVol…−95.5 dB / 0.5) | **Yes** | No | **Yes** | **Impl/Exp** |
| `P1M` / `P1MT` | Mute / mute-toggle (state in `P1?`) | via `P1?` | No | **Yes** | **Impl/Exp** |
| `P1SS` | Source seek up/down | — (momentary) | — | — | **Impl** (remote cmd) |
| `P1TE` / `P1TE?` | Tone controls (0=bypassed,1=enabled) | **Yes** | No | ? | **Impl** ("Main Off" when zone off — Exp) |
| `P1E…` / `P1E?` (+ EF/EE/ES/EU/ET/EW/EX/EY/ED/EB/EC/EM*/ER/EN) | Surround / processing mode per signal type | **Yes** | No | (on source change) | **Impl** (set `P1E{src}{mode}` — Exp; read as attrs) |
| `P1C` / `P1C?` | Dynamic-range compression | **Yes** | No | ? | Impl (read as attr) |
| `P1VF/VC/VR/VB/VS/VL` + `?` | Per-channel **level** trims (front/ctr/surr/back ±10, sub +20−30, LFE +0−10) — **per current source** | **Yes** | No | **Yes** | **Impl/Exp** (number entities; **pushed** in the power-on/source-change flood; no-signal reply `P1VF +0.0` has a space) |
| `P1BM` + `BF/BC/BR/BB` | Bass: master + per-channel (±12 / 0.5) | **Yes** | No | ? | **Impl/Exp** (master `P1BM+12.0`; per-channel disabled-by-default) |
| `P1TM` + `TF/TC/TR/TB` | Treble: master + per-channel (±12 / 0.5) | **Yes** | No | ? | **Impl/Exp** |
| `P1LM` + `LF/LR/LB` | Balance: master + per-channel (±10 / 0.5) | **Yes** | No | ? | **Impl/Exp** |
| `P1D?/P1DF?/P1DS?/P1A?/P1AD?` | Decoder / signal / AC3 status (read-only) | **Yes** | (read-only) | (on signal change) | Impl (attrs) |
| `P1Q?` | Processing-mode text (LCD lower line) | **Yes** | (read-only) | ? | Impl (attr) |
| `P1Z` | Sleep timer (Off/30/60/90) | **No** | **Yes** | No | **Exp** (set works; no query) |
| `SV1O` / `SV1M` | Power-up volume / max volume (MainMaxVol) | per-cmd `?` | No | ? | Doc |
| `SZ*` | Speaker / bass-management config (sizes, crossovers, sub) — Main only | `a?` form | — | No | Doc |
| `SP*` | Listener-position distances, lip-sync `SPG` — Main only | some `?` | — | No | Doc |
| `SL*` | Speaker level calibration / Dolby level — Main only | `a?` form | — | No | Doc |
| `SA1*` | Auto-on/off timer schedule (2 timers: wake/off time, source, level) | No | Yes | No | Doc |
| `SO1*` | On-screen display config (Main OSD) | No | Yes | No | Doc |
| `SW*`, `SEQ`, `STV` | Sub room-resonance filter, center EQ, TV size | some `?` | mostly | No | Doc |
| `P1?` | Combined status `P1S{x}V{vol}M{m}D{u}E{v}` | **Yes** | — | — | **Impl** |
| `P1s`, `P1z`, `P1U`, `P1G` | Show status / OSD message / menu nav / video-menu nav | — (actions) | Yes | No | Doc |

---

## Zone 2 / Zone 3 (identical command shape, `P2*` / `P3*`)

| Command(s) | Function | Query | Write-only | Push | Confirmed |
|---|---|---|---|---|---|
| `P{z}P` / `P{z}P?` | Power | **Yes** | No | **Yes** | **Impl/Exp** |
| `P{z}S` / `P{z}S?` (`P{z}X`) | Source (`M`=follow main) | **Yes** | No | **Yes** | **Impl/Exp** |
| `P{z}V` / `P{z}V?` (`U/D`) | Volume (MaxVol…−62.5 dB / 1.25) | **Yes** | No | **Yes** | **Impl/Exp** |
| `P{z}M` / `P{z}MT` | Mute / toggle (state in `P{z}?`) | via `P{z}?` | No | **Yes** | **Impl/Exp** |
| `P{z}L` / `P{z}L?` | Balance (±12.5 / 1.25) | **Yes** | No | ? | **Impl/Exp** |
| `P{z}T` / `P{z}T?` | Treble (±14 / 2.0) | **Yes** | No | ? | **Impl/Exp** |
| `P{z}B` / `P{z}B?` | Bass (±14 / 2.0) | **Yes** | No | ? | **Impl/Exp** |
| `P{z}TE` / `P{z}TE?` | Tone controls | **Yes** | No | ? | **Impl** (exposed as remote bypass/enable cmd) |
| `P{z}SS` | Source seek | — | — | — | **Impl** (remote cmd) |
| `P{z}Z` | Sleep timer | **No** | **Yes** | No | Impl (remote cmd) |
| `SV{z}O`/`SV{z}M` (`SV{z}MF`) | Power-up / max volume (+ fix-at-power-up) | per-cmd `?` | No | ? | Doc |
| `SA{z}*` | Auto-on/off timer schedule (2 timers: wake/off, source, level) | No | Yes | No | Doc |
| `SO2*` | On-screen display config (**Zone 2 OSD only** — no Zone 3 OSD) | No | Yes | No | Doc |
| `P{z}?` | Combined status `P{z}S{x}V{vol}M{m}` | **Yes** | — | — | **Impl** |
| `P{z}Q?` | Processing-mode text (always `Stereo`) | **Yes** | — | — | Doc |

> Zones 2/3 have **single** bass/treble/balance (no per-channel), unlike Main.

---

## Tuner

> Note (CSV line 205): tuner commands work **regardless of main power**, but
> while main is off each reply gets an extra `Main Off` appended.

| Command(s) | Function | Query | Write-only | Push | Confirmed |
|---|---|---|---|---|---|
| `TH` / `TH?` | Tuner mode (Stereo/Hi-blend/Mono) | **Yes** | No | ? | **Impl** |
| `TAT` / `TFT` (+ `U`/`D`) | Set AM/FM frequency, step up/down | via `TT?` | No | ? | Doc |
| `T+` / `T-` | Seek up / down | — | — | — | Doc |
| `TT?` | Current station → `TAT{xxxx}` / `TFT{xxx.x}` | **Yes** | — | ? | Doc |
| `TAP` / `TFP` | Recall AM / FM-band preset | — | Yes | — | Doc |
| `TAS`/`TASy?`, `TFS`/`TFSxy?` | Set / query station presets | **Yes** | No | No | Doc |

---

## Headphone (independent of zone power — confirmed)

| Command(s) | Function | Query | Write-only | Push | Confirmed |
|---|---|---|---|---|---|
| `HV` / `HV?` (`U`/`D`) | Volume (+10…−62.5 dB / 1.25) | **Yes** | No | ? | **Impl/Exp** |
| `HL` / `HL?` | Balance (±12.5 / 1.25) | **Yes** | No | ? | **Impl/Exp** |
| `HT` / `HT?` | Treble (±14 / 2.0) | **Yes** | No | ? | **Impl/Exp** |
| `HB` / `HB?` | Bass (±14 / 2.0) | **Yes** | No | ? | **Impl/Exp** |
| `HM` / `HMT` | Mute / mute-toggle | via `H?` | No | ? | **Impl** |
| `H?` | Combined status `HS{src}V{vol}M{mute}` | **Yes** | — | ? | **Impl/Exp** |
| `SVHO`/`SVHM` | Power-up / max volume | per-cmd `?` | No | ? | Doc |

> Confirmed (probe_headphone): all `H*?` return real values with **main off**;
> replies are uppercase, signed, one decimal (`HV-35.0`, `HL+0.0`). `Hb` is
> deprecated → use `HL`.

---

## Record output ("Zone 4" / Rec)

| Command(s) | Function | Query | Write-only | Push | Confirmed |
|---|---|---|---|---|---|
| `P4S` / `P4S?` (`P4X` simulcast) | Record source (`M`=follow main) | **Yes** | No | ? | **Impl/Exp** |

> Confirmed (probe_P4S): `P4S?` → `P4S{x}` while main on, **`Main Off` while main
> off** → the select is unavailable-when-off + re-queries on `P1P1`.

---

## Video processing (per-source, AVM 50 / D2 only)

A large `f*` family: scale mode `fa`, crop window `fW`/`fA`/`fE`/`fo`–`fr`,
through/extract geometry `fe`–`fw`, picture `fc/fb/fs/fh` (contrast/bright/sat/hue),
detail/noise `fd/fD/fn/fm`, color space `fS`, RGB `fR`, film mode `fF`, gamma
`fG/fX/fI`, frame-lock `fi`, ADC `fV/fT/fP`, chroma `fB/fC/fl`. Plus output config
`SG*` (resolution `SGR`/`SGA`, color space `SGS`, data format `SGD`, preferred
`SGP`).

| Aspect | Finding | Confirmed |
|---|---|---|
| Query form | lowercase `f{x}?{n}` per-source | **Exp** |
| Reply format | **lowercase-echoed** (`fa?2`→`fa21`), *not* the uppercase `Fany` the CSV documents | **Exp** |
| `SG*` replies | **uppercase** (`SGR1g`) | **Exp** |
| Push | **None** — query-only, no unsolicited updates → a live readout must poll | **Exp** |
| Timing | replies lag / interleave → match by prefix, not arrival order | **Exp** |
| `SCF{n}?` | returns `Parameter Out-of-range` — can't read active output config | **Exp** |
| Input resolution | not exposed (only output resolution + scaling) | **Exp** |

---

## Unsolicited-push summary

**Confirmed push (report-on-change):** per-zone power, source, volume, mute — and
the decoder/effect status plus the Main per-channel **level** trims (`P1V*`) that
ride along on a source/signal change (the level trims are per current source).
Verified by monitoring the stream while changing inputs / on power-on
(`monitor_unsolicited.py`, `probe_trims.py`).

**Query-driven (push not confirmed):** tone, auto-timers, tuner mode, record
source, headphone levels, brightness (write-only), and everything under
"Processor config." The integration queries these on add and re-queries on the
relevant power-on, rather than assuming a push.

---

## Coverage: implemented vs. available

| Sub-device | Implemented today | Notable still-available |
|---|---|---|
| Main | power, source, volume, mute, seek, tone defeat, **all bass/treble/balance + per-channel level trims**, sound-mode, sleep (remote), read-only decoder/effect attrs | compression as a control |
| Zone 2/3 | power, source, volume, mute, seek, tone (remote), sleep (remote), **bass/treble/balance** | (per-channel n/a — zones are stereo) |
| Tuner | mode | station set/seek, presets, current-station readout |
| Headphone | volume, bass, treble, balance, mute | power-up/max volume, "mutes main" toggle |
| Processor | brightness, panel lock, auto-timers, record output, triggers (opt-in), time-sync service | auto-timer *schedules*, serial config, displays, save/restore button, speaker/room config |
| Video | none (read-only readout was scoped as a separate track) | full `f*` per-source readout (poll-only) |

**Highest-value next targets** (all queryable, so proper stateful entities): the
**Main surround / processing-mode** selects (`P1E*`), then optionally the Main
**per-channel** trims (front/center/surround/back) for fine speaker tuning.
