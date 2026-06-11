"""Tests for config flow and options flow."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.data_entry_flow import FlowResultType

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.anthemav_serial.const import (
    DEFAULT_BAUDRATE,
    DOMAIN,
    VOLUME_MAX,
    VOLUME_MIN,
)
from tests.conftest import (
    ENTRY_DATA,
    MOCK_BAUDRATE,
    MOCK_HOST,
    MOCK_ID,
    MOCK_IDENTITY,
    MOCK_MODEL,
    MOCK_PORT,
    MOCK_SW_VERSION,
    MOCK_URL,
)


# ── Config flow (user step) ────────────────────────────────────────────────────

def _probe_client(identity=MOCK_IDENTITY, start_error=None):
    client = MagicMock()
    client.start = AsyncMock(side_effect=start_error)
    client.stop = AsyncMock()
    client.query_one = AsyncMock(return_value=identity)
    return client


def _patch_client(client):
    return patch(
        "custom_components.anthemav_serial.config_flow.AnthemClient", return_value=client
    )


async def _pick(hass, flow_id, step):
    return await hass.config_entries.flow.async_configure(flow_id, {"next_step_id": step})


async def _add_via(hass, step, fields, client):
    """Drive an add: init -> menu -> pick `step` -> submit `fields`."""
    with _patch_client(client):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await _pick(hass, result["flow_id"], step)
        return await hass.config_entries.flow.async_configure(result["flow_id"], fields)


async def test_user_step_shows_menu(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == FlowResultType.MENU
    assert result["step_id"] == "user"
    assert set(result["menu_options"]) == {"socket", "rfc2217", "esphome", "serial"}


async def test_socket_step_creates_entry(hass):
    result = await _add_via(hass, "socket", {"host": MOCK_HOST, "port": MOCK_PORT}, _probe_client())
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == MOCK_MODEL
    assert result["data"]["url"] == MOCK_URL  # socket://MOCK_HOST:MOCK_PORT
    assert result["data"]["baudrate"] == DEFAULT_BAUDRATE
    assert result["data"]["model"] == MOCK_MODEL
    assert result["data"]["sw_version"] == MOCK_SW_VERSION
    assert result["data"]["id"]
    assert result["result"].unique_id == result["data"]["id"]


async def test_socket_step_falls_back_to_default_name(hass):
    from custom_components.anthemav_serial.const import DEFAULT_NAME

    result = await _add_via(
        hass, "socket", {"host": MOCK_HOST, "port": MOCK_PORT}, _probe_client(identity=None)
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["model"] == DEFAULT_NAME
    assert "sw_version" not in result["data"]


@pytest.mark.parametrize(
    "error, expected",
    [
        (OSError, "cannot_connect"),
        (TimeoutError, "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_socket_step_connection_errors(hass, error, expected):
    result = await _add_via(
        hass, "socket", {"host": MOCK_HOST, "port": MOCK_PORT}, _probe_client(start_error=error)
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "socket"
    assert result["errors"] == {"base": expected}


async def test_rfc2217_step_builds_url(hass):
    result = await _add_via(hass, "rfc2217", {"host": "gw.local", "port": 5000}, _probe_client())
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["url"] == "rfc2217://gw.local:5000"


async def test_serial_step_uses_device_path_as_url(hass):
    result = await _add_via(
        hass, "serial", {"device": "/dev/ttyUSB0", "baudrate": 9600}, _probe_client()
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["url"] == "/dev/ttyUSB0"
    assert result["data"]["baudrate"] == 9600


async def test_user_step_allows_multiple_entries(hass, config_entry):
    """No hardware serial number exists, so the id is random per flow run."""
    result = await _add_via(hass, "socket", {"host": MOCK_HOST, "port": MOCK_PORT}, _probe_client())
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["id"] != config_entry.unique_id


def test_parse_url_splits_known_schemes():
    from custom_components.anthemav_serial.config_flow import _parse_url

    assert _parse_url("socket://1.2.3.4:9999") == ("socket", "1.2.3.4", 9999, "")
    assert _parse_url("rfc2217://gw:5") == ("rfc2217", "gw", 5, "")
    assert _parse_url("esphome://host:6053") == ("esphome", "host", 6053, "")
    assert _parse_url("/dev/ttyUSB0") == ("serial", "", None, "/dev/ttyUSB0")


# ── Config flow: reconfigure (swap gateway) ──────────────────────────────────────

async def test_reconfigure_shows_menu(hass, config_entry):
    result = await config_entry.start_reconfigure_flow(hass)
    assert result["type"] == FlowResultType.MENU
    assert result["step_id"] == "reconfigure"


async def test_reconfigure_swaps_connection_type(hass, config_entry):
    """Reconfiguring to a different type rewrites the URL but keeps the id."""
    with _patch_client(_probe_client()), patch(
        "homeassistant.config_entries.ConfigEntries.async_reload", AsyncMock(return_value=True)
    ):
        result = await config_entry.start_reconfigure_flow(hass)
        result = await _pick(hass, result["flow_id"], "serial")
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"device": "/dev/ttyUSB1", "baudrate": 9600}
        )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data["url"] == "/dev/ttyUSB1"
    assert config_entry.data["id"] == MOCK_ID  # stable id preserved


# ── Options flow ───────────────────────────────────────────────────────────────

async def test_options_flow_shows_form(hass, setup_integration):
    config_entry, mock_client = setup_integration
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"


async def test_options_flow_saves_source_names(hass, setup_integration):
    config_entry, mock_client = setup_integration
    await hass.config_entries.options.async_init(config_entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        hass.config_entries.options.async_progress()[0]["flow_id"],
        user_input={
            "source_0": "Blu-ray",
            "source_1": "2-Ch BAL",
            "source_2": "6-Ch SE",
            "source_3": "Tape",
            "source_4": "Tuner",
            "source_5": "DVD1",
            "source_6": "TV1",
            "source_7": "SAT1",
            "source_8": "VCR",
            "source_9": "AUX",
            "source_d": "DVD2",
            "source_e": "DVD3",
            "source_f": "DVD4",
            "source_g": "TV2",
            "source_h": "TV3",
            "source_i": "TV4",
            "source_j": "SAT2",
            "hidden_sources": [],
            "zone1_vol_min": VOLUME_MIN,
            "zone1_vol_max": VOLUME_MAX,
            "zone2_vol_min": VOLUME_MIN,
            "zone2_vol_max": VOLUME_MAX,
            "zone3_vol_min": VOLUME_MIN,
            "zone3_vol_max": VOLUME_MAX,
            "time_format_24hr": False,
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert config_entry.options["source_0"] == "Blu-ray"


async def test_options_flow_saves_hidden_sources(hass, setup_integration):
    config_entry, mock_client = setup_integration
    await hass.config_entries.options.async_init(config_entry.entry_id)

    user_input = {
        f"source_{k}": v
        for k, v in [
            ("0", "CD"), ("1", "2-Ch BAL"), ("2", "6-Ch SE"), ("3", "Tape"),
            ("4", "Tuner"), ("5", "DVD1"), ("6", "TV1"), ("7", "SAT1"),
            ("8", "VCR"), ("9", "AUX"), ("d", "DVD2"),
            ("e", "DVD3"), ("f", "DVD4"), ("g", "TV2"), ("h", "TV3"),
            ("i", "TV4"), ("j", "SAT2"),
        ]
    }
    user_input["hidden_sources"] = ["3", "8"]
    user_input["zone1_vol_min"] = VOLUME_MIN
    user_input["zone1_vol_max"] = VOLUME_MAX
    user_input["zone2_vol_min"] = VOLUME_MIN
    user_input["zone2_vol_max"] = VOLUME_MAX
    user_input["zone3_vol_min"] = VOLUME_MIN
    user_input["zone3_vol_max"] = VOLUME_MAX
    user_input["time_format_24hr"] = False

    result = await hass.config_entries.options.async_configure(
        hass.config_entries.options.async_progress()[0]["flow_id"],
        user_input=user_input,
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert config_entry.options["hidden_sources"] == ["3", "8"]


async def test_options_flow_saves_vol_limits(hass, setup_integration):
    config_entry, mock_client = setup_integration
    await hass.config_entries.options.async_init(config_entry.entry_id)

    user_input = {
        f"source_{k}": v
        for k, v in [
            ("0", "CD"), ("1", "2-Ch BAL"), ("2", "6-Ch SE"), ("3", "Tape"),
            ("4", "Tuner"), ("5", "DVD1"), ("6", "TV1"), ("7", "SAT1"),
            ("8", "VCR"), ("9", "AUX"), ("d", "DVD2"),
            ("e", "DVD3"), ("f", "DVD4"), ("g", "TV2"), ("h", "TV3"),
            ("i", "TV4"), ("j", "SAT2"),
        ]
    }
    user_input["hidden_sources"] = []
    user_input["zone1_vol_min"] = -70.0
    user_input["zone1_vol_max"] = 0.0
    user_input["zone2_vol_min"] = VOLUME_MIN
    user_input["zone2_vol_max"] = VOLUME_MAX
    user_input["zone3_vol_min"] = VOLUME_MIN
    user_input["zone3_vol_max"] = VOLUME_MAX
    user_input["time_format_24hr"] = False

    result = await hass.config_entries.options.async_configure(
        hass.config_entries.options.async_progress()[0]["flow_id"],
        user_input=user_input,
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert config_entry.options["zone1_vol_min"] == -70.0
    assert config_entry.options["zone1_vol_max"] == 0.0


async def test_options_flow_rejects_inverted_vol_limits(hass, setup_integration):
    """A zone whose min >= max is rejected with a form error, not saved."""
    config_entry, mock_client = setup_integration
    await hass.config_entries.options.async_init(config_entry.entry_id)

    user_input = {
        f"source_{k}": v
        for k, v in [
            ("0", "CD"), ("1", "2-Ch BAL"), ("2", "6-Ch SE"), ("3", "Tape"),
            ("4", "Tuner"), ("5", "DVD1"), ("6", "TV1"), ("7", "SAT1"),
            ("8", "VCR"), ("9", "AUX"), ("d", "DVD2"),
            ("e", "DVD3"), ("f", "DVD4"), ("g", "TV2"), ("h", "TV3"),
            ("i", "TV4"), ("j", "SAT2"),
        ]
    }
    user_input["hidden_sources"] = []
    user_input["zone1_vol_min"] = 0.0    # min >= max → invalid
    user_input["zone1_vol_max"] = -10.0
    user_input["zone2_vol_min"] = VOLUME_MIN
    user_input["zone2_vol_max"] = VOLUME_MAX
    user_input["zone3_vol_min"] = VOLUME_MIN
    user_input["zone3_vol_max"] = VOLUME_MAX
    user_input["time_format_24hr"] = False

    result = await hass.config_entries.options.async_configure(
        hass.config_entries.options.async_progress()[0]["flow_id"],
        user_input=user_input,
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "vol_min_not_below_max"}
    assert "zone1_vol_min" not in config_entry.options


async def test_options_flow_queries_device_for_time_format_on_first_open(
    hass, setup_integration
):
    """When time_format_24hr is not in options, the flow should call query_one."""
    config_entry, mock_client = setup_integration
    mock_client.query_one = AsyncMock(return_value="STF1")

    await hass.config_entries.options.async_init(config_entry.entry_id)

    mock_client.query_one.assert_called_once_with("STF?", "STF")


async def test_options_flow_falls_back_to_12hr_on_query_timeout(
    hass, setup_integration
):
    config_entry, mock_client = setup_integration
    mock_client.query_one = AsyncMock(return_value=None)

    await hass.config_entries.options.async_init(config_entry.entry_id)
    mock_client.query_one.assert_called_once_with("STF?", "STF")

    # Complete the flow without specifying time_format_24hr so voluptuous
    # fills in the schema default, then verify it was saved as False (12hr).
    flow_id = hass.config_entries.options.async_progress()[0]["flow_id"]
    result = await hass.config_entries.options.async_configure(
        flow_id,
        user_input={
            **{f"source_{k}": v for k, v in [
                ("0", "CD"), ("1", "2-Ch BAL"), ("2", "6-Ch SE"), ("3", "Tape"),
                ("4", "Tuner"), ("5", "DVD1"), ("6", "TV1"), ("7", "SAT1"),
                ("8", "VCR"), ("9", "AUX"), ("d", "DVD2"),
                ("e", "DVD3"), ("f", "DVD4"), ("g", "TV2"), ("h", "TV3"),
                ("i", "TV4"), ("j", "SAT2"),
            ]},
            "hidden_sources": [],
            "zone1_vol_min": VOLUME_MIN, "zone1_vol_max": VOLUME_MAX,
            "zone2_vol_min": VOLUME_MIN, "zone2_vol_max": VOLUME_MAX,
            "zone3_vol_min": VOLUME_MIN, "zone3_vol_max": VOLUME_MAX,
            # time_format_24hr intentionally absent — schema default applies.
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert config_entry.options["time_format_24hr"] is False


async def test_options_flow_uses_stored_time_format_without_querying(
    hass, mock_client
):
    """If time_format_24hr is already in options, device must not be queried."""
    from unittest.mock import patch

    entry = MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_MODEL,
        data=ENTRY_DATA,
        options={"time_format_24hr": True},
        unique_id=MOCK_ID,
        version=2,
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.anthemav_serial.AnthemClient", return_value=mock_client),
        patch("custom_components.anthemav_serial.media_player.asyncio.sleep", AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    await hass.config_entries.options.async_init(entry.entry_id)
    mock_client.query_one.assert_not_called()


# ── Reconfigure flow ───────────────────────────────────────────────────────────

async def test_reconfigure_to_same_scheme_prefills_host(hass, config_entry):
    """Picking the current scheme on reconfigure pre-fills its host/port, and a
    successful submit updates the URL while preserving the stable id."""
    original_id = config_entry.data["id"]
    original_unique_id = config_entry.unique_id

    with _patch_client(_probe_client()), patch(
        "homeassistant.config_entries.ConfigEntries.async_reload", AsyncMock(return_value=True)
    ):
        result = await config_entry.start_reconfigure_flow(hass)
        result = await _pick(hass, result["flow_id"], "socket")
        assert result["type"] == FlowResultType.FORM
        # Pre-filled from the current socket URL.
        defaults = {m.schema: m.default() for m in result["data_schema"].schema}
        assert defaults["host"] == MOCK_HOST
        assert defaults["port"] == MOCK_PORT

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "10.0.0.5", "port": 5000}
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data["url"] == "socket://10.0.0.5:5000"
    assert config_entry.data["id"] == original_id
    assert config_entry.unique_id == original_unique_id


async def test_reconfigure_connection_error_keeps_entry(hass, config_entry):
    """A failed probe during reconfigure re-shows the form and leaves the entry."""
    with _patch_client(_probe_client(start_error=OSError)):
        result = await config_entry.start_reconfigure_flow(hass)
        result = await _pick(hass, result["flow_id"], "socket")
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "bad", "port": 1}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "socket"
    assert result["errors"] == {"base": "cannot_connect"}
    assert config_entry.data["url"] == MOCK_URL  # untouched on failure


# ── v1 → v2 migration ──────────────────────────────────────────────────────────

async def test_migrate_v1_entry_to_v2(hass, mock_client):
    """A legacy host/port entry migrates to url/baudrate, reusing host:port
    as the stable id so existing entities keep their unique_ids."""
    v1_entry = MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_MODEL,
        data={
            "host": MOCK_HOST,
            "port": MOCK_PORT,
            "model": MOCK_MODEL,
            "sw_version": MOCK_SW_VERSION,
        },
        options={},
        unique_id=f"{MOCK_HOST}:{MOCK_PORT}",
        version=1,
    )
    v1_entry.add_to_hass(hass)

    with (
        patch("custom_components.anthemav_serial.AnthemClient", return_value=mock_client),
        patch("custom_components.anthemav_serial.media_player.asyncio.sleep", AsyncMock()),
    ):
        await hass.config_entries.async_setup(v1_entry.entry_id)
        await hass.async_block_till_done()

    assert v1_entry.version == 2
    assert v1_entry.data["id"] == f"{MOCK_HOST}:{MOCK_PORT}"
    assert v1_entry.data["url"] == f"socket://{MOCK_HOST}:{MOCK_PORT}"
    assert v1_entry.data["baudrate"] == 9600
    assert "host" not in v1_entry.data and "port" not in v1_entry.data
    assert v1_entry.unique_id == f"{MOCK_HOST}:{MOCK_PORT}"
