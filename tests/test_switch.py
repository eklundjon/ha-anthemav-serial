"""Tests for the Anthem switch platform."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.anthemav_serial.const import DOMAIN, ZONE_2, ZONE_MAIN
from tests.conftest import ENTRY_DATA, MOCK_ID, MOCK_MODEL


async def _setup_with_options(hass, mock_client, options):
    entry = MockConfigEntry(
        domain=DOMAIN, title=MOCK_MODEL, data=ENTRY_DATA,
        options=options, unique_id=MOCK_ID, version=2,
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.anthemav_serial.AnthemClient", return_value=mock_client),
        patch("custom_components.anthemav_serial.media_player.asyncio.sleep", AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


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


# ── Triggers (opt-in) ────────────────────────────────────────────────────────────

def _trigger_id(hass, num: int) -> str:
    return _entity_id(hass, f"{MOCK_ID}_trigger{num}")


async def test_no_trigger_switches_by_default(hass, setup_integration):
    reg = er.async_get(hass)
    uids = {e.unique_id for e in reg.entities.values() if e.domain == "switch"}
    assert f"{MOCK_ID}_trigger1" not in uids


async def test_trigger_switches_created_when_enabled(hass, mock_client):
    await _setup_with_options(hass, mock_client, {"trigger_control": True})
    reg = er.async_get(hass)
    uids = {e.unique_id for e in reg.entities.values() if e.domain == "switch"}
    assert {f"{MOCK_ID}_trigger1", f"{MOCK_ID}_trigger2", f"{MOCK_ID}_trigger3"} <= uids


async def test_trigger_turn_on_asserts_mode_and_sets(hass, mock_client):
    await _setup_with_options(hass, mock_client, {"trigger_control": True})
    mock_client.send.reset_mock()
    tid = _trigger_id(hass, 1)
    await hass.services.async_call("switch", "turn_on", {"entity_id": tid}, blocking=True)
    mock_client.send.assert_called_once_with("StE2;t1T1")
    assert hass.states.get(tid).state == "on"
    assert hass.states.get(tid).attributes.get("assumed_state") is True


async def test_trigger_turn_off_sends_command(hass, mock_client):
    await _setup_with_options(hass, mock_client, {"trigger_control": True})
    tid = _trigger_id(hass, 3)
    await hass.services.async_call("switch", "turn_on", {"entity_id": tid}, blocking=True)
    mock_client.send.reset_mock()
    await hass.services.async_call("switch", "turn_off", {"entity_id": tid}, blocking=True)
    mock_client.send.assert_called_once_with("StE2;t3T0")


async def test_trigger_reapplied_on_power_on_when_on(hass, mock_client):
    await _setup_with_options(hass, mock_client, {"trigger_control": True})
    tid = _trigger_id(hass, 2)
    await hass.services.async_call("switch", "turn_on", {"entity_id": tid}, blocking=True)
    mock_client.send.reset_mock()

    mock_client._on_message("P1P1")  # main power-on
    await hass.async_block_till_done()
    sent = [c.args[0] for c in mock_client.send.call_args_list if c.args]
    assert "StE2;t2T1" in sent


async def test_trigger_not_reapplied_when_off(hass, mock_client):
    await _setup_with_options(hass, mock_client, {"trigger_control": True})
    mock_client.send.reset_mock()
    mock_client._on_message("P1P1")
    await hass.async_block_till_done()
    sent = [c.args[0] for c in mock_client.send.call_args_list if c.args]
    assert not any("t1T" in s or "t2T" in s or "t3T" in s for s in sent)
