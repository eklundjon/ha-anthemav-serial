DOMAIN = "anthemav_serial"

DEFAULT_NAME = "Anthem AVM50"
CONF_HOST = "host"
CONF_PORT = "port"

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

def cmd_mute(zone: int, mute: bool) -> str:
    return f"P{zone}M{1 if mute else 0}"

def cmd_source(zone: int, source: str) -> str:
    return f"P{zone}S{source}"

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
    # Per-channel volume trims (dB)  (source-independent)
    ("volume_trim_front",        "VF",  None, False),
    ("volume_trim_center",       "VC",  None, False),
    ("volume_trim_surround",     "VR",  None, False),
    ("volume_trim_back",         "VB",  None, False),
    ("volume_trim_sub",          "VS",  None, False),
    ("volume_trim_lfe",          "VL",  None, False),
    # Balance (dB)  (source-independent)
    ("balance",                  "LM",  None, False),
    ("balance_front",            "LF",  None, False),
    ("balance_surround",         "LR",  None, False),
    ("balance_back",             "LB",  None, False),
    # Bass (dB)  (source-independent)
    ("bass",                     "BM",  None, False),  # zone 1
    ("bass",                     "B",   None, False),  # zones 2/3
    ("bass_front",               "BF",  None, False),
    ("bass_center",              "BC",  None, False),
    ("bass_surround",            "BR",  None, False),
    ("bass_rear",                "BB",  None, False),
    # Treble (dB)  (source-independent)
    ("treble",                   "TM",  None, False),  # zone 1
    ("treble",                   "T",   None, False),  # zones 2/3
    ("treble_front",             "TF",  None, False),
    ("treble_center",            "TC",  None, False),
    ("treble_surround",          "TR",  None, False),
    ("treble_rear",              "TB",  None, False),
    # Balance (dB)  (source-independent)
    ("balance",                  "L",   None, False),  # zones 2/3
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
    # Volume trims
    "VF", "VC", "VR", "VB", "VS", "VL",
    # Balance (zone 1 variants)
    "LM", "LF", "LR", "LB",
    # Bass (zone 1 variants)
    "BM", "BF", "BC", "BR", "BB",
    # Treble (zone 1 variants)
    "TM", "TF", "TC", "TR", "TB",
})

# Suffixes only valid for zones 2/3 (zone 1 uses the longer-suffix variants)
ZONE_23_ONLY_QUERY_SUFFIXES: frozenset[str] = frozenset({"B", "T", "L"})

# Suffixes not queryable on any zone (write-only or push-only)
NON_QUERYABLE_SUFFIXES: frozenset[str] = frozenset({"Z"})
