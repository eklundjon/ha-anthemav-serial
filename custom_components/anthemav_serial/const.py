DOMAIN = "anthemav_serial"

DEFAULT_NAME = "Anthem AVM50"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_URL = "url"
CONF_BAUDRATE = "baudrate"
CONF_ID = "id"
CONF_MODEL = "model"
CONF_SW_VERSION = "sw_version"

# Anthem Gen1 RS-232 default; only meaningful for native serial URLs
# (ignored for socket://, rfc2217://, esphome://) but serialx requires it.
DEFAULT_BAUDRATE = 9600

CMD_TERMINATOR = "\n"

# Zone identifiers
ZONE_MAIN = 1
ZONE_2 = 2
ZONE_3 = 3

# Commands
def cmd_power(zone: int, on: bool) -> str:
    return f"P{zone}P{1 if on else 0}"


def cmd_volume(zone: int, db: float) -> str:
    if zone == ZONE_MAIN:
        db_rounded = round(db * 2) / 2        # 0.5 dB steps
        return f"P{zone}VM{db_rounded:+.1f}"
    else:
        db_rounded = round(db / 1.25) * 1.25  # 1.25 dB steps (zones 2/3)
        return f"P{zone}V{db_rounded:+.2f}"

def cmd_volume_up(zone: int) -> str:
    # One native step (0.5 dB on zone 1, 1.25 dB on zones 2/3).
    return f"P{zone}VMU" if zone == ZONE_MAIN else f"P{zone}VU"

def cmd_volume_down(zone: int) -> str:
    return f"P{zone}VMD" if zone == ZONE_MAIN else f"P{zone}VD"

def cmd_mute(zone: int, mute: bool) -> str:
    return f"P{zone}M{1 if mute else 0}"

def cmd_source(zone: int, source: str) -> str:
    return f"P{zone}S{source}"

def cmd_sound_mode(zone: int, source: str, mode: str) -> str:
    # P{z}E{source}{mode} sets the per-source stereo/2.0 listening effect
    # (CSV: P1E,nx). The active source char is required, not just the mode.
    return f"P{zone}E{source}{mode}"

def cmd_tone_controls(zone: int, enabled: bool) -> str:
    # P{z}TE: 1=tone controls enabled, 0=bypassed.
    return f"P{zone}TE{1 if enabled else 0}"

def cmd_panel_lock(locked: bool) -> str:
    # FPL: 1=front panel locked (except power), 0=unlocked. Write-only.
    return f"FPL{1 if locked else 0}"

def cmd_auto_timers(enabled: bool) -> str:
    # STE: enable/disable all auto on/off timers.
    return f"STE{1 if enabled else 0}"


# Trigger outputs are write-only and global mode `StE` must be 2 (RS-232
# control) for t{n}T to drive an output — so every trigger write asserts the
# mode first. `StE` is global (all 3 triggers) and detaches them from their
# built-in condition table, which is why trigger control is opt-in.
def cmd_trigger(num: int, on: bool) -> str:
    return f"StE2;t{num}T{1 if on else 0}"


# Hand the triggers back to their internal auto/condition control.
TRIGGER_HANDBACK = "StE1"


# ── Select entities ────────────────────────────────────────────────────────────
TUNER_MODES: dict[str, str] = {"0": "Stereo", "1": "Hi-blend", "2": "Mono"}
SLEEP_TIMERS: dict[str, str] = {"0": "Off", "1": "30 min", "2": "60 min", "3": "90 min"}
FP_BRIGHTNESS: dict[str, str] = {"0": "Off", "1": "Low", "2": "Medium", "3": "High"}

# Record output ("zone 4") extra source: "M" = follow the main-zone source.
REC_MAIN_KEY = "M"
REC_MAIN_LABEL = "Main"


def cmd_tuner_mode(key: str) -> str:
    return f"TH{key}"


def cmd_sleep_timer(zone: int, key: str) -> str:
    return f"P{zone}Z{key}"


def cmd_fp_brightness(key: str) -> str:
    return f"FP{key}"


def cmd_rec_source(key: str) -> str:
    # P4S: set the record output source (key is a source char or "M" = Main).
    return f"P4S{key}"


