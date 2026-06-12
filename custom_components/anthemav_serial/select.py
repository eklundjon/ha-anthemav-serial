from __future__ import annotations

import logging
import re

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .client import AnthemClient
from .const import (
    CONF_ID,
    CONF_MODEL,
    CONF_SW_VERSION,
    DOMAIN,
    FP_BRIGHTNESS,
    REC_MAIN_KEY,
    REC_MAIN_LABEL,
    SELECTABLE_SOURCES,
    TUNER_MODES,
    cmd_fp_brightness,
    cmd_rec_source,
    cmd_tuner_mode,
    message_signal,
)

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


def _rec_source_labels(entry: ConfigEntry) -> dict[str, str]:
    """Record-output source key -> label: Main plus the (renamed, non-hidden) inputs."""
    hidden = set(entry.options.get("hidden_sources", []))
    labels = {
        idx: entry.options.get(f"source_{idx}", name)
        for idx, name in SELECTABLE_SOURCES.items()
        if idx not in hidden
    }
    return {REC_MAIN_KEY: REC_MAIN_LABEL, **labels}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: AnthemClient = hass.data[DOMAIN][entry.entry_id]
    entities: list[SelectEntity] = [
        AnthemTunerModeSelect(client, entry),
        AnthemRecordSourceSelect(client, entry),
        AnthemBrightnessSelect(client, entry),
    ]
    async_add_entities(entities)


class _AnthemSelectBase(SelectEntity):
    """Shared wiring: device info, message subscription, initial query."""

    _attr_has_entity_name = True

    def __init__(self, client: AnthemClient, entry: ConfigEntry) -> None:
        self._client = client
        self._entry_id = entry.entry_id
        device_id = entry.data[CONF_ID]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
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
        await self._request_state()

    async def _request_state(self) -> None:
        """Send the query that elicits the current value (if any)."""

    @callback
    def _handle_message(self, message: str) -> None:
        """Update the current option from a raw device message."""


class AnthemTunerModeSelect(_AnthemSelectBase):
    """Tuner mode (TH): Stereo / Hi-blend / Mono. Stateful."""

    _attr_icon = "mdi:radio"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, client: AnthemClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_name = "Tuner mode"
        self._attr_unique_id = f"{entry.data[CONF_ID]}_tuner_mode"
        self._attr_options = list(TUNER_MODES.values())
        self._by_label = {v: k for k, v in TUNER_MODES.items()}
        self._attr_current_option: str | None = None
        self._re = re.compile(r"^TH([012])$")

    async def _request_state(self) -> None:
        await self._client.send("TH?")

    @callback
    def _handle_message(self, message: str) -> None:
        if m := self._re.match(message):
            option = TUNER_MODES[m.group(1)]
            if option != self._attr_current_option:
                self._attr_current_option = option
                self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        await self._client.send(cmd_tuner_mode(self._by_label[option]))
        self._attr_current_option = option
        self.async_write_ha_state()


class AnthemRecordSourceSelect(_AnthemSelectBase):
    """Record output source (P4S): the inputs plus "Main" (follow main zone)."""

    _attr_icon = "mdi:record-rec"

    def __init__(self, client: AnthemClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_name = "Record output"
        self._attr_unique_id = f"{entry.data[CONF_ID]}_rec_source"
        self._labels = _rec_source_labels(entry)
        self._attr_options = list(self._labels.values())
        self._by_label = {v: k for k, v in self._labels.items()}
        self._attr_current_option: str | None = None
        # P4Sx, or simulcast P4X{audio}{video} (responses are audio-first).
        self._re_s = re.compile(r"^P4S([0-9c-jM])$")
        self._re_x = re.compile(r"^P4X([0-9c-j])[0-9c-j]$")

    async def _request_state(self) -> None:
        await self._client.send("P4S?")

    @callback
    def _handle_message(self, message: str) -> None:
        m = self._re_s.match(message) or self._re_x.match(message)
        if m and (option := self._labels.get(m.group(1))) != self._attr_current_option:
            if option is not None:
                self._attr_current_option = option
                self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        await self._client.send(cmd_rec_source(self._by_label[option]))
        self._attr_current_option = option
        self.async_write_ha_state()


class AnthemBrightnessSelect(_AnthemSelectBase, RestoreEntity):
    """Front-panel display brightness (FP): Off / Low / Medium / High.

    Write-only on the device (not queryable), so HA is the source of truth — the
    last set value is restored across restarts rather than coming up unknown.
    """

    _attr_icon = "mdi:brightness-6"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, client: AnthemClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_name = "Front panel brightness"
        self._attr_unique_id = f"{entry.data[CONF_ID]}_fp_brightness"
        self._attr_options = list(FP_BRIGHTNESS.values())
        self._by_label = {v: k for k, v in FP_BRIGHTNESS.items()}
        self._attr_current_option: str | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) and last.state in self._attr_options:
            self._attr_current_option = last.state

    async def async_select_option(self, option: str) -> None:
        await self._client.send(cmd_fp_brightness(self._by_label[option]))
        self._attr_current_option = option
        self.async_write_ha_state()
