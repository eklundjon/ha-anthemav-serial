from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Any

from homeassistant.components.remote import RemoteEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import AnthemClient
from .config_flow import CONF_MODEL, CONF_SW_VERSION
from .const import DOMAIN, SOURCES, ZONE_MAIN, ZONE_2, ZONE_3

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

_ZONE_NAMES: dict[int, str] = {ZONE_MAIN: "Main", ZONE_2: "Zone 2", ZONE_3: "Zone 3"}


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
    """
    if cmd == "volume_up":
        return f"P{zone}VMU" if zone == ZONE_MAIN else f"P{zone}VU"
    if cmd == "volume_down":
        return f"P{zone}VMD" if zone == ZONE_MAIN else f"P{zone}VD"
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
    """Remote entity for one Anthem zone — designed for custom remote cards."""

    _attr_has_entity_name = True
    _attr_is_on = True  # always ready to accept commands

    def __init__(self, client: AnthemClient, zone: int, entry: ConfigEntry) -> None:
        self._client = client
        self.zone = zone
        device_id = f"{client.host}:{client.port}"
        self._attr_name = _ZONE_NAMES[zone]
        self._attr_unique_id = f"{device_id}_zone{zone}_remote"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.title,
            manufacturer="Anthem",
            model=entry.data.get(CONF_MODEL),
            sw_version=entry.data.get(CONF_SW_VERSION),
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._client.send(f"P{self.zone}P1")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._client.send(f"P{self.zone}P0")

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        num_repeats: int = kwargs.get("num_repeats", 1)
        delay_secs: float = kwargs.get("delay_secs", 0.0)

        for cmd in command:
            device_cmd = _resolve_command(self.zone, cmd)
            if device_cmd is None:
                _LOGGER.warning(
                    "Remote zone %s: unknown command %r — valid commands: "
                    "volume_up, volume_down, mute_toggle, source_seek_up, "
                    "source_seek_down, power_on, power_off, source_{key}",
                    self.zone, cmd,
                )
                continue
            for _ in range(num_repeats):
                await self._client.send(device_cmd)
                if delay_secs:
                    await asyncio.sleep(delay_secs)
