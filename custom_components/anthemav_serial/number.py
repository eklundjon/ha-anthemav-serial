from __future__ import annotations

import logging
import re
from collections.abc import Callable

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import AnthemClient
from .const import (
    CONF_ID,
    CONF_MODEL,
    CONF_SW_VERSION,
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
    cmd_hp_balance,
    cmd_hp_bass,
    cmd_hp_treble,
    cmd_hp_volume,
    message_signal,
)

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# Combined headphone status (HSuVvMw) — carries the volume too.
_RE_COMBINED = re.compile(r"^HS[0-9c-j]V([+-]\d+\.\d+)M[01]$")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: AnthemClient = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            AnthemHeadphoneNumber(
                client, entry, "Headphone volume", "hp_volume", "V",
                HP_VOLUME_MIN, HP_VOLUME_MAX, HP_VOLUME_STEP, cmd_hp_volume,
                category=None, combined=True,
            ),
            AnthemHeadphoneNumber(
                client, entry, "Headphone bass", "hp_bass", "B",
                HP_TONE_MIN, HP_TONE_MAX, HP_TONE_STEP, cmd_hp_bass,
            ),
            AnthemHeadphoneNumber(
                client, entry, "Headphone treble", "hp_treble", "T",
                HP_TONE_MIN, HP_TONE_MAX, HP_TONE_STEP, cmd_hp_treble,
            ),
            AnthemHeadphoneNumber(
                client, entry, "Headphone balance", "hp_balance", "L",
                HP_BALANCE_MIN, HP_BALANCE_MAX, HP_BALANCE_STEP, cmd_hp_balance,
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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_ID])},
            name=entry.title,
            manufacturer="Anthem",
            model=entry.data.get(CONF_MODEL),
            sw_version=entry.data.get(CONF_SW_VERSION),
        )

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
