"""Tests for the remote platform."""
from __future__ import annotations

from unittest.mock import AsyncMock, call

import pytest

from custom_components.anthemav_serial.const import DOMAIN, ZONE_MAIN, ZONE_2, ZONE_3
from tests.conftest import ENTRY_DATA, MOCK_HOST, MOCK_PORT


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
