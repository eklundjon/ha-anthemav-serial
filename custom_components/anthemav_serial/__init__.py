import logging
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall

from .client import AnthemClient
from .const import (
    CONF_BAUDRATE,
    CONF_ID,
    CONF_URL,
    DEFAULT_BAUDRATE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["media_player", "remote", "switch", "select"]

# AVM50 day encoding: 1=Sunday … 7=Saturday; Python weekday(): 0=Monday … 6=Sunday
_PYTHON_TO_ANTHEM_DAY = [2, 3, 4, 5, 6, 7, 1]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate v1 (host/port, host:port unique_id) to v2 (url/baudrate, id).

    The old `host:port` string is reused verbatim as CONF_ID so existing
    devices and entity history survive the upgrade — only fresh installs
    get a random uuid.
    """
    if entry.version == 1:
        host = entry.data[CONF_HOST]
        port = entry.data[CONF_PORT]
        legacy_id = f"{host}:{port}"
        new_data = {
            k: v for k, v in entry.data.items() if k not in (CONF_HOST, CONF_PORT)
        }
        new_data[CONF_ID] = legacy_id
        new_data[CONF_URL] = f"socket://{host}:{port}"
        new_data[CONF_BAUDRATE] = DEFAULT_BAUDRATE
        hass.config_entries.async_update_entry(
            entry, data=new_data, unique_id=legacy_id, version=2
        )
        _LOGGER.debug("Migrated entry %s to v2 (url=%s)", entry.entry_id, new_data[CONF_URL])
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Handlers are wired by media_player.async_setup_entry via set_handlers()
    # once the entities exist.
    client = AnthemClient(
        url=entry.data[CONF_URL],
        baudrate=entry.data[CONF_BAUDRATE],
    )
    await client.start()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = client
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    async def _handle_sync_time(call: ServiceCall) -> None:
        now = datetime.now()
        use_24hr: bool = entry.options.get("time_format_24hr", False)

        day_cmd = f"STD{_PYTHON_TO_ANTHEM_DAY[now.weekday()]}"
        fmt_cmd = "STF1" if use_24hr else "STF0"
        time_str = now.strftime("%H:%M") if use_24hr else now.strftime("%I:%M%p")
        time_cmd = f"STC{time_str}"

        _LOGGER.debug("Syncing time: %s %s %s", day_cmd, fmt_cmd, time_cmd)
        await client.send(f"{fmt_cmd};{day_cmd};{time_cmd}")

    hass.services.async_register(DOMAIN, "sync_time", _handle_sync_time, schema=vol.Schema({}))

    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        client: AnthemClient = hass.data[DOMAIN].pop(entry.entry_id)
        await client.stop()
    return unloaded
