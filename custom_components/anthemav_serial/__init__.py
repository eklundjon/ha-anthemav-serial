import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .client import AnthemClient
from .const import (
    CONF_BAUDRATE,
    CONF_ID,
    CONF_URL,
    DEFAULT_BAUDRATE,
    DOMAIN,
)
from .router import MessageRouter

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.MEDIA_PLAYER,
    Platform.REMOTE,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.NUMBER,
]

# AVM50 day encoding: 1=Sunday … 7=Saturday; Python weekday(): 0=Monday … 6=Sunday
_PYTHON_TO_ANTHEM_DAY = [2, 3, 4, 5, 6, 7, 1]

SERVICE_SYNC_TIME = "sync_time"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the domain-wide sync_time action once (not per config entry)."""

    async def _handle_sync_time(call: ServiceCall) -> None:
        clients: dict[str, AnthemClient] = hass.data.get(DOMAIN, {})
        if not clients:
            raise ServiceValidationError("No Anthem device is loaded to sync")

        now = dt_util.now()
        day_cmd = f"STD{_PYTHON_TO_ANTHEM_DAY[now.weekday()]}"
        for entry_id, client in clients.items():
            entry = hass.config_entries.async_get_entry(entry_id)
            use_24hr = bool(entry and entry.options.get("time_format_24hr", False))
            fmt_cmd = "STF1" if use_24hr else "STF0"
            time_str = now.strftime("%H:%M") if use_24hr else now.strftime("%I:%M%p")
            _LOGGER.debug("Sync time on %s: %s;%s;STC%s", entry_id, fmt_cmd, day_cmd, time_str)
            await client.send(f"{fmt_cmd};{day_cmd};STC{time_str}")

    hass.services.async_register(
        DOMAIN, SERVICE_SYNC_TIME, _handle_sync_time, schema=vol.Schema({})
    )
    return True


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
    client = AnthemClient(
        url=entry.data[CONF_URL],
        baudrate=entry.data[CONF_BAUDRATE],
    )
    # Wire the message/connection handler before connecting and before forwarding
    # platforms, so no entity's add-time query reply is lost — every platform
    # subscribes to message_signal and self-filters.
    router = MessageRouter(hass, client, entry.entry_id)
    client.set_handlers(router.dispatch, router.connection_lost, router.connection_restored)
    try:
        await client.start()
    except (OSError, TimeoutError) as err:
        # A transient connect failure (e.g. the gateway briefly unreachable,
        # "No route to host", or a connect timeout) should not permanently fail
        # the entry. Raise ConfigEntryNotReady so HA retries with backoff
        # instead of leaving the entry dead and its options flow stranded.
        raise ConfigEntryNotReady(
            f"Could not connect to {entry.data[CONF_URL]}: {err}"
        ) from err
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = client
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        client: AnthemClient = hass.data[DOMAIN].pop(entry.entry_id)
        await client.stop()
    return unloaded
