"""Tests for the Anthem select platform."""
from __future__ import annotations

from homeassistant.helpers import entity_registry as er

from tests.conftest import MOCK_ID


def _eid(hass, unique_id: str) -> str:
    reg = er.async_get(hass)
    e = next((x for x in reg.entities.values() if x.unique_id == unique_id), None)
    assert e is not None, f"no entity with unique_id {unique_id!r}"
    return e.entity_id


async def _select(hass, eid: str, option: str) -> None:
    await hass.services.async_call(
        "select", "select_option", {"entity_id": eid, "option": option}, blocking=True
    )


async def test_select_entities_created(hass, setup_integration):
    reg = er.async_get(hass)
    uids = {e.unique_id for e in reg.entities.values() if e.domain == "select"}
    assert f"{MOCK_ID}_tuner_mode" in uids
    assert f"{MOCK_ID}_rec_source" in uids
    assert f"{MOCK_ID}_fp_brightness" in uids
    # Sleep timer is a remote command now, not a select.
    assert f"{MOCK_ID}_zone1_sleep" not in uids


# ── Tuner mode ───────────────────────────────────────────────────────────────────

async def test_tuner_mode_queries_on_add(hass, setup_integration):
    _, mock_client = setup_integration
    sent = [c.args[0] for c in mock_client.send.call_args_list if c.args]
    assert "TH?" in sent


async def test_tuner_mode_reflects_push(hass, setup_integration):
    on_message = setup_integration[1]._on_message
    on_message("TH2")
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, f"{MOCK_ID}_tuner_mode")).state == "Mono"


async def test_tuner_mode_select_sends_command(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    eid = _eid(hass, f"{MOCK_ID}_tuner_mode")
    await _select(hass, eid, "Hi-blend")
    mock_client.send.assert_called_once_with("TH1")
    assert hass.states.get(eid).state == "Hi-blend"


# ── Record output source ─────────────────────────────────────────────────────────

async def test_record_source_queries_on_add(hass, setup_integration):
    _, mock_client = setup_integration
    sent = [c.args[0] for c in mock_client.send.call_args_list if c.args]
    assert "P4S?" in sent


async def test_record_source_main_option(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client._on_message("P4S1")  # device reports -> entity becomes available
    await hass.async_block_till_done()
    mock_client.send.reset_mock()
    await _select(hass, _eid(hass, f"{MOCK_ID}_rec_source"), "Main")
    mock_client.send.assert_called_once_with("P4SM")


async def test_record_source_input_option(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client._on_message("P4S1")  # device reports -> entity becomes available
    await hass.async_block_till_done()
    mock_client.send.reset_mock()
    await _select(hass, _eid(hass, f"{MOCK_ID}_rec_source"), "CD")  # source 0
    mock_client.send.assert_called_once_with("P4S0")


async def test_record_source_reflects_push(hass, setup_integration):
    on_message = setup_integration[1]._on_message
    on_message("P4S5")  # DVD1
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, f"{MOCK_ID}_rec_source")).state == "DVD1"


async def test_record_source_unavailable_when_main_off(hass, setup_integration):
    """P4S? answers "Main Off" while main is off, so the select is unavailable."""
    on_message = setup_integration[1]._on_message
    on_message("P4S0")  # CD -> available first
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, f"{MOCK_ID}_rec_source")).state == "CD"

    on_message("Main Off")  # main powers off
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, f"{MOCK_ID}_rec_source")).state == "unavailable"


async def test_record_source_requeries_on_power_on(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client._on_message("Main Off")
    await hass.async_block_till_done()
    mock_client.send.reset_mock()

    mock_client._on_message("P1P1")  # main powers on -> re-query record source
    await hass.async_block_till_done()
    assert "P4S?" in [c.args[0] for c in mock_client.send.call_args_list if c.args]


# ── Front panel brightness (write-only, RestoreEntity) ───────────────────────────

async def test_brightness_select_sends_command(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await _select(hass, _eid(hass, f"{MOCK_ID}_fp_brightness"), "High")
    mock_client.send.assert_called_once_with("FP3")


async def test_brightness_restores_last_state(hass, config_entry, mock_client):
    """The write-only brightness comes up at its last value, not unknown."""
    from unittest.mock import AsyncMock, patch

    from homeassistant.core import State
    from pytest_homeassistant_custom_component.common import mock_restore_cache

    mock_restore_cache(hass, [State("select.avm_50v_front_panel_brightness", "Medium")])
    with (
        patch("custom_components.anthemav_serial.AnthemClient", return_value=mock_client),
        patch("custom_components.anthemav_serial.media_player.asyncio.sleep", AsyncMock()),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get("select.avm_50v_front_panel_brightness").state == "Medium"
