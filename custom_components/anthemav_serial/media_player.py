from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import AnthemClient
from .const import (
    DOMAIN,
    NON_QUERYABLE_SUFFIXES,
    SOURCES,
    VOLUME_MAX,
    VOLUME_MIN,
    ZONE_1_ONLY_QUERY_SUFFIXES,
    ZONE_23_ONLY_QUERY_SUFFIXES,
    ZONE_2,
    ZONE_3,
    ZONE_EXTRA_ATTRS,
    ZONE_MAIN,
    cmd_mute,
    cmd_power,
    cmd_source,
    cmd_volume,
)

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# Zone 1 gets name=None so its entity name IS the device name.
# Zone 2 gets a suffix so it appears as "<device> Zone 2".
ZONE_NAMES: dict[int, str] = {
    ZONE_MAIN: "Main",
    ZONE_2: "Zone 2",
    ZONE_3: "Zone 3",
}


def _effective_sources(entry: ConfigEntry) -> dict[str, str]:
    """Return source index → name, excluding hidden sources."""
    hidden = set(entry.options.get("hidden_sources", []))
    return {
        idx: entry.options.get(f"source_{idx}", default_name)
        for idx, default_name in SOURCES.items()
        if idx not in hidden
    }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: AnthemClient = hass.data[DOMAIN][entry.entry_id]

    zone_entities = [AnthemZoneEntity(client, zone, entry) for zone in (ZONE_MAIN, ZONE_2, ZONE_3)]
    zone_map = {e.zone: e for e in zone_entities}

    tuner = AnthemTunerEntity(client, entry)
    all_entities = [*zone_entities, tuner]

    def on_message(message: str) -> None:
        _LOGGER.debug("RX: %r", message)
        for zone, entity in zone_map.items():
            if message.startswith(f"P{zone}"):
                entity.handle_message(message)
                tuner.notify_zone_source(zone, entity._source_id)
                return
        if message.startswith("H"):
            _LOGGER.debug("Headphone message (entity disabled): %r", message)
            return
        if message.startswith("TAT") or message.startswith("TFT"):
            tuner.handle_message(message)
            return
        if message.startswith("P4"):
            _LOGGER.debug("Zone 4 (rec) message ignored: %r", message)
            return
        if re.match(r"^E\d+$", message):
            _LOGGER.debug("Device error code: %s", message)
            return
        _ZONE_OFF = {"Main Off": ZONE_MAIN, "Zone2 Off": ZONE_2, "Zone3 Off": ZONE_3}
        if message in _ZONE_OFF:
            zone_map[_ZONE_OFF[message]].handle_message(message)
            return
        if message == "Unit Off":
            _LOGGER.debug("Device status: %s", message)
            return
        if message in ("Invalid Command", "Parameter Out-of-range"):
            _LOGGER.warning("Device returned %r (last sent: %r)", message, client.last_command)
            return
        _LOGGER.warning("Unrouted message: %r", message)

    def on_connection_lost() -> None:
        _LOGGER.warning("Lost connection to Anthem device at %s", client.host)
        for entity in all_entities:
            entity.mark_unavailable()

    client._on_message = on_message
    client._on_connection_lost = on_connection_lost

    async_add_entities(all_entities)


