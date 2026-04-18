from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import selector

from .client import AnthemClient
from .const import DEFAULT_NAME, DEFAULT_PORT, DOMAIN, SOURCES, VOLUME_MAX, VOLUME_MIN

_VOL_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=VOLUME_MIN,
        max=VOLUME_MAX,
        step=0.5,
        mode=selector.NumberSelectorMode.BOX,
        unit_of_measurement="dB",
    )
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
    }
)


def _options_schema(
    current_names: dict[str, str],
    hidden: list[str],
    vol_limits: dict[str, float],
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
        }
    )


class AnthemSerialConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Anthem Serial."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AnthemSerialOptionsFlow:
        return AnthemSerialOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]

            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            try:
                client = AnthemClient(host=host, port=port, on_message=lambda _: None)
                await client.connect()
                await client.stop()
            except (TimeoutError, OSError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"{DEFAULT_NAME} ({host})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
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
            data_schema=_options_schema(current_names, hidden, vol_limits),
        )
