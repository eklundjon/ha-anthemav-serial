"""Tests for the remote platform."""
from __future__ import annotations

from unittest.mock import AsyncMock, call

import pytest

from custom_components.anthemav_serial.const import DOMAIN, ZONE_MAIN, ZONE_2, ZONE_3


def remote_entity_id(hass, zone: int) -> str:
    states = hass.states.async_all("remote")
    suffix = {ZONE_MAIN: "main", ZONE_2: "zone_2", ZONE_3: "zone_3"}[zone]
    for s in states:
        if s.entity_id.endswith(suffix):
            return s.entity_id
    raise AssertionError(f"No remote entity found for zone {zone}: {[s.entity_id for s in states]}")


# ── Setup ──────────────────────────────────────────────────────────────────────

async def test_remote_entities_created(hass, setup_integration):
    states = hass.states.async_all("remote")
    assert len(states) == 3


# ── Commands ───────────────────────────────────────────────────────────────────

async def test_volume_up_zone1(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await hass.services.async_call(
        "remote", "send_command",
        {"entity_id": remote_entity_id(hass, ZONE_MAIN), "command": ["volume_up"]},
        blocking=True,
    )
    mock_client.send.assert_called_once_with("P1VMU")


async def test_volume_up_zone2_uses_short_form(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await hass.services.async_call(
        "remote", "send_command",
        {"entity_id": remote_entity_id(hass, ZONE_2), "command": ["volume_up"]},
        blocking=True,
    )
    mock_client.send.assert_called_once_with("P2VU")


async def test_volume_down_zone1(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await hass.services.async_call(
        "remote", "send_command",
        {"entity_id": remote_entity_id(hass, ZONE_MAIN), "command": ["volume_down"]},
        blocking=True,
    )
    mock_client.send.assert_called_once_with("P1VMD")


async def test_mute_toggle(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await hass.services.async_call(
        "remote", "send_command",
        {"entity_id": remote_entity_id(hass, ZONE_MAIN), "command": ["mute_toggle"]},
        blocking=True,
    )
    mock_client.send.assert_called_once_with("P1MT")


async def test_source_seek_up(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await hass.services.async_call(
        "remote", "send_command",
        {"entity_id": remote_entity_id(hass, ZONE_MAIN), "command": ["source_seek_up"]},
        blocking=True,
    )
    mock_client.send.assert_called_once_with("P1SS+")


async def test_source_seek_down(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await hass.services.async_call(
        "remote", "send_command",
        {"entity_id": remote_entity_id(hass, ZONE_MAIN), "command": ["source_seek_down"]},
        blocking=True,
    )
    mock_client.send.assert_called_once_with("P1SS-")


async def test_source_by_key(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await hass.services.async_call(
        "remote", "send_command",
        {"entity_id": remote_entity_id(hass, ZONE_MAIN), "command": ["source_5"]},
        blocking=True,
    )
    mock_client.send.assert_called_once_with("P1S5")


async def test_num_repeats(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await hass.services.async_call(
        "remote", "send_command",
        {"entity_id": remote_entity_id(hass, ZONE_MAIN), "command": ["volume_up"], "num_repeats": 3},
        blocking=True,
    )
    assert mock_client.send.call_count == 3
    mock_client.send.assert_called_with("P1VMU")


async def test_unknown_command_logs_warning(hass, setup_integration, caplog):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    import logging
    with caplog.at_level(logging.WARNING):
        await hass.services.async_call(
            "remote", "send_command",
            {"entity_id": remote_entity_id(hass, ZONE_MAIN), "command": ["not_a_command"]},
            blocking=True,
        )
    mock_client.send.assert_not_called()
    assert "unknown command" in caplog.text.lower()


async def test_turn_on_sends_power_on(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await hass.services.async_call(
        "remote", "turn_on",
        {"entity_id": remote_entity_id(hass, ZONE_MAIN)},
        blocking=True,
    )
    mock_client.send.assert_called_once_with("P1P1")


async def test_turn_off_sends_power_off(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await hass.services.async_call(
        "remote", "turn_off",
        {"entity_id": remote_entity_id(hass, ZONE_MAIN)},
        blocking=True,
    )
    mock_client.send.assert_called_once_with("P1P0")


# ── Power state tracking (toggle reflects real zone power) ───────────────────────

async def test_remote_queries_power_on_add(hass, setup_integration):
    _, mock_client = setup_integration
    sent = [c.args[0] for c in mock_client.send.call_args_list if c.args]
    assert "P1P?" in sent


async def test_remote_reflects_power_push(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client._on_message("P1P1")
    await hass.async_block_till_done()
    assert hass.states.get(remote_entity_id(hass, ZONE_MAIN)).state == "on"

    mock_client._on_message("P1P0")
    await hass.async_block_till_done()
    assert hass.states.get(remote_entity_id(hass, ZONE_MAIN)).state == "off"


async def test_remote_reflects_zone_off_text(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client._on_message("P1P1")
    await hass.async_block_till_done()
    assert hass.states.get(remote_entity_id(hass, ZONE_MAIN)).state == "on"

    mock_client._on_message("Main Off")  # device's zone-off text, not P1P0
    await hass.async_block_till_done()
    assert hass.states.get(remote_entity_id(hass, ZONE_MAIN)).state == "off"


async def test_remote_reflects_unit_off(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client._on_message("P2P1")
    await hass.async_block_till_done()
    assert hass.states.get(remote_entity_id(hass, ZONE_2)).state == "on"

    mock_client._on_message("Unit Off")  # whole unit off -> every zone off
    await hass.async_block_till_done()
    assert hass.states.get(remote_entity_id(hass, ZONE_2)).state == "off"


# ── Tone controls (bypass / enable) ──────────────────────────────────────────────

async def test_bypass_command_zone2(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await hass.services.async_call(
        "remote", "send_command",
        {"entity_id": remote_entity_id(hass, ZONE_2), "command": ["bypass"]},
        blocking=True,
    )
    mock_client.send.assert_called_once_with("P2TE0")  # tone bypassed


async def test_enable_command_zone3(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await hass.services.async_call(
        "remote", "send_command",
        {"entity_id": remote_entity_id(hass, ZONE_3), "command": ["enable"]},
        blocking=True,
    )
    mock_client.send.assert_called_once_with("P3TE1")  # tone enabled


async def test_bypass_enable_on_main_remote(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await hass.services.async_call(
        "remote", "send_command",
        {"entity_id": remote_entity_id(hass, ZONE_MAIN), "command": ["bypass", "enable"]},
        blocking=True,
    )
    assert [c.args[0] for c in mock_client.send.call_args_list] == ["P1TE0", "P1TE1"]


# ── Sleep timer commands ─────────────────────────────────────────────────────────

async def test_sleep_30_command_zone1(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await hass.services.async_call(
        "remote", "send_command",
        {"entity_id": remote_entity_id(hass, ZONE_MAIN), "command": ["sleep_30"]},
        blocking=True,
    )
    mock_client.send.assert_called_once_with("P1Z1")  # 30 min


async def test_sleep_off_command_zone2(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await hass.services.async_call(
        "remote", "send_command",
        {"entity_id": remote_entity_id(hass, ZONE_2), "command": ["sleep_off"]},
        blocking=True,
    )
    mock_client.send.assert_called_once_with("P2Z0")


async def test_sleep_90_command_zone3(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client.send.reset_mock()
    await hass.services.async_call(
        "remote", "send_command",
        {"entity_id": remote_entity_id(hass, ZONE_3), "command": ["sleep_90"]},
        blocking=True,
    )
    mock_client.send.assert_called_once_with("P3Z3")  # 90 min
