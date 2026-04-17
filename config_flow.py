from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback

from .client import AnthemClient
from .const import DEFAULT_NAME, DEFAULT_PORT, DOMAIN, SOURCES

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
    }
)


def _options_schema(current_names: dict[int, str]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(f"source_{idx}", default=current_names[idx]): str
            for idx in sorted(SOURCES)
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

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(current_names),
        )
