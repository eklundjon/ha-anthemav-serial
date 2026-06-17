from __future__ import annotations

import logging
import re
from collections.abc import Callable

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
    message_signal,
)
from .device import headphone_device_info, zone_device_info

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# Combined headphone status (HSuVvMw) — carries the volume too.
_RE_COMBINED = re.compile(r"^HS[0-9c-j]V([+-]\d+\.\d+)M[01]$")

_ZONE_OFF_TEXT = {ZONE_MAIN: "Main Off", ZONE_2: "Zone2 Off", ZONE_3: "Zone3 Off"}

# Per zone: (name, uid, command/reply prefix, min, max, step). Main is the master
# trim (P1BM/P1TM/P1LM); Zones 2/3 use P{z}B/P{z}T/P{z}L.
_TRIMS: dict[int, list[tuple[str, str, str, float, float, float]]] = {
    ZONE_MAIN: [
        ("Bass", "bass", "P1BM", MAIN_TONE_MIN, MAIN_TONE_MAX, MAIN_TONE_STEP),
        ("Treble", "treble", "P1TM", MAIN_TONE_MIN, MAIN_TONE_MAX, MAIN_TONE_STEP),
        ("Balance", "balance", "P1LM", MAIN_BALANCE_MIN, MAIN_BALANCE_MAX, MAIN_BALANCE_STEP),
    ],
    ZONE_2: [
        ("Bass", "bass", "P2B", ZONE_TONE_MIN, ZONE_TONE_MAX, ZONE_TONE_STEP),
        ("Treble", "treble", "P2T", ZONE_TONE_MIN, ZONE_TONE_MAX, ZONE_TONE_STEP),
        ("Balance", "balance", "P2L", ZONE_BALANCE_MIN, ZONE_BALANCE_MAX, ZONE_BALANCE_STEP),
    ],
    ZONE_3: [
        ("Bass", "bass", "P3B", ZONE_TONE_MIN, ZONE_TONE_MAX, ZONE_TONE_STEP),
        ("Treble", "treble", "P3T", ZONE_TONE_MIN, ZONE_TONE_MAX, ZONE_TONE_STEP),
        ("Balance", "balance", "P3L", ZONE_BALANCE_MIN, ZONE_BALANCE_MAX, ZONE_BALANCE_STEP),
    ],
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
                    client, entry, zone, name=name,
                    uid_suffix=f"zone{zone}_{uid}", prefix=prefix,
                    native_min=lo, native_max=hi, step=step,
                )
                for zone, specs in _TRIMS.items()
                for name, uid, prefix, lo, hi, step in specs
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
        self.hass.async_create_task(self._client.send(f"H{self._letter}?"))

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
    """A per-zone tone trim (bass/treble/balance) as a dB number.

    Tied to its zone's power: the device answers the query with zone-off text
    while the zone is off, so the entity is unavailable then and re-queries when
    the zone powers on — mirroring the tone-defeat switch and record select.
    """

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "dB"
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:tune-vertical"

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
    ) -> None:
        self._client = client
        self._entry_id = entry.entry_id
        self._prefix = prefix
        self._step = step
        self._attr_name = name
        self._attr_unique_id = f"{entry.data[CONF_ID]}_{uid_suffix}"
        self._attr_native_min_value = native_min
        self._attr_native_max_value = native_max
        self._attr_native_step = step
        self._attr_native_value: float | None = None
        self._attr_available = False  # until the zone reports its value
        self._re = re.compile(rf"^{prefix}([+-]?\d+\.\d+)$")
        self._power_off = frozenset({f"P{zone}P0", _ZONE_OFF_TEXT[zone], "Unit Off"})
        self._power_on = f"P{zone}P1"
        self._attr_device_info = zone_device_info(entry, zone)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, message_signal(self._entry_id), self._handle_message
            )
        )
        self.hass.async_create_task(self._client.send(f"{self._prefix}?"))

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
            self.hass.async_create_task(self._client.send(f"{self._prefix}?"))

    async def async_set_native_value(self, value: float) -> None:
        await self._client.send(cmd_trim(self._prefix, value, self._step))
        self._attr_native_value = round(value / self._step) * self._step
        self.async_write_ha_state()