# ── Headphone output (independent of zone power) ─────────────────────────────────
# Ranges/steps per the HV/HL/HT/HB command docs. The device echoes one decimal
# with an explicit sign (e.g. HV-35.0, HL+0.0), confirmed against the AVM50.
HP_VOLUME_MIN, HP_VOLUME_MAX, HP_VOLUME_STEP = -62.5, 10.0, 1.25
HP_BALANCE_MIN, HP_BALANCE_MAX, HP_BALANCE_STEP = -12.5, 12.5, 1.25
HP_TONE_MIN, HP_TONE_MAX, HP_TONE_STEP = -14.0, 14.0, 2.0  # treble and bass


def _round_step(db: float, step: float) -> float:
    return round(db / step) * step


def cmd_hp_volume(db: float) -> str:
    return f"HV{_round_step(db, HP_VOLUME_STEP):+.2f}"


def cmd_hp_balance(db: float) -> str:
    return f"HL{_round_step(db, HP_BALANCE_STEP):+.2f}"


def cmd_hp_treble(db: float) -> str:
    return f"HT{_round_step(db, HP_TONE_STEP):+.2f}"


def cmd_hp_bass(db: float) -> str:
    return f"HB{_round_step(db, HP_TONE_STEP):+.2f}"


def cmd_hp_mute(mute: bool) -> str:
    return f"HM{1 if mute else 0}"


# ── Per-zone tone trims (bass / treble / balance) ────────────────────────────────
# Main uses 0.5 dB steps (±12 bass/treble, ±10 balance); Zones 2/3 use the wider
# 2.0 / 1.25 steps (same as the headphone). Commands: Main master P1BM/P1TM/P1LM;
# Zones P{z}B/P{z}T/P{z}L. Replies echo `{prefix}sxx.x`.
MAIN_TONE_MIN, MAIN_TONE_MAX, MAIN_TONE_STEP = -12.0, 12.0, 0.5
MAIN_BALANCE_MIN, MAIN_BALANCE_MAX, MAIN_BALANCE_STEP = -10.0, 10.0, 0.5
ZONE_TONE_MIN, ZONE_TONE_MAX, ZONE_TONE_STEP = -14.0, 14.0, 2.0
ZONE_BALANCE_MIN, ZONE_BALANCE_MAX, ZONE_BALANCE_STEP = -12.5, 12.5, 1.25
# Main per-channel level trims (dB, 0.5 step): front/center/surround/back ±10,
# subwoofer +20/-30, LFE +0/-10. Replies may include a space when no signal
# ("P1VF +0.0"), so the number entity's regex tolerates optional whitespace.
MAIN_LEVEL_MIN, MAIN_LEVEL_MAX, MAIN_LEVEL_STEP = -10.0, 10.0, 0.5
MAIN_SUB_MIN, MAIN_SUB_MAX = -30.0, 20.0
MAIN_LFE_MIN, MAIN_LFE_MAX = -10.0, 0.0


def cmd_trim(prefix: str, db: float, step: float) -> str:
    """Set a zone tone trim; prefix is e.g. 'P1BM' (Main bass) or 'P2L' (Zone2 balance)."""
    return f"{prefix}{_round_step(db, step):+.2f}"


def message_signal(entry_id: str) -> str:
    """Dispatcher signal carrying every raw device message for an entry.

    Lets non-media_player platforms (switch, etc.) observe the device stream
    without each one wiring its own client handler.
    """
    return f"{DOMAIN}_message_{entry_id}"

# Source map — keys are the characters sent to/received from the device
SOURCES = {
    "0": "CD",
    "1": "2-Ch BAL",
    "2": "6-Ch SE",
    "3": "Tape",
    "4": "Tuner",
    "5": "DVD1",
    "6": "TV1",
    "7": "SAT1",
    "8": "VCR",
    "9": "AUX",
    "c": "current",
    "d": "DVD2",
    "e": "DVD3",
    "f": "DVD4",
    "g": "TV2",
    "h": "TV3",
    "i": "TV4",
    "j": "SAT2",
}

# "c" (current) is a meta value the device accepts as a "recall current source"
# command and can echo back, but it is not a real selectable input. Keep it in
# SOURCES for message parsing, but exclude it from anything user-facing.
META_SOURCE_KEYS: frozenset[str] = frozenset({"c"})