class AnthemZoneEntity(MediaPlayerEntity):
    _attr_has_entity_name = True
    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )

    def __init__(self, client: AnthemClient, zone: int, entry: ConfigEntry) -> None:
        self._client = client
        self.zone = zone
        device_id = f"{client.host}:{client.port}"
        self._attr_name = ZONE_NAMES[zone]
        self._attr_unique_id = f"{device_id}_zone{zone}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.title,
            manufacturer="Anthem",
            model="AVM50",
        )
        self._vol_min: float = entry.options.get(f"zone{zone}_vol_min", VOLUME_MIN)
        self._vol_max: float = entry.options.get(f"zone{zone}_vol_max", VOLUME_MAX)

        self._attr_available = False
        self._attr_state: MediaPlayerState | None = None
        self._attr_volume_level: float | None = None
        self._attr_is_volume_muted: bool | None = None
        self._attr_source: str | None = None
        self._source_id: str | None = None

        # Source maps built from options; rebuilt on entry reload.
        self._sources = _effective_sources(entry)
        self._attr_source_list = list(self._sources.values())
        self._source_by_name = {name: idx for idx, name in self._sources.items()}

        # Extra attributes: storage dict + pre-compiled parsers.
        # Sorted longest-suffix-first so e.g. "DF" is tried before "D".
        self._extra_attrs: dict[str, Any] = {}
        self._extra_attr_parsers: list[tuple[re.Pattern[str], str, dict[str, str] | None, bool]] = [
            (re.compile(rf"P{zone}{re.escape(suffix)}(.*)$"), name, enum_map, src_prefix)
            for name, suffix, enum_map, src_prefix in sorted(ZONE_EXTRA_ATTRS, key=lambda x: -len(x[1]))
        ]

    async def async_added_to_hass(self) -> None:
        """Request current state from the device on startup."""
        await self._client.send(f"P{self.zone}P?;P{self.zone}?")
        self.hass.async_create_task(self._async_query_extra_attrs())

    async def _async_query_extra_attrs(self) -> None:
        """Send extra attribute queries in batched stacks after a staggered delay.

        Each zone waits zone*2 seconds so all three don't flood the device at once.
        The device's 32-byte incoming buffer overflows if multiple zones query
        simultaneously.
        """
        await asyncio.sleep(self.zone * 2)
        if self._attr_state != MediaPlayerState.ON:
            _LOGGER.debug("Zone %s is off — skipping extra attr queries", self.zone)
            return
        suffixes = [
            suffix for _, suffix, _, _ in ZONE_EXTRA_ATTRS
            if suffix not in NON_QUERYABLE_SUFFIXES
            and (self.zone == ZONE_MAIN or suffix not in ZONE_1_ONLY_QUERY_SUFFIXES)
            and (self.zone != ZONE_MAIN or suffix not in ZONE_23_ONLY_QUERY_SUFFIXES)
        ]
        for i in range(0, len(suffixes), 5):
            batch = ";".join(f"P{self.zone}{s}?" for s in suffixes[i:i + 5])
            await self._client.send(batch)
            await asyncio.sleep(0.5)

    def handle_message(self, message: str) -> None:
        """Parse a push status message and update entity state."""
        changed = False
        z = self.zone

        # Zone-off notification (e.g. "Main Off", "Zone2 Off") — device sends this
        # instead of P{z}P0 in some contexts (e.g. response to P{z}? when zone is off).
        _zone_off_msg = {1: "Main Off", 2: "Zone2 Off", 3: "Zone3 Off"}.get(z)
        if message == _zone_off_msg:
            self._attr_state = MediaPlayerState.OFF
            self._attr_available = True
            changed = True

        # Power: P{z}P{0|1}
        if m := re.match(rf"P{z}P([01])$", message):
            self._attr_state = (
                MediaPlayerState.ON if m.group(1) == "1" else MediaPlayerState.OFF
            )
            self._attr_available = True
            changed = True
            if m.group(1) == "1" and self.hass:
                self.hass.async_create_task(self._client.send(f"P{z}?"))
                self.hass.async_create_task(self._async_query_extra_attrs())

        # Volume: P{z}VM{db} (zone 1, e.g. "P1VM-35.0") or P{z}V{db} (zones 2/3, e.g. "P2V-15.0")
        if m := re.match(rf"P{z}VM?([+-]?\d+\.\d+)$", message):
            db = float(m.group(1))
            self._attr_volume_level = max(0.0, min(1.0, (db - self._vol_min) / (self._vol_max - self._vol_min)))
            changed = True

        # Mute: P{z}M{0|1}
        if m := re.match(rf"P{z}M([01])$", message):
            self._attr_is_volume_muted = m.group(1) == "1"
            changed = True

        # Source: P{z}S{id}  (id is 0-9 or c-j)
        if m := re.match(rf"P{z}S([0-9c-j])$", message):
            self._source_id = m.group(1)
            self._attr_source = self._sources.get(self._source_id)
            changed = True

        # Combined zone status: P{z}S{source}V{vol}M{mute}[...] (response to P{z}?)
        # Zone 1 appends extra fields (e.g. D7 for decoder), so no $ anchor.
        if m := re.match(rf"P{z}S([0-9c-j])V([+-]?\d+\.\d+)M([01])", message):
            self._source_id = m.group(1)
            self._attr_source = self._sources.get(self._source_id)
            db = float(m.group(2))
            self._attr_volume_level = max(0.0, min(1.0, (db - self._vol_min) / (self._vol_max - self._vol_min)))
            self._attr_is_volume_muted = m.group(3) == "1"
            self._attr_available = True
            changed = True

        # Extra attributes
        for pattern, attr_name, enum_map, src_prefix in self._extra_attr_parsers:
            if m := pattern.match(message):
                raw = m.group(1).strip()
                if src_prefix and raw:
                    raw = raw[1:]  # strip leading source-index char
                if not raw:
                    # Empty payload — device acknowledged query with no data (e.g. P1Q)
                    changed = True
                    break
                if enum_map is not None:
                    self._extra_attrs[attr_name] = enum_map.get(raw, raw)
                else:
                    try:
                        self._extra_attrs[attr_name] = float(raw)
                    except ValueError:
                        self._extra_attrs[attr_name] = raw
                changed = True
                break

        if changed and self.hass:
            self.async_write_ha_state()
        elif not changed:
            _LOGGER.warning("Zone %s: unrecognized message %r", self.zone, message)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self._extra_attrs)

    def mark_unavailable(self) -> None:
        self._attr_available = False
        if self.hass:
            self.async_write_ha_state()

    # --- Commands ---

    async def async_turn_on(self) -> None:
        await self._client.send(cmd_power(self.zone, True))

    async def async_turn_off(self) -> None:
        await self._client.send(cmd_power(self.zone, False))

    async def async_set_volume_level(self, volume: float) -> None:
        db = volume * (self._vol_max - self._vol_min) + self._vol_min
        await self._client.send(cmd_volume(self.zone, db))

    async def async_mute_volume(self, mute: bool) -> None:
        await self._client.send(cmd_mute(self.zone, mute))

    async def async_select_source(self, source: str) -> None:
        source_id = self._source_by_name.get(source)
        if source_id is None:
            _LOGGER.warning(
                "Zone %s: unknown source %r — known sources: %s",
                self.zone, source, list(self._source_by_name),
            )
            return
        _LOGGER.debug("Zone %s: selecting source %r (id=%s)", self.zone, source, source_id)
        await self._client.send(cmd_source(self.zone, source_id))



