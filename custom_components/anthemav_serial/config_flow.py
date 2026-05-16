from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .client import AnthemClient
from .const import (
    CONF_BAUDRATE,
    CONF_ID,
    CONF_MODEL,
    CONF_SW_VERSION,
    CONF_URL,
    DEFAULT_BAUDRATE,
    DEFAULT_NAME,
    DOMAIN,
    SOURCES,
    VOLUME_MAX,
    VOLUME_MIN,
)

_IDENTITY_RE = re.compile(r"^(.+?)\s+(v\d+\.\S+)\s+(.+)$")


async def _probe(url: str, baudrate: int) -> tuple[str, str | None]:
    """Connect, query device identity, return (model, sw_version).

    Raises TimeoutError/OSError on connection failure, or any other
    exception for unexpected errors — callers map these to form errors.
    """
    client = AnthemClient(url=url, baudrate=baudrate)
    await client.start()
    try:
        identity = await client.query_one("?", "")
    finally:
        await client.stop()

    model = DEFAULT_NAME
    sw_version: str | None = None
    if identity and (m := _IDENTITY_RE.match(identity)):
        model = m.group(1)
        sw_version = m.group(2)
    return model, sw_version

_VOL_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=VOLUME_MIN,
        max=VOLUME_MAX,
        step=0.5,
        mode=selector.NumberSelectorMode.BOX,
        unit_of_measurement="dB",
    )
)

def _connection_schema(url: str = "", baudrate: int = DEFAULT_BAUDRATE) -> vol.Schema:
    """Schema for the URL + baudrate form (reused by user and reconfigure)."""
    return vol.Schema(
        {
            vol.Required(CONF_URL, default=url): str,
            vol.Required(CONF_BAUDRATE, default=baudrate): int,
        }
    )


def _options_schema(
    current_names: dict[str, str],
    hidden: list[str],
    vol_limits: dict[str, float],
    time_format_24hr: bool,
) -> vol.Schema:
    return vol.Schema(
        {
            **{
                vol.Optional(f"source_{idx}", default=current_names[idx]): str
                for idx in sorted(SOURCES)
            },
            vol.Optional("hidden_sources", default=hidden): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": idx, "label": current_names[idx]}
                        for idx in sorted(SOURCES)
                    ],
                    multiple=True,
                )
            ),
            **{
                vol.Optional(key, default=vol_limits[key]): _VOL_SELECTOR
                for key in (
                    "zone1_vol_min", "zone1_vol_max",
                    "zone2_vol_min", "zone2_vol_max",
                    "zone3_vol_min", "zone3_vol_max",
                )
            },
            vol.Optional("time_format_24hr", default=time_format_24hr): bool,
        }
    )


class AnthemSerialConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Anthem Serial."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AnthemSerialOptionsFlow:
        return AnthemSerialOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input[CONF_URL]
            baudrate = user_input[CONF_BAUDRATE]
            try:
                model, sw_version = await _probe(url, baudrate)
            except (TimeoutError, OSError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                # No hardware serial number is available from the Gen1
                # protocol, so the device identity is an opaque random id
                # stored in the entry. It stays stable when the URL changes
                # (reconfigure), keeping the device and its entities intact.
                await self.async_set_unique_id(uuid4().hex)
                entry_data = {
                    CONF_ID: self.unique_id,
                    CONF_URL: url,
                    CONF_BAUDRATE: baudrate,
                    CONF_MODEL: model,
                }
                if sw_version is not None:
                    entry_data[CONF_SW_VERSION] = sw_version
                return self.async_create_entry(title=model, data=entry_data)

        return self.async_show_form(
            step_id="user",
            data_schema=_connection_schema(),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the connection URL/baudrate without recreating the entry.

        The stable CONF_ID is preserved, so the device registry entry and
        all entity history survive moving between e.g. a legacy gateway and
        an esphome serial proxy.
        """
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input[CONF_URL]
            baudrate = user_input[CONF_BAUDRATE]
            try:
                model, sw_version = await _probe(url, baudrate)
            except (TimeoutError, OSError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                new_data = {
                    **entry.data,
                    CONF_URL: url,
                    CONF_BAUDRATE: baudrate,
                    CONF_MODEL: model,
                }
                if sw_version is not None:
                    new_data[CONF_SW_VERSION] = sw_version
                self.hass.config_entries.async_update_entry(
                    entry, title=model, data=new_data
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(
                entry.data.get(CONF_URL, ""),
                entry.data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE),
            ),
            errors=errors,
        )


class AnthemSerialOptionsFlow(OptionsFlow):
    """Allow the user to rename inputs."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current_names = {
            idx: self.config_entry.options.get(f"source_{idx}", default_name)
            for idx, default_name in SOURCES.items()
        }
        hidden = self.config_entry.options.get("hidden_sources", [])

        if "time_format_24hr" in self.config_entry.options:
            time_format_24hr: bool = self.config_entry.options["time_format_24hr"]
        else:
            # Query the device for its current clock format setting.
            client = self.hass.data[DOMAIN][self.config_entry.entry_id]
            response = await client.query_one("STF?", "STF")
            time_format_24hr = response == "STF1" if response is not None else False
        vol_limits = {
            key: self.config_entry.options.get(key, default)
            for key, default in [
                ("zone1_vol_min", VOLUME_MIN), ("zone1_vol_max", VOLUME_MAX),
                ("zone2_vol_min", VOLUME_MIN), ("zone2_vol_max", VOLUME_MAX),
                ("zone3_vol_min", VOLUME_MIN), ("zone3_vol_max", VOLUME_MAX),
            ]
        }

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(current_names, hidden, vol_limits, time_format_24hr),
        )
