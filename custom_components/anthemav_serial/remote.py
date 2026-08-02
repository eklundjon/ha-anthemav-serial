from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Iterable
from typing import Any

from homeassistant.components.remote import RemoteEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import AnthemClient
from .const import (
    CONF_ID,
    DOMAIN,
    SOURCES,
    ZONE_2,
    ZONE_3,
    ZONE_MAIN,
    cmd_power,
    cmd_sleep_timer,
    cmd_tone_controls,
    cmd_volume_down,
    cmd_volume_up,
    connection_signal,
    message_signal,
)
from .device import zone_device_info

# Sleep-timer remote commands -> P{z}Z key (0=Off, 1=30, 2=60, 3=90 min).
_SLEEP_COMMANDS = {"sleep_off": "0", "sleep_30": "1", "sleep_60": "2", "sleep_90": "3"}

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: AnthemClient = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AnthemRemoteEntity(client, zone, entry)
        for zone in (ZONE_MAIN, ZONE_2, ZONE_3)
    )


def _resolve_command(zone: int, cmd: str) -> str | None:
    """Map a named remote command to a device command string.

    Supported commands:
      volume_up / volume_down   — one step; repeat via num_repeats
      mute_toggle
      source_seek_up / source_seek_down
      power_on / power_off
      source_{key}              — e.g. source_0 (CD), source_5 (DVD1)
      bypass / enable           — tone controls: bypass (defeat) or enable
      sleep_off / sleep_30 / sleep_60 / sleep_90  — sleep timer (minutes)
    """
    if cmd == "volume_up":
        return cmd_volume_up(zone)
    if cmd == "volume_down":
        return cmd_volume_down(zone)
    if cmd == "bypass":
        return cmd_tone_controls(zone, False)  # tone controls bypassed (defeat)
    if cmd == "enable":
        return cmd_tone_controls(zone, True)  # tone controls enabled (normal)
    if cmd in _SLEEP_COMMANDS:
        return cmd_sleep_timer(zone, _SLEEP_COMMANDS[cmd])
    if cmd == "mute_toggle":
        return f"P{zone}MT"
    if cmd == "source_seek_up":
        return f"P{zone}SS+"
    if cmd == "source_seek_down":
        return f"P{zone}SS-"
    if cmd == "power_on":
        return f"P{zone}P1"
    if cmd == "power_off":
        return f"P{zone}P0"
    if cmd.startswith("source_"):
        key = cmd[len("source_"):]
        if key in SOURCES:
            return f"P{zone}S{key}"
    return None


class AnthemRemoteEntity(RemoteEntity):
    """Remote entity for one Anthem zone — a send_command surface for custom
    remote cards/automations, whose on/off reflects the zone's real power.

    The toggle tracks zone power from the device stream (P{z}P{0|1}, plus the
    zone-off and unit-off text) rather than being a hardcoded "on", so it stays
    in sync with the media_player. The remote itself is not marked unavailable
    when the zone is off — commands (e.g. power_on) are still valid then.

    Disabled by default: it duplicates the media_player's power toggle on the
    zone device, so it's opt-in for custom-card / send_command use.
    """

    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = False

    def __init__(self, client: AnthemClient, zone: int, entry: ConfigEntry) -> None:
        self._client = client
        self.zone = zone
        self._entry_id = entry.entry_id
        device_id = entry.data[CONF_ID]
        self._attr_name = None  # the zone IS its sub-device
        self._attr_unique_id = f"{device_id}_zone{zone}_remote"
        self._attr_is_on: bool | None = None  # until the device reports power
        self._re_power = re.compile(rf"^P{zone}P([01])$")
        self._off_text = {
            ZONE_MAIN: "Main Off", ZONE_2: "Zone2 Off", ZONE_3: "Zone3 Off"
        }[zone]
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
        self._client.request_query(f"P{self.zone}P?")

    @callback
    def _handle_connection(self, connected: bool) -> None:
        self._attr_available = connected
        self.async_write_ha_state()
        if connected:
            self._client.request_query(f"P{self.zone}P?")

    @callback
    def _handle_message(self, message: str) -> None:
        if m := self._re_power.match(message):
            is_on = m.group(1) == "1"
        elif message in (self._off_text, "Unit Off"):
            is_on = False
        else:
            return
        if is_on != self._attr_is_on:
            self._attr_is_on = is_on
            self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._client.send(cmd_power(self.zone, True))
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._client.send(cmd_power(self.zone, False))
        self._attr_is_on = False
        self.async_write_ha_state()

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        num_repeats: int = kwargs.get("num_repeats", 1)
        delay_secs: float = kwargs.get("delay_secs", 0.0)

        for cmd in command:
            device_cmd = _resolve_command(self.zone, cmd)
            if device_cmd is None:
                _LOGGER.warning(
                    "Remote zone %s: unknown command %r — valid commands: "
                    "volume_up, volume_down, mute_toggle, source_seek_up, "
                    "source_seek_down, power_on, power_off, bypass, enable, "
                    "sleep_off, sleep_30, sleep_60, sleep_90, source_{key}",
                    self.zone, cmd,
                )
                continue
            for _ in range(num_repeats):
                await self._client.send(device_cmd)
                if delay_secs:
                    await asyncio.sleep(delay_secs)
