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
    assert {f"{MOCK_ID}_zone{z}_sleep" for z in (1, 2, 3)} <= uids


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
    mock_client.send.reset_mock()
    await _select(hass, _eid(hass, f"{MOCK_ID}_rec_source"), "Main")
    mock_client.send.assert_called_once_with("P4SM")


async def test_record_source_input_option(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await _select(hass, _eid(hass, f"{MOCK_ID}_rec_source"), "CD")  # source 0
    mock_client.send.assert_called_once_with("P4S0")


async def test_record_source_reflects_push(hass, setup_integration):
    on_message = setup_integration[1]._on_message
    on_message("P4S5")  # DVD1
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, f"{MOCK_ID}_rec_source")).state == "DVD1"


# ── Sleep timer ──────────────────────────────────────────────────────────────────

async def test_sleep_timer_select_sends_command(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await _select(hass, _eid(hass, f"{MOCK_ID}_zone1_sleep"), "60 min")
    mock_client.send.assert_called_once_with("P1Z2")


async def test_sleep_timer_reflects_push(hass, setup_integration):
    on_message = setup_integration[1]._on_message
    on_message("P2Z1")  # 30 min
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, f"{MOCK_ID}_zone2_sleep")).state == "30 min"


# ── Front panel brightness ───────────────────────────────────────────────────────

async def test_brightness_select_sends_command(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await _select(hass, _eid(hass, f"{MOCK_ID}_fp_brightness"), "High")
    mock_client.send.assert_called_once_with("FP3")
