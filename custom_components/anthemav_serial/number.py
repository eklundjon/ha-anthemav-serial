from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import NamedTuple

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import AnthemClient
from .const import (
    CONF_ID,
    DOMAIN,
    HP_BALANCE_MAX,
    HP_BALANCE_MIN,
    HP_BALANCE_STEP,
    HP_TONE_MAX,
    HP_TONE_MIN,
    HP_TONE_STEP,
    HP_VOLUME_MAX,
    HP_VOLUME_MIN,
    HP_VOLUME_STEP,
    MAIN_BALANCE_MAX,
    MAIN_BALANCE_MIN,
    MAIN_BALANCE_STEP,
    MAIN_LEVEL_MAX,
    MAIN_LEVEL_MIN,
    MAIN_LEVEL_STEP,
    MAIN_LFE_MAX,
    MAIN_LFE_MIN,
    MAIN_SUB_MAX,
    MAIN_SUB_MIN,
    MAIN_TONE_MAX,
    MAIN_TONE_MIN,
    MAIN_TONE_STEP,
    ZONE_2,
    ZONE_3,
    ZONE_BALANCE_MAX,
    ZONE_BALANCE_MIN,
    ZONE_BALANCE_STEP,
    ZONE_MAIN,
    ZONE_TONE_MAX,
    ZONE_TONE_MIN,
    ZONE_TONE_STEP,
    cmd_hp_balance,
    cmd_hp_bass,
    cmd_hp_treble,
    cmd_hp_volume,
    cmd_trim,
    connection_signal,
    message_signal,
)
from .device import headphone_device_info, zone_device_info

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# Combined headphone status (HSuVvMw) — carries the volume too.
_RE_COMBINED = re.compile(r"^HS[0-9c-j]V([+-]\d+\.\d+)M[01]$")

_ZONE_OFF_TEXT = {ZONE_MAIN: "Main Off", ZONE_2: "Zone2 Off", ZONE_3: "Zone3 Off"}

_SPEAKER = "mdi:speaker"
_TUNE = "mdi:tune-vertical"


class _Trim(NamedTuple):
    name: str
    uid: str           # appended to "zone{z}_" for the unique_id
    prefix: str        # command + reply prefix, e.g. "P1BM", "P1VF", "P2L"
    native_min: float
    native_max: float
    step: float
    enabled_default: bool = True
    icon: str = _TUNE


# (native_min, native_max, step) range tuples.
_TONE = (MAIN_TONE_MIN, MAIN_TONE_MAX, MAIN_TONE_STEP)
_BAL = (MAIN_BALANCE_MIN, MAIN_BALANCE_MAX, MAIN_BALANCE_STEP)
_LEVEL = (MAIN_LEVEL_MIN, MAIN_LEVEL_MAX, MAIN_LEVEL_STEP)
_SUB = (MAIN_SUB_MIN, MAIN_SUB_MAX, MAIN_LEVEL_STEP)
_LFE = (MAIN_LFE_MIN, MAIN_LFE_MAX, MAIN_LEVEL_STEP)
_ZTONE = (ZONE_TONE_MIN, ZONE_TONE_MAX, ZONE_TONE_STEP)
_ZBAL = (ZONE_BALANCE_MIN, ZONE_BALANCE_MAX, ZONE_BALANCE_STEP)

