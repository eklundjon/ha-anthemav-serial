DOMAIN = "anthem_serial"

DEFAULT_PORT = 14000  # adjust to match your gateway
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

def cmd_query_power(zone: int) -> str:
    return f"P{zone}P?"

def cmd_query_source(zone: int) -> str:
    return f"P{zone}S?"

def cmd_query_volume(zone: int) -> str:
    return f"P{zone}VM?"

def cmd_query_status(zone: int) -> str:
    return f"P{zone}?"

def cmd_volume(zone: int, db: float) -> str:
    db_rounded = round(db * 2) / 2  # device accepts 0.5 dB increments
    return f"P{zone}VM{db_rounded:+.1f}"

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
