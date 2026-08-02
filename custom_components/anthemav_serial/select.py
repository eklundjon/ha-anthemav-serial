from __future__ import annotations

import logging
import re

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .client import AnthemClient
from .const import (
    CONF_ID,
    DOMAIN,
    FP_BRIGHTNESS,
    REC_MAIN_KEY,
    REC_MAIN_LABEL,
    SELECTABLE_SOURCES,
    TUNER_MODES,
    cmd_fp_brightness,
    cmd_rec_source,
    cmd_tuner_mode,
    connection_signal,
    message_signal,
)
from .device import processor_device_info, tuner_device_info

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
        # Most selects live on the processor; the tuner one overrides below.
        self._attr_device_info = processor_device_info(entry)

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
        await self._request_state()

    async def _request_state(self) -> None:
        """Send the query that elicits the current value (if any)."""

    @callback
    def _handle_connection(self, connected: bool) -> None:
        self._attr_available = connected
        self.async_write_ha_state()
        if connected:
            self.hass.async_create_task(self._request_state())

    @callback
    def _handle_message(self, message: str) -> None:
        """Update the current option from a raw device message."""


class AnthemTunerModeSelect(_AnthemSelectBase):
    """Tuner mode (TH): Stereo / Hi-blend / Mono. Stateful."""

    _attr_icon = "mdi:radio"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, client: AnthemClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_device_info = tuner_device_info(entry)
        self._attr_name = "Mode"
        self._attr_unique_id = f"{entry.data[CONF_ID]}_tuner_mode"
        self._attr_options = list(TUNER_MODES.values())
        self._by_label = {v: k for k, v in TUNER_MODES.items()}
        self._attr_current_option: str | None = None
        self._re = re.compile(r"^TH([012])$")

    async def _request_state(self) -> None:
        self._client.request_query("TH?")

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
    """Record output source (P4S): the inputs plus "Main" (follow main zone).

    The device only reports the record source while the main zone is on: P4S?
    answers "Main Off" otherwise (confirmed against the device). So the select
    is unavailable while main is off and re-queries when main powers on, rather
    than sitting at a stale or perpetually-unknown value.
    """

    _attr_icon = "mdi:record-rec"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False  # niche (record/tape routing)

    # Main-zone power-off — also how P4S? replies while main is off.
    _POWER_OFF = frozenset({"P1P0", "Main Off", "Unit Off"})

    def __init__(self, client: AnthemClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_name = "Record output"
        self._attr_unique_id = f"{entry.data[CONF_ID]}_rec_source"
        self._labels = _rec_source_labels(entry)
        self._attr_options = list(self._labels.values())
        self._by_label = {v: k for k, v in self._labels.items()}
        self._attr_current_option: str | None = None
        self._attr_available = False  # until the device reports a source
        # P4Sx, or simulcast P4X{audio}{video} (responses are audio-first).
        self._re_s = re.compile(r"^P4S([0-9c-jM])$")
        self._re_x = re.compile(r"^P4X([0-9c-j])[0-9c-j]$")

    async def _request_state(self) -> None:
        self._client.request_query("P4S?")

    @callback
    def _handle_message(self, message: str) -> None:
        if m := (self._re_s.match(message) or self._re_x.match(message)):
            option = self._labels.get(m.group(1))
            if option is not None and (
                option != self._attr_current_option or not self._attr_available
            ):
                self._attr_current_option = option
                self._attr_available = True
                self.async_write_ha_state()
        elif message in self._POWER_OFF:
            if self._attr_available:
                self._attr_available = False
                self.async_write_ha_state()
        elif message == "P1P1":
            # Main came on — re-query so the record source repopulates.
            self._client.request_query("P4S?")

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
