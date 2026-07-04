"""Tests for __init__.py: setup, unload, and sync_time service."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.anthemav_serial.const import DOMAIN

# ── Setup / unload ─────────────────────────────────────────────────────────────

async def test_setup_entry_starts_client_and_stores_in_hass(
    hass, config_entry, mock_client
):
    with (
        patch("custom_components.anthemav_serial.AnthemClient", return_value=mock_client),
        patch("custom_components.anthemav_serial.media_player.asyncio.sleep", AsyncMock()),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    mock_client.start.assert_called_once()
    assert hass.data[DOMAIN][config_entry.entry_id] is mock_client


async def test_setup_entry_registers_sync_time_service(
    hass, config_entry, mock_client
):
    with (
        patch("custom_components.anthemav_serial.AnthemClient", return_value=mock_client),
        patch("custom_components.anthemav_serial.media_player.asyncio.sleep", AsyncMock()),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, "sync_time")


async def test_unload_entry_stops_client_and_removes_from_hass(
    hass, setup_integration
):
    config_entry, mock_client = setup_integration
    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    mock_client.stop.assert_called_once()
    assert config_entry.entry_id not in hass.data.get(DOMAIN, {})


# ── sync_time service ──────────────────────────────────────────────────────────

# Anthem day encoding: 1=Sunday, 2=Monday … 7=Saturday
_WEEKDAY_TO_ANTHEM = {
    0: 2,  # Monday
    1: 3,  # Tuesday
    2: 4,  # Wednesday
    3: 5,  # Thursday
    4: 6,  # Friday
    5: 7,  # Saturday
    6: 1,  # Sunday
}


@pytest.mark.parametrize("weekday,expected_day", list(_WEEKDAY_TO_ANTHEM.items()))
async def test_sync_time_sends_correct_day(
    hass, setup_integration, weekday, expected_day
):
    config_entry, mock_client = setup_integration
    fake_now = datetime(2024, 1, 1 + weekday, 10, 30)  # Monday–Sunday

    with patch("custom_components.anthemav_serial.dt_util") as mock_dt:
        mock_dt.now.return_value = fake_now
        await hass.services.async_call(DOMAIN, "sync_time", {}, blocking=True)

    sent: str = mock_client.send.call_args[0][0]
    assert f"STD{expected_day}" in sent


async def _setup_with_time_format(hass, mock_client, use_24hr):
    """Set up one entry with a given clock-format option (no update-triggered reload)."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from tests.conftest import ENTRY_DATA, MOCK_ID, MOCK_MODEL

    entry = MockConfigEntry(
        domain=DOMAIN, title=MOCK_MODEL, data=ENTRY_DATA,
        options={"time_format_24hr": use_24hr}, unique_id=MOCK_ID, version=2,
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.anthemav_serial.AnthemClient", return_value=mock_client),
        patch("custom_components.anthemav_serial.media_player.asyncio.sleep", AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_sync_time_12hr_format(hass, mock_client):
    await _setup_with_time_format(hass, mock_client, use_24hr=False)
    fake_now = datetime(2024, 1, 1, 14, 5)  # 14:05 → 02:05PM in 12hr

    with patch("custom_components.anthemav_serial.dt_util") as mock_dt:
        mock_dt.now.return_value = fake_now
        await hass.services.async_call(DOMAIN, "sync_time", {}, blocking=True)

    sent: str = mock_client.send.call_args[0][0]
    assert "STF0" in sent
    assert "STC02:05PM" in sent


async def test_sync_time_24hr_format(hass, mock_client):
    await _setup_with_time_format(hass, mock_client, use_24hr=True)
    fake_now = datetime(2024, 1, 1, 14, 5)

    with patch("custom_components.anthemav_serial.dt_util") as mock_dt:
        mock_dt.now.return_value = fake_now
        await hass.services.async_call(DOMAIN, "sync_time", {}, blocking=True)

    sent: str = mock_client.send.call_args[0][0]
    assert "STF1" in sent
    assert "STC14:05" in sent


async def test_sync_time_no_devices_raises(hass):
    """The service is domain-wide; calling it with no loaded entry errors clearly."""
    from homeassistant.exceptions import ServiceValidationError
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    assert hass.services.has_service(DOMAIN, "sync_time")
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "sync_time", {}, blocking=True)


async def test_sync_time_stacks_all_commands_in_one_send(hass, setup_integration):
    """All three sub-commands must arrive in a single semicolon-separated send."""
    config_entry, mock_client = setup_integration
    mock_client.send.reset_mock()  # ignore zone queries sent during setup
    fake_now = datetime(2024, 1, 1, 10, 0)  # Monday

    with patch("custom_components.anthemav_serial.dt_util") as mock_dt:
        mock_dt.now.return_value = fake_now
        await hass.services.async_call(DOMAIN, "sync_time", {}, blocking=True)

    assert mock_client.send.call_count == 1
    sent: str = mock_client.send.call_args[0][0]
    parts = sent.split(";")
    assert len(parts) == 3
    assert any(p.startswith("STF") for p in parts)
    assert any(p.startswith("STD") for p in parts)
    assert any(p.startswith("STC") for p in parts)