# Main zone: master tone + the per-channel level trims (the remote's LEVEL
# buttons) ship enabled; the per-channel bass/treble/balance are setup-menu
# niche and ship disabled-by-default.
_OFF = {"enabled_default": False}
_MAIN_TRIMS: list[_Trim] = [
    _Trim("Bass", "bass", "P1BM", *_TONE),
    _Trim("Treble", "treble", "P1TM", *_TONE),
    _Trim("Balance", "balance", "P1LM", *_BAL),
    _Trim("Front level", "level_front", "P1VF", *_LEVEL, icon=_SPEAKER),
    _Trim("Center level", "level_center", "P1VC", *_LEVEL, icon=_SPEAKER),
    _Trim("Surround level", "level_surround", "P1VR", *_LEVEL, icon=_SPEAKER),
    _Trim("Back level", "level_back", "P1VB", *_LEVEL, icon=_SPEAKER),
    _Trim("Sub level", "level_sub", "P1VS", *_SUB, icon=_SPEAKER),
    _Trim("LFE level", "level_lfe", "P1VL", *_LFE, icon=_SPEAKER),
    _Trim("Front bass", "bass_front", "P1BF", *_TONE, **_OFF),
    _Trim("Center bass", "bass_center", "P1BC", *_TONE, **_OFF),
    _Trim("Surround bass", "bass_surround", "P1BR", *_TONE, **_OFF),
    _Trim("Back bass", "bass_back", "P1BB", *_TONE, **_OFF),
    _Trim("Front treble", "treble_front", "P1TF", *_TONE, **_OFF),
    _Trim("Center treble", "treble_center", "P1TC", *_TONE, **_OFF),
    _Trim("Surround treble", "treble_surround", "P1TR", *_TONE, **_OFF),
    _Trim("Back treble", "treble_back", "P1TB", *_TONE, **_OFF),
    _Trim("Front balance", "balance_front", "P1LF", *_BAL, **_OFF),
    _Trim("Surround balance", "balance_surround", "P1LR", *_BAL, **_OFF),
    _Trim("Back balance", "balance_back", "P1LB", *_BAL, **_OFF),
]


def _zone_trims(z: int) -> list[_Trim]:
    return [
        _Trim("Bass", "bass", f"P{z}B", *_ZTONE),
        _Trim("Treble", "treble", f"P{z}T", *_ZTONE),
        _Trim("Balance", "balance", f"P{z}L", *_ZBAL),
    ]


_TRIMS: dict[int, list[_Trim]] = {
    ZONE_MAIN: _MAIN_TRIMS,
    ZONE_2: _zone_trims(ZONE_2),
    ZONE_3: _zone_trims(ZONE_3),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: AnthemClient = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            AnthemHeadphoneNumber(
                client, entry, "Volume", "hp_volume", "V",
                HP_VOLUME_MIN, HP_VOLUME_MAX, HP_VOLUME_STEP, cmd_hp_volume,
                category=None, combined=True,
            ),
            AnthemHeadphoneNumber(
                client, entry, "Bass", "hp_bass", "B",
                HP_TONE_MIN, HP_TONE_MAX, HP_TONE_STEP, cmd_hp_bass,
            ),
            AnthemHeadphoneNumber(
                client, entry, "Treble", "hp_treble", "T",
                HP_TONE_MIN, HP_TONE_MAX, HP_TONE_STEP, cmd_hp_treble,
            ),
            AnthemHeadphoneNumber(
                client, entry, "Balance", "hp_balance", "L",
                HP_BALANCE_MIN, HP_BALANCE_MAX, HP_BALANCE_STEP, cmd_hp_balance,
            ),
            *(
                AnthemZoneTrimNumber(
                    client, entry, zone, name=t.name,
                    uid_suffix=f"zone{zone}_{t.uid}", prefix=t.prefix,
                    native_min=t.native_min, native_max=t.native_max, step=t.step,
                    enabled_default=t.enabled_default, icon=t.icon,
                )
                for zone, specs in _TRIMS.items()
                for t in specs
            ),
        ]
    )


