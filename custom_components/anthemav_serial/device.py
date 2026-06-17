"""Device topology helpers.

The processor is one HA device; each zone, the tuner, and the headphone output
are sub-devices hanging off it via `via_device`. This lets the UI group entities
per function and lets a user disable a whole zone/feature they don't use.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

from .const import CONF_ID, CONF_MODEL, CONF_SW_VERSION, DOMAIN

_ZONE_LABELS: dict[int, str] = {1: "Main", 2: "Zone 2", 3: "Zone 3"}


def processor_device_info(entry: ConfigEntry) -> DeviceInfo:
    """The processor itself — the parent every sub-device hangs off."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.data[CONF_ID])},
        name=entry.title,
        manufacturer="Anthem",
        model=entry.data.get(CONF_MODEL),
        sw_version=entry.data.get(CONF_SW_VERSION),
    )


def _sub_device_info(entry: ConfigEntry, suffix: str, label: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.data[CONF_ID]}_{suffix}")},
        name=f"{entry.title} {label}",
        manufacturer="Anthem",
        via_device=(DOMAIN, entry.data[CONF_ID]),
    )


def zone_device_info(entry: ConfigEntry, zone: int) -> DeviceInfo:
    return _sub_device_info(entry, f"zone{zone}", _ZONE_LABELS[zone])


def tuner_device_info(entry: ConfigEntry) -> DeviceInfo:
    return _sub_device_info(entry, "tuner", "Tuner")


def headphone_device_info(entry: ConfigEntry) -> DeviceInfo:
    return _sub_device_info(entry, "headphone", "Headphone")
