"""Tests for the Anthem number platform (headphone dB controls)."""
from __future__ import annotations

from homeassistant.helpers import entity_registry as er

from tests.conftest import MOCK_ID


def _eid(hass, unique_id: str) -> str:
    reg = er.async_get(hass)
    e = next((x for x in reg.entities.values() if x.unique_id == unique_id), None)
    assert e is not None, f"no entity with unique_id {unique_id!r}"
    return e.entity_id


async def _set(hass, eid: str, value: float) -> None:
    await hass.services.async_call(
        "number", "set_value", {"entity_id": eid, "value": value}, blocking=True
    )


async def test_number_entities_created(hass, setup_integration):
    reg = er.async_get(hass)
    uids = {e.unique_id for e in reg.entities.values() if e.domain == "number"}
    assert {
        f"{MOCK_ID}_hp_volume",
        f"{MOCK_ID}_hp_bass",
        f"{MOCK_ID}_hp_treble",
        f"{MOCK_ID}_hp_balance",
    } <= uids


async def test_headphone_numbers_query_on_add(hass, setup_integration):
    _, mock_client = setup_integration
    sent = [c.args[0] for c in mock_client.send.call_args_list if c.args]
    assert {"HV?", "HB?", "HT?", "HL?"} <= set(sent)


# ── Volume ───────────────────────────────────────────────────────────────────────

async def test_volume_reflects_push(hass, setup_integration):
    on_message = setup_integration[1]._on_message
    on_message("HV-35.0")
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, f"{MOCK_ID}_hp_volume")).state == "-35.0"


async def test_volume_reflects_combined_status(hass, setup_integration):
    """The combined HSuVvMw status carries the volume too."""
    on_message = setup_integration[1]._on_message
    on_message("HS7V-20.0M0")
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, f"{MOCK_ID}_hp_volume")).state == "-20.0"


async def test_volume_set_sends_command(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await _set(hass, _eid(hass, f"{MOCK_ID}_hp_volume"), 0.0)
    mock_client.send.assert_called_once_with("HV+0.00")


# ── Tone / balance ────────────────────────────────────────────────────────────────

async def test_bass_set_sends_command(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await _set(hass, _eid(hass, f"{MOCK_ID}_hp_bass"), 6.0)
    mock_client.send.assert_called_once_with("HB+6.00")


async def test_treble_reflects_push(hass, setup_integration):
    on_message = setup_integration[1]._on_message
    on_message("HT-4.0")
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, f"{MOCK_ID}_hp_treble")).state == "-4.0"


async def test_balance_set_rounds_to_step(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await _set(hass, _eid(hass, f"{MOCK_ID}_hp_balance"), 2.5)
    mock_client.send.assert_called_once_with("HL+2.50")


async def test_headphone_numbers_available_with_main_off(hass, setup_integration):
    """The headphone output is independent of zone power — never unavailable."""
    on_message = setup_integration[1]._on_message
    on_message("HV-35.0")
    on_message("Main Off")
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, f"{MOCK_ID}_hp_volume")).state == "-35.0"


# ── Per-zone tone trims (bass / treble / balance) ────────────────────────────────

async def test_zone_trim_entities_created(hass, setup_integration):
    reg = er.async_get(hass)
    uids = {e.unique_id for e in reg.entities.values() if e.domain == "number"}
    assert {
        # master tone
        f"{MOCK_ID}_zone1_bass", f"{MOCK_ID}_zone1_treble", f"{MOCK_ID}_zone1_balance",
        # per-channel level (the remote LEVEL buttons)
        f"{MOCK_ID}_zone1_level_front", f"{MOCK_ID}_zone1_level_center",
        f"{MOCK_ID}_zone1_level_surround", f"{MOCK_ID}_zone1_level_back",
        f"{MOCK_ID}_zone1_level_sub", f"{MOCK_ID}_zone1_level_lfe",
        # per-channel tone (disabled by default, still registered)
        f"{MOCK_ID}_zone1_bass_front", f"{MOCK_ID}_zone1_treble_surround",
        f"{MOCK_ID}_zone1_balance_back",
        # zones 2/3
        f"{MOCK_ID}_zone2_bass", f"{MOCK_ID}_zone2_treble", f"{MOCK_ID}_zone2_balance",
        f"{MOCK_ID}_zone3_bass", f"{MOCK_ID}_zone3_treble", f"{MOCK_ID}_zone3_balance",
    } <= uids