# Real, user-selectable inputs (source picker + options-flow rename/hide UI).
SELECTABLE_SOURCES: dict[str, str] = {
    idx: name for idx, name in SOURCES.items() if idx not in META_SOURCE_KEYS
}

VOLUME_MIN = -95.5
VOLUME_MAX = 31.5

# ---- Extra zone attributes -----------------------------------------------
# Enum maps for interpreted values
_DECODER_STATUS: dict[str, str] = {
    "0": "Stereo", "1": "Dolby Digital", "2": "DTS", "3": "MPEG",
    "4": "6-Ch", "5": "2-Ch Analog Direct", "6": "No Signal",
    "7": "Dolby Digital Plus", "8": "Dolby TrueHD", "9": "DTS-HD",
}
_DECODER_FLAGS: dict[str, str] = {
    "0": "No Signal", "1": "Mono", "2": "2Ch Unflagged", "3": "2Ch Flagged",
    "4": "6Ch Unflagged Dolby", "5": "Dolby Digital 5.1 EX",
    "6": "6Ch Unflagged DTS", "7": "DTS EX Matrix", "8": "DTS EX Discrete",
    "9": "6Ch Analog/PCM", "A": "8 Channel",
}
_SOURCE_TYPE: dict[str, str] = {
    "0": "Digital", "1": "DTS 24/96", "2": "Analog DSP",
    "3": "Analog Direct", "4": "Auto Digital",
    "5": "DTS-HD Low Bit Rate", "6": "DTS-HD Master Audio",
    "7": "DTS-ES Discrete", "8": "DTS-HD Matrix", "9": "PCM",
    "a": "Dolby Digital", "b": "DTS Digital Surround",
    "c": "Dolby Digital Plus", "d": "Dolby TrueHD",
    "e": "DTS-HD High Resolution",
}
_FX_MODES: dict[str, str] = {
    "0": "Off", "1": "AnthemLogic Music", "2": "AnthemLogic Cinema",
    "3": "ProLogic IIx Music", "4": "ProLogic IIx Movie", "5": "ProLogic",
    "6": "Neo:6 Music", "7": "Neo:6 Cinema", "8": "All-Channel Stereo",
    "9": "All-Channel Mono", "A": "Mono", "B": "Mono Academy",
    "C": "ProLogic IIx Matrix", "D": "ProLogic IIx Game",
}

# Sound modes exposed to HA's sound-mode selector (Main zone only). These are
# the stereo/2.0 listening effects set by P{z}E{source}{mode}. Curated to the
# digit-keyed modes (0-9): every common mode, all confirmed settable on the
# AVM 50v, and free of the a-d upper/lowercase ambiguity. The exotic a-d modes
# (Mono, Mono Academy, ProLogic IIx Matrix/Game) are intentionally omitted.
SOUND_MODES: dict[str, str] = {k: v for k, v in _FX_MODES.items() if k.isdigit()}
SOUND_MODE_BY_NAME: dict[str, str] = {v: k for k, v in SOUND_MODES.items()}

_DOLBY_EX_FX: dict[str, str] = {
    "0": "Off", "1": "Dolby Digital EX", "2": "THX Surround EX",
    "3": "ProLogic IIx Movie", "4": "ProLogic IIx Movie THX",
    "5": "ProLogic IIx Music", "6": "Neo:6", "7": "Neo:6 THX",
}
_DOLBY_DIGITAL_FX: dict[str, str] = {
    "0": "Off", "1": "THX Cinema 5.1", "2": "THX Ultra2 Cinema",
    "3": "THX Music", "4": "THX Surround EX", "5": "THX Games",
    "6": "PLIIx Movie", "7": "PLIIx Movie THX", "8": "PLIIx Music",
    "9": "Dolby Digital EX", "A": "Neo:6", "B": "Neo:6 THX",
}
_DTS_FX: dict[str, str] = {
    "0": "Off", "1": "THX Cinema 5.1", "2": "THX Ultra2 Cinema",
    "3": "THX Music", "4": "Neo:6 THX", "5": "THX Games",
    "6": "PLIIx Movie", "7": "PLIIx Movie THX", "8": "PLIIx Music",
    "9": "Dolby Digital EX", "A": "Neo:6",
}
_DTS_MATRIX_FX: dict[str, str] = {
    "0": "Off", "1": "Off", "2": "THX Cinema",
    "3": "Off", "4": "THX Cinema", "5": "Off", "6": "Off",
}
_ON_OFF: dict[str, str] = {"0": "Off", "1": "On"}

