from __future__ import annotations

import logging
import re
from typing import Any
from uuid import uuid4

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_DEVICE, CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import selector

_LOGGER = logging.getLogger(__name__)

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
    SELECTABLE_SOURCES,
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
        # Match only a line shaped like the identity string, so an unsolicited
        # status push arriving first isn't mistaken for the reply.
        identity = await client.query_one("?", match=lambda msg: bool(_IDENTITY_RE.match(msg)))
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

# Menu options == the per-scheme step ids. Network schemes build a
# "{scheme}://{host}:{port}" serialx URL; "serial" uses a bare device path.
_NETWORK_SCHEMES = ("socket", "rfc2217", "esphome")
_MENU_OPTIONS = ["socket", "rfc2217", "esphome", "serial"]
_DEFAULT_PORT = 4999  # common TCP serial-gateway port (e.g. Global Cache iTach)
_DEFAULT_DEVICE = "/dev/ttyUSB0"


def _network_schema(host: str = "", port: int = _DEFAULT_PORT) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=host): str,
            vol.Required(CONF_PORT, default=port): int,
        }
    )


def _serial_schema(device: str = _DEFAULT_DEVICE, baudrate: int = DEFAULT_BAUDRATE) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_DEVICE, default=device): str,
            vol.Required(CONF_BAUDRATE, default=baudrate): int,
        }
    )


def _parse_url(url: str) -> tuple[str, str, int | None, str]:
    """Split a stored serialx URL into (kind, host, port, device).

    kind is one of the menu options. Network URLs yield host/port; anything
    without a known scheme is treated as a local serial device path.
    """
    for scheme in _NETWORK_SCHEMES:
        prefix = f"{scheme}://"
        if url.startswith(prefix):
            host, _, port = url[len(prefix):].partition(":")
            return scheme, host, (int(port) if port.isdigit() else None), ""
    return "serial", "", None, url


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
                for idx in sorted(SELECTABLE_SOURCES)
            },
            vol.Optional("hidden_sources", default=hidden): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": idx, "label": current_names[idx]}
                        for idx in sorted(SELECTABLE_SOURCES)
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
        """Pick a connection type, then collect its details in a sub-step."""
        return self.async_show_menu(step_id="user", menu_options=_MENU_OPTIONS)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-pick the connection type — e.g. to swap to a new gateway.

        The stable CONF_ID is preserved, so the device registry entry and all
        entity history survive moving between e.g. a TCP gateway and an esphome
        serial proxy.
        """
        return self.async_show_menu(step_id="reconfigure", menu_options=_MENU_OPTIONS)

    # ── Per-scheme connection steps (shared by add + reconfigure) ────────────

    async def async_step_socket(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_network_step("socket", user_input)

    async def async_step_rfc2217(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_network_step("rfc2217", user_input)

    async def async_step_esphome(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_network_step("esphome", user_input)

    async def _async_network_step(
        self, scheme: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host, port = user_input[CONF_HOST], user_input[CONF_PORT]
            url = f"{scheme}://{host}:{port}"
            result = await self._async_probe_and_finish(url, DEFAULT_BAUDRATE, errors)
            if result is not None:
                return result
        else:
            host, port = self._network_defaults(scheme)
        return self.async_show_form(
            step_id=scheme, data_schema=_network_schema(host, port), errors=errors
        )

    async def async_step_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            device, baudrate = user_input[CONF_DEVICE], user_input[CONF_BAUDRATE]
            result = await self._async_probe_and_finish(device, baudrate, errors)
            if result is not None:
                return result
        else:
            device, baudrate = self._serial_defaults()
        return self.async_show_form(
            step_id="serial", data_schema=_serial_schema(device, baudrate), errors=errors
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _reconfigure_entry(self) -> ConfigEntry | None:
        if self.source != SOURCE_RECONFIGURE:
            return None
        return self.hass.config_entries.async_get_entry(self.context["entry_id"])

    def _network_defaults(self, scheme: str) -> tuple[str, int]:
        if entry := self._reconfigure_entry():
            kind, host, port, _ = _parse_url(entry.data.get(CONF_URL, ""))
            if kind == scheme:
                return host, port or _DEFAULT_PORT
        return "", _DEFAULT_PORT

    def _serial_defaults(self) -> tuple[str, int]:
        if entry := self._reconfigure_entry():
            kind, _, _, device = _parse_url(entry.data.get(CONF_URL, ""))
            if kind == "serial":
                return device, entry.data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)
        return _DEFAULT_DEVICE, DEFAULT_BAUDRATE

    async def _async_probe_and_finish(
        self, url: str, baudrate: int, errors: dict[str, str]
    ) -> ConfigFlowResult | None:
        """Probe; on success create/update the entry, else fill `errors`."""
        try:
            model, sw_version = await _probe(url, baudrate)
        except (TimeoutError, OSError) as err:
            _LOGGER.debug("Probe of %s failed: %s: %s", url, type(err).__name__, err)
            errors["base"] = "cannot_connect"
            return None
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error probing %s", url)
            errors["base"] = "unknown"
            return None
        return await self._async_finish(url, baudrate, model, sw_version)

    async def _async_finish(
        self, url: str, baudrate: int, model: str, sw_version: str | None
    ) -> ConfigFlowResult:
        if entry := self._reconfigure_entry():
            new_data = {**entry.data, CONF_URL: url, CONF_BAUDRATE: baudrate, CONF_MODEL: model}
            if sw_version is not None:
                new_data[CONF_SW_VERSION] = sw_version
            self.hass.config_entries.async_update_entry(entry, title=model, data=new_data)
            await self.hass.config_entries.async_reload(entry.entry_id)
            return self.async_abort(reason="reconfigure_successful")

        # No hardware serial number is available from the Gen1 protocol, so the
        # device identity is an opaque random id stored in the entry. It stays
        # stable across reconfigure, keeping the device and its entities intact.
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


class AnthemSerialOptionsFlow(OptionsFlow):
    """Allow the user to rename inputs."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            # A zone whose min >= max would make the volume scaling divide by
            # zero (or invert) in the media_player, so reject it here.
            if any(
                user_input.get(f"zone{z}_vol_min", VOLUME_MIN)
                >= user_input.get(f"zone{z}_vol_max", VOLUME_MAX)
                for z in (1, 2, 3)
            ):
                errors["base"] = "vol_min_not_below_max"
            else:
                return self.async_create_entry(data=user_input)

        # On a validation re-show, prefill from the rejected input so the user's
        # edits survive; otherwise from saved options.
        prefill = user_input if user_input is not None else self.config_entry.options

        current_names = {
            idx: prefill.get(f"source_{idx}", default_name)
            for idx, default_name in SELECTABLE_SOURCES.items()
        }
        hidden = prefill.get("hidden_sources", [])

        if "time_format_24hr" in prefill:
            time_format_24hr: bool = prefill["time_format_24hr"]
        else:
            # Query the device for its current clock format setting.
            client = self.hass.data[DOMAIN][self.config_entry.entry_id]
            response = await client.query_one("STF?", "STF")
            time_format_24hr = response == "STF1" if response is not None else False
        vol_limits = {
            key: prefill.get(key, default)
            for key, default in [
                ("zone1_vol_min", VOLUME_MIN), ("zone1_vol_max", VOLUME_MAX),
                ("zone2_vol_min", VOLUME_MIN), ("zone2_vol_max", VOLUME_MAX),
                ("zone3_vol_min", VOLUME_MIN), ("zone3_vol_max", VOLUME_MAX),
            ]
        }

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(current_names, hidden, vol_limits, time_format_24hr),
            errors=errors,
        )