_TUNER_SOURCE_ID = "4"


class AnthemTunerEntity(MediaPlayerEntity):
    """Built-in tuner — on when any zone has tuner selected as source."""

    _attr_has_entity_name = True
    _attr_name = "Tuner"
    _attr_supported_features = (
        MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
    )
    _attr_media_content_type = MediaType.MUSIC

    def __init__(self, client: AnthemClient, entry: ConfigEntry) -> None:
        self._client = client
        device_id = f"{client.host}:{client.port}"
        self._attr_unique_id = f"{device_id}_tuner"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.title,
            manufacturer="Anthem",
            model="AVM50",
        )
        self._attr_available = False
        self._frequency: str | None = None
        self._zones_on_tuner: set[int] = set()
        self._attr_state = MediaPlayerState.IDLE

    def notify_zone_source(self, zone: int, source_id: str | None) -> None:
        """Called by on_message whenever a zone's source may have changed."""
        if source_id == _TUNER_SOURCE_ID:
            self._zones_on_tuner.add(zone)
        else:
            self._zones_on_tuner.discard(zone)
        new_state = MediaPlayerState.ON if self._zones_on_tuner else MediaPlayerState.IDLE
        changed = new_state != self._attr_state or not self._attr_available
        self._attr_available = True
        self._attr_state = new_state
        if changed and self.hass:
            self.async_write_ha_state()

    @property
    def media_title(self) -> str | None:
        return self._frequency

    async def async_added_to_hass(self) -> None:
        pass  # tuner frequency arrives as push when a zone selects tuner source

    def handle_message(self, message: str) -> None:
        # AM: TAT 530  FM: TFT 87.5  (device includes a space before the value)
        if m := re.match(r"TAT\s*(\d+)$", message):
            self._frequency = f"AM {m.group(1)} kHz"
            self._attr_available = True
        elif m := re.match(r"TFT\s*([\d.]+)$", message):
            self._frequency = f"FM {m.group(1)} MHz"
            self._attr_available = True
        else:
            _LOGGER.warning("Tuner: unrecognized message %r", message)
            return

        if self.hass:
            self.async_write_ha_state()

    def mark_unavailable(self) -> None:
        self._attr_available = False
        if self.hass:
            self.async_write_ha_state()

    async def async_media_next_track(self) -> None:
        await self._client.send("T+")

    async def async_media_previous_track(self) -> None:
        await self._client.send("T-")