# Extra per-zone attributes beyond power/source/volume/mute.
# Each tuple: (ha_attr_name, cmd_suffix, enum_map or None, source_prefixed).
# source_prefixed=True means the device prepends the active source index to the
# value in its response (e.g. P1D77 → source 7, decoder value 7).
# Sorted longest-suffix-first at parse time to avoid ambiguous prefix matches.
ZONE_EXTRA_ATTRS: list[tuple[str, str, dict[str, str] | None, bool]] = [
    # Decoder / format status  (all source-prefixed)
    ("decoder",                  "D",   _DECODER_STATUS,  True),
    ("decoder_flags",            "DF",  _DECODER_FLAGS,   True),
    ("source_type",              "DS",  _SOURCE_TYPE,     True),
    ("processing_mode",          "Q",   None,             False),  # free-text, no prefix
    ("ac3_status",               "A",   {"0": "Not AC3", "1": "2-Channel", "2": "Multichannel"}, True),
    ("ac3_dialog_normalization", "AD",  None,             True),
    # DSP / listening mode  (source-independent)
    ("compression",              "C",   {"0": "Normal", "1": "Reduced", "2": "Night"}, False),
    ("tone_bypass",              "TE",  {"0": "On", "1": "Off"},                       False),
    ("sleep_timer",              "Z",   {"0": "Off", "1": "30 min", "2": "60 min", "3": "90 min"}, False),
    # FX modes  (all source-prefixed)
    ("audio_fx",                 "E",   _FX_MODES,        True),
    ("dolby_stereo_fx",          "EF",  _FX_MODES,        True),
    ("dolby_ex_fx",              "EE",  _DOLBY_EX_FX,     True),
    ("dts_matrix_fx",            "ES",  _DTS_MATRIX_FX,   True),
    ("dolby_stereo_thx",         "EU",  {"0": "Off", "1": "THX Cinema", "2": "THX Games"}, True),
    ("stereo_thx",               "ET",  {"0": "Off", "1": "THX Cinema", "2": "THX Game"},  True),
    ("seven_ch_thx",             "EW",  {"0": "Off", "1": "THX Cinema"},                   True),
    ("dolby_digital_fx",         "EX",  _DOLBY_DIGITAL_FX, True),
    ("six_ch_fx",                "EY",  _DOLBY_DIGITAL_FX, True),
    ("dts_fx",                   "ED",  _DTS_FX,           True),
    ("prologic_panorama",        "EMP", _ON_OFF,           True),
    ("prologic_width",           "EMC", None,              True),
    ("prologic_dimension",       "EMD", None,              True),
    ("dts_neo6_center_gain",     "EMG", None,              True),
    ("thx_reeq_thx",             "ER",  _ON_OFF,           True),
    ("thx_reeq_non_thx",         "EN",  _ON_OFF,           True),
    # Tone/level trims (bass/treble/balance/per-channel level) are exposed as
    # number entities, not attributes — the media_player recognizes-and-ignores
    # those P{z}* messages (see _owned_elsewhere) rather than carrying them here.
]

# Suffixes that are only valid to query on zone 1 (zones 2/3 return Invalid Command
# or Parameter Out-of-range).  Parsers still handle push messages from any zone.
ZONE_1_ONLY_QUERY_SUFFIXES: frozenset[str] = frozenset({
    # Decoder / AC3
    "D", "DF", "DS", "A", "AD",
    # Compression (zone 1 DSP only)
    "C",
    # FX modes
    "E", "EF", "EE", "ES", "EU", "ET", "EW", "EX", "EY", "ED",
    "EMP", "EMC", "EMD", "EMG", "ER", "EN",
})

# Suffixes only valid for zones 2/3 (zone 1 uses the longer-suffix variants)
# Zone 2/3 bass/treble/balance are number entities now, not media_player attrs.
ZONE_23_ONLY_QUERY_SUFFIXES: frozenset[str] = frozenset()

# Suffixes not queryable on any zone (write-only or push-only)
NON_QUERYABLE_SUFFIXES: frozenset[str] = frozenset({"Z"})