class AnthemHeadphoneNumber(NumberEntity):
    """A headphone dB control (volume / bass / treble / balance).

    Each maps to one H{letter} command, is queried on add, and tracks the
    device's echo. The headphone output is independent of zone power, so these
    stay available regardless of which zones are on.
    """

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "dB"
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:headphones"

    def __init__(
        self,
        client: AnthemClient,
        entry: ConfigEntry,
        name: str,
        uid_suffix: str,
        letter: str,
        native_min: float,
        native_max: float,
        step: float,
        send_cmd: Callable[[float], str],
        *,
        category: EntityCategory | None = EntityCategory.CONFIG,
        combined: bool = False,
    ) -> None:
        self._client = client
        self._entry_id = entry.entry_id
        self._letter = letter
        self._send_cmd = send_cmd
        self._step = step
        self._combined = combined
        self._attr_name = name
        self._attr_unique_id = f"{entry.data[CONF_ID]}_{uid_suffix}"
        self._attr_native_min_value = native_min
        self._attr_native_max_value = native_max
        self._attr_native_step = step
        self._attr_entity_category = category
        self._attr_native_value: float | None = None
        self._re = re.compile(rf"^H{letter}([+-]\d+\.\d+)$")
        self._attr_device_info = headphone_device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, message_signal(self._entry_id), self._handle_message
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, connection_signal(self._entry_id), self._handle_connection
            )
        )
        self._client.request_query(f"H{self._letter}?")

    @callback
    def _handle_connection(self, connected: bool) -> None:
        self._attr_available = connected
        self.async_write_ha_state()
        if connected:
            self._client.request_query(f"H{self._letter}?")

    @callback
    def _handle_message(self, message: str) -> None:
        m = self._re.match(message)
        if m is None and self._combined:
            m = _RE_COMBINED.match(message)
        if m is None:
            return
        value = round(float(m.group(1)) / self._step) * self._step
        if value != self._attr_native_value:
            self._attr_native_value = value
            self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        await self._client.send(self._send_cmd(value))
        self._attr_native_value = round(value / self._step) * self._step
        self.async_write_ha_state()


class AnthemZoneTrimNumber(NumberEntity):
    """A per-zone tone/level trim (bass/treble/balance/channel level) as a dB number.

    Tied to its zone's power: the device answers the query with zone-off text
    while the zone is off, so the entity is unavailable then and re-queries when
    the zone powers on — mirroring the tone-defeat switch and record select.
    """

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "dB"
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        client: AnthemClient,
        entry: ConfigEntry,
        zone: int,
        *,
        name: str,
        uid_suffix: str,
        prefix: str,
        native_min: float,
        native_max: float,
        step: float,
        enabled_default: bool = True,
        icon: str = _TUNE,
    ) -> None:
        self._client = client
        self._entry_id = entry.entry_id
        self._prefix = prefix
        self._step = step
        self._attr_name = name
        self._attr_icon = icon
        self._attr_entity_registry_enabled_default = enabled_default
        self._attr_unique_id = f"{entry.data[CONF_ID]}_{uid_suffix}"
        self._attr_native_min_value = native_min
        self._attr_native_max_value = native_max
        self._attr_native_step = step
        self._attr_native_value: float | None = None
        self._attr_available = False  # until the zone reports its value
        # Tolerate the optional space in the no-signal level reply ("P1VF +0.0").
        self._re = re.compile(rf"^{prefix}\s?([+-]?\d+\.\d+)$")
        self._power_off = frozenset({f"P{zone}P0", _ZONE_OFF_TEXT[zone], "Unit Off"})
        self._power_on = f"P{zone}P1"
        self._attr_device_info = zone_device_info(entry, zone)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, message_signal(self._entry_id), self._handle_message
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, connection_signal(self._entry_id), self._handle_connection
            )
        )
        self._client.request_query(f"{self._prefix}?")

    @callback
    def _handle_connection(self, connected: bool) -> None:
        self._attr_available = connected
        self.async_write_ha_state()
        if connected:
            self._client.request_query(f"{self._prefix}?")

    @callback
    def _handle_message(self, message: str) -> None:
        if m := self._re.match(message):
            value = round(float(m.group(1)) / self._step) * self._step
            if value != self._attr_native_value or not self._attr_available:
                self._attr_native_value = value
                self._attr_available = True
                self.async_write_ha_state()
        elif message in self._power_off:
            if self._attr_available:
                self._attr_available = False
                self.async_write_ha_state()
        elif message == self._power_on:
            # Zone came on — re-query so the trim repopulates.
            self._client.request_query(f"{self._prefix}?")

    async def async_set_native_value(self, value: float) -> None:
        await self._client.send(cmd_trim(self._prefix, value, self._step))
        self._attr_native_value = round(value / self._step) * self._step
        self.async_write_ha_state()
