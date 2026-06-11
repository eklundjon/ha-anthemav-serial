"""Tests for the Anthem switch platform."""
from __future__ import annotations

from homeassistant.helpers import entity_registry as er

from custom_components.anthemav_serial.const import ZONE_2, ZONE_MAIN
from tests.conftest import MOCK_ID


def _entity_id(hass, unique_id: str) -> str:
    reg = er.async_get(hass)
    e = next((x for x in reg.entities.values() if x.unique_id == unique_id), None)
    assert e is not None, f"no entity with unique_id {unique_id!r}"
    return e.entity_id


def _tone_id(hass, zone: int) -> str:
    return _entity_id(hass, f"{MOCK_ID}_zone{zone}_tone")


def _lock_id(hass) -> str:
    return _entity_id(hass, f"{MOCK_ID}_panel_lock")


def _timers_id(hass) -> str:
    return _entity_id(hass, f"{MOCK_ID}_auto_timers")


async def test_switch_entities_created(hass, setup_integration):
    reg = er.async_get(hass)
    uids = {e.unique_id for e in reg.entities.values() if e.domain == "switch"}
    assert f"{MOCK_ID}_zone1_tone" in uids
    assert f"{MOCK_ID}_zone2_tone" in uids
    assert f"{MOCK_ID}_zone3_tone" in uids
    assert f"{MOCK_ID}_panel_lock" in uids
    assert f"{MOCK_ID}_auto_timers" in uids


# ── Tone controls ────────────────────────────────────────────────────────────────

async def test_tone_control_reflects_push(hass, setup_integration):
    on_message = setup_integration[1]._on_message
    on_message("P1TE1")  # enabled
    await hass.async_block_till_done()
    assert hass.states.get(_tone_id(hass, ZONE_MAIN)).state == "on"

    on_message("P1TE0")  # bypassed
    await hass.async_block_till_done()
    assert hass.states.get(_tone_id(hass, ZONE_MAIN)).state == "off"


async def test_tone_control_queries_state_on_add(hass, setup_integration):
    _, mock_client = setup_integration
    sent = [c.args[0] for c in mock_client.send.call_args_list]
    assert "P1TE?" in sent


async def test_tone_control_turn_on_sends_command(hass, setup_integration):
    _, mock_client = setup_integration
    await hass.async_block_till_done()
    mock_client.send.reset_mock()

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": _tone_id(hass, ZONE_2)}, blocking=True
    )
    mock_client.send.assert_called_once_with("P2TE1")
    assert hass.states.get(_tone_id(hass, ZONE_2)).state == "on"


# ── Panel lock ───────────────────────────────────────────────────────────────────

async def test_panel_lock_turn_on_off(hass, setup_integration):
    _, mock_client = setup_integration
    await hass.async_block_till_done()
    mock_client.send.reset_mock()

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": _lock_id(hass)}, blocking=True
    )
    mock_client.send.assert_called_once_with("FPL1")
    assert hass.states.get(_lock_id(hass)).state == "on"

    mock_client.send.reset_mock()
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": _lock_id(hass)}, blocking=True
    )
    mock_client.send.assert_called_once_with("FPL0")
    assert hass.states.get(_lock_id(hass)).state == "off"


async def test_panel_lock_resets_on_power_off(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": _lock_id(hass)}, blocking=True
    )
    assert hass.states.get(_lock_id(hass)).state == "on"

    on_message("Unit Off")  # unit power-off resets the front-panel lock
    await hass.async_block_till_done()
    assert hass.states.get(_lock_id(hass)).state == "off"


# ── Auto timers ──────────────────────────────────────────────────────────────────

async def test_auto_timers_reflects_push_and_command(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    on_message("STE1")
    await hass.async_block_till_done()
    assert hass.states.get(_timers_id(hass)).state == "on"

    mock_client.send.reset_mock()
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": _timers_id(hass)}, blocking=True
    )
    mock_client.send.assert_called_once_with("STE0")