async def test_per_channel_tone_trims_disabled_by_default(hass, config_entry, mock_client):
    """Master + level trims ship enabled; per-channel bass/treble/balance off."""
    from unittest.mock import AsyncMock, patch

    with (
        patch("custom_components.anthemav_serial.AnthemClient", return_value=mock_client),
        patch("custom_components.anthemav_serial.media_player.asyncio.sleep", AsyncMock()),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    by_uid = {e.unique_id: e for e in er.async_get(hass).entities.values()}
    assert by_uid[f"{MOCK_ID}_zone1_bass_front"].disabled_by is not None      # per-channel
    assert by_uid[f"{MOCK_ID}_zone1_level_front"].disabled_by is None         # level (enabled)
    assert by_uid[f"{MOCK_ID}_zone1_bass"].disabled_by is None                # master (enabled)


async def test_main_level_set_sends_command(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client._on_message("P1VF+0.0")  # front level reports -> available
    await hass.async_block_till_done()
    mock_client.send.reset_mock()
    await _set(hass, _eid(hass, f"{MOCK_ID}_zone1_level_front"), -3.0)
    mock_client.send.assert_called_once_with("P1VF-3.00")


async def test_main_level_reflects_no_signal_space(hass, setup_integration):
    """No-signal reply has a space ('P1VF +0.0'); the regex tolerates it."""
    on_message = setup_integration[1]._on_message
    on_message("P1VF +0.0")
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, f"{MOCK_ID}_zone1_level_front")).state == "0.0"


async def test_zone_trims_query_on_add(hass, setup_integration):
    _, mock_client = setup_integration
    sent = [c.args[0] for c in mock_client.send.call_args_list if c.args]
    assert {"P1BM?", "P1TM?", "P1LM?", "P2B?", "P2T?", "P2L?", "P3B?", "P3T?", "P3L?"} <= set(sent)


async def test_main_bass_reflects_push(hass, setup_integration):
    on_message = setup_integration[1]._on_message
    on_message("P1BM-6.0")
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, f"{MOCK_ID}_zone1_bass")).state == "-6.0"


async def test_main_bass_set_sends_command(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client._on_message("P1BM+0.0")  # available first
    await hass.async_block_till_done()
    mock_client.send.reset_mock()
    await _set(hass, _eid(hass, f"{MOCK_ID}_zone1_bass"), 6.0)
    mock_client.send.assert_called_once_with("P1BM+6.00")


async def test_zone2_balance_set_rounds_to_step(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client._on_message("P2L+0.0")  # available first
    await hass.async_block_till_done()
    mock_client.send.reset_mock()
    await _set(hass, _eid(hass, f"{MOCK_ID}_zone2_balance"), 2.5)
    mock_client.send.assert_called_once_with("P2L+2.50")


async def test_zone_trim_unavailable_when_zone_off(hass, setup_integration):
    on_message = setup_integration[1]._on_message
    on_message("P2T+4.0")  # Zone 2 reports -> available
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, f"{MOCK_ID}_zone2_treble")).state == "4.0"

    on_message("Zone2 Off")  # Zone 2 powers off
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, f"{MOCK_ID}_zone2_treble")).state == "unavailable"


async def test_zone_trim_requeries_on_power_on(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client._on_message("Main Off")
    await hass.async_block_till_done()
    mock_client.send.reset_mock()

    mock_client._on_message("P1P1")  # main powers on -> re-query trims
    await hass.async_block_till_done()
    sent = [c.args[0] for c in mock_client.send.call_args_list if c.args]
    assert "P1BM?" in sent
