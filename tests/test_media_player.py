"""Tests for AnthemZoneEntity and AnthemTunerEntity."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.media_player import MediaPlayerState
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.anthemav_serial.const import (
    DOMAIN,
    VOLUME_MAX,
    VOLUME_MIN,
    ZONE_2,
    ZONE_3,
    ZONE_MAIN,
)
from tests.conftest import ENTRY_DATA, MOCK_HOST, MOCK_PORT


# ── Helpers ────────────────────────────────────────────────────────────────────

def _entity_id_for_unique(hass, unique_id: str) -> str:
    reg = er.async_get(hass)
    entry = next(
        (e for e in reg.entities.values() if e.unique_id == unique_id),
        None,
    )
    assert entry is not None, f"No entity with unique_id {unique_id!r}"
    return entry.entity_id


def _device_prefix(host=MOCK_HOST, port=MOCK_PORT):
    return f"{host}:{port}"


def zone_entity_id(hass, zone: int) -> str:
    return _entity_id_for_unique(hass, f"{_device_prefix()}_zone{zone}")


def tuner_entity_id(hass) -> str:
    return _entity_id_for_unique(hass, f"{_device_prefix()}_tuner")


# ── Setup ──────────────────────────────────────────────────────────────────────

async def test_four_entities_created(hass, setup_integration):
    """Zone 1, Zone 2, Zone 3, and Tuner must all be registered."""
    reg = er.async_get(hass)
    uids = {e.unique_id for e in reg.entities.values() if e.domain == "media_player"}
    prefix = _device_prefix()
    assert f"{prefix}_zone1" in uids
    assert f"{prefix}_zone2" in uids
    assert f"{prefix}_zone3" in uids
    assert f"{prefix}_tuner" in uids


async def test_zones_start_unavailable(hass, setup_integration):
    for zone in (ZONE_MAIN, ZONE_2, ZONE_3):
        state = hass.states.get(zone_entity_id(hass, zone))
        assert state is not None
        assert state.state == "unavailable"


async def test_tuner_starts_unavailable(hass, setup_integration):
    state = hass.states.get(tuner_entity_id(hass))
    assert state is not None
    assert state.state == "unavailable"


# ── Zone: power ────────────────────────────────────────────────────────────────

async def test_zone_power_on_message_sets_state_on(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    on_message("P1P1")
    await hass.async_block_till_done()

    state = hass.states.get(zone_entity_id(hass, ZONE_MAIN))
    assert state.state == MediaPlayerState.ON


async def test_zone_power_off_message_sets_state_off(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    on_message("P1P1")
    await hass.async_block_till_done()
    on_message("P1P0")
    await hass.async_block_till_done()

    state = hass.states.get(zone_entity_id(hass, ZONE_MAIN))
    assert state.state == MediaPlayerState.OFF


async def test_zone_becomes_available_on_first_power_message(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    on_message("P1P0")
    await hass.async_block_till_done()

    state = hass.states.get(zone_entity_id(hass, ZONE_MAIN))
    assert state.state != "unavailable"


async def test_zone_becomes_unavailable_on_connection_lost(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message
    on_connection_lost = mock_client._on_connection_lost

    on_message("P1P1")
    await hass.async_block_till_done()
    on_connection_lost()
    await hass.async_block_till_done()

    state = hass.states.get(zone_entity_id(hass, ZONE_MAIN))
    assert state.state == "unavailable"


# ── Zone: volume ───────────────────────────────────────────────────────────────

async def test_zone1_volume_message_vm_format(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    on_message("P1P1")
    on_message("P1VM-35.0")
    await hass.async_block_till_done()

    state = hass.states.get(zone_entity_id(hass, ZONE_MAIN))
    expected = (-35.0 - VOLUME_MIN) / (VOLUME_MAX - VOLUME_MIN)
    assert abs(state.attributes["volume_level"] - expected) < 0.001


async def test_zone2_volume_message_v_format(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    on_message("P2P1")
    on_message("P2V-15.00")
    await hass.async_block_till_done()

    state = hass.states.get(zone_entity_id(hass, ZONE_2))
    expected = (-15.0 - VOLUME_MIN) / (VOLUME_MAX - VOLUME_MIN)
    assert abs(state.attributes["volume_level"] - expected) < 0.001


async def test_volume_level_clamped_to_0_1(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    # Volume below the configured minimum.
    on_message("P1P1")
    on_message(f"P1VM{VOLUME_MIN - 10.0:+.1f}")
    await hass.async_block_till_done()

    state = hass.states.get(zone_entity_id(hass, ZONE_MAIN))
    assert state.attributes["volume_level"] == 0.0


# ── Zone: mute ─────────────────────────────────────────────────────────────────

async def test_zone_mute_on(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    on_message("P1P1")
    on_message("P1M1")
    await hass.async_block_till_done()

    state = hass.states.get(zone_entity_id(hass, ZONE_MAIN))
    assert state.attributes["is_volume_muted"] is True


async def test_zone_mute_off(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    on_message("P1P1")
    on_message("P1M1")
    on_message("P1M0")
    await hass.async_block_till_done()

    state = hass.states.get(zone_entity_id(hass, ZONE_MAIN))
    assert state.attributes["is_volume_muted"] is False


# ── Zone: source ───────────────────────────────────────────────────────────────

async def test_zone_source_message_sets_source_name(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    on_message("P1P1")
    on_message("P1S0")  # source 0 = "CD"
    await hass.async_block_till_done()

    state = hass.states.get(zone_entity_id(hass, ZONE_MAIN))
    assert state.attributes["source"] == "CD"


async def test_zone_hidden_source_sets_source_none(hass, mock_client):
    """A source in hidden_sources should resolve to None."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"Anthem AVM50 ({MOCK_HOST})",
        data=ENTRY_DATA,
        options={"hidden_sources": ["0"]},
        unique_id=f"{MOCK_HOST}:{MOCK_PORT}",
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.anthemav_serial.AnthemClient", return_value=mock_client),
        patch("custom_components.anthemav_serial.media_player.asyncio.sleep", AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    on_message = mock_client._on_message
    on_message("P1P1")
    on_message("P1S0")
    await hass.async_block_till_done()

    state = hass.states.get(zone_entity_id(hass, ZONE_MAIN))
    assert state.attributes.get("source") is None


# ── Zone: combined status ──────────────────────────────────────────────────────

async def test_zone_combined_status_message(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    on_message("P1P1")
    on_message("P1S5V-35.0M0")  # source=DVD1, vol=-35, unmuted
    await hass.async_block_till_done()

    state = hass.states.get(zone_entity_id(hass, ZONE_MAIN))
    assert state.attributes["source"] == "DVD1"
    assert state.attributes["is_volume_muted"] is False
    expected_vol = (-35.0 - VOLUME_MIN) / (VOLUME_MAX - VOLUME_MIN)
    assert abs(state.attributes["volume_level"] - expected_vol) < 0.001


# ── Zone: simulcast ────────────────────────────────────────────────────────────

async def test_zone_simulcast_standalone_uses_audio_source(hass, setup_integration):
    """P{z}X{audio}{video} — audio source (first char) is tracked."""
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    on_message("P1P1")
    on_message("P1X50")  # audio=DVD1 (5), video=CD (0)
    await hass.async_block_till_done()

    state = hass.states.get(zone_entity_id(hass, ZONE_MAIN))
    assert state.attributes["source"] == "DVD1"


async def test_zone_simulcast_combined_status(hass, setup_integration):
    """P{z}X{audio}{video}V{vol}M{mute} — audio source, vol, mute all parsed."""
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    on_message("P1P1")
    on_message("P1X50V-35.0M1")  # audio=DVD1 (5), video=CD (0), muted
    await hass.async_block_till_done()

    state = hass.states.get(zone_entity_id(hass, ZONE_MAIN))
    assert state.attributes["source"] == "DVD1"
    assert state.attributes["is_volume_muted"] is True
    expected_vol = (-35.0 - VOLUME_MIN) / (VOLUME_MAX - VOLUME_MIN)
    assert abs(state.attributes["volume_level"] - expected_vol) < 0.001


async def test_zone_simulcast_tuner_notified(hass, setup_integration):
    """Tuner entity is notified when simulcast audio source is tuner."""
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    on_message("P1P1")
    on_message("P1X46")  # audio=Tuner (4), video=TV1 (6)
    await hass.async_block_till_done()

    state = hass.states.get(tuner_entity_id(hass))
    assert state.state == MediaPlayerState.ON


# ── Zone: extra attributes ─────────────────────────────────────────────────────

async def test_zone_extra_attr_enum_resolved(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    # P1D: decoder, source-prefixed.  "P1D71" → source 7, decoder value "1" = "Dolby Digital"
    on_message("P1P1")
    on_message("P1D71")
    await hass.async_block_till_done()

    state = hass.states.get(zone_entity_id(hass, ZONE_MAIN))
    assert state.attributes.get("decoder") == "Dolby Digital"


async def test_zone_extra_attr_float_value(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    # Volume trim front: P1VF+1.5
    on_message("P1P1")
    on_message("P1VF+1.5")
    await hass.async_block_till_done()

    state = hass.states.get(zone_entity_id(hass, ZONE_MAIN))
    assert state.attributes.get("volume_trim_front") == pytest.approx(1.5)


async def test_zone_extra_attr_bare_response_no_warning(hass, setup_integration, caplog):
    """Empty payload (e.g. P1Q with no data) must not produce a warning."""
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    on_message("P1P1")
    with caplog.at_level("WARNING"):
        on_message("P1Q")
    await hass.async_block_till_done()

    assert "unrecognized message" not in caplog.text.lower()


async def test_zone_unrecognized_message_logs_warning(hass, setup_integration, caplog):
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    with caplog.at_level("WARNING"):
        on_message("P1XYZZY")
    await hass.async_block_till_done()

    assert "unrecognized" in caplog.text.lower()


# ── Zone: commands ─────────────────────────────────────────────────────────────

async def test_turn_on_sends_power_command(hass, setup_integration):
    config_entry, mock_client = setup_integration
    on_message = mock_client._on_message
    # Make entity available (OFF) so HA will dispatch to it.
    on_message("P1P0")
    await hass.async_block_till_done()
    mock_client.send.reset_mock()

    entity_id = zone_entity_id(hass, ZONE_MAIN)
    await hass.services.async_call(
        "media_player", "turn_on", {"entity_id": entity_id}, blocking=True
    )
    mock_client.send.assert_called_once_with("P1P1")


async def test_turn_off_sends_power_command(hass, setup_integration):
    config_entry, mock_client = setup_integration
    on_message = mock_client._on_message
    on_message("P1P1")
    await hass.async_block_till_done()
    mock_client.send.reset_mock()

    entity_id = zone_entity_id(hass, ZONE_MAIN)
    await hass.services.async_call(
        "media_player", "turn_off", {"entity_id": entity_id}, blocking=True
    )
    mock_client.send.assert_called_once_with("P1P0")


async def test_set_volume_level_zone1_uses_vm_format(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message
    on_message("P1P1")
    await hass.async_block_till_done()
    mock_client.send.reset_mock()

    entity_id = zone_entity_id(hass, ZONE_MAIN)
    target_db = 0.5 * (VOLUME_MAX - VOLUME_MIN) + VOLUME_MIN
    db_rounded = round(target_db * 2) / 2

    await hass.services.async_call(
        "media_player", "volume_set", {"entity_id": entity_id, "volume_level": 0.5},
        blocking=True,
    )

    mock_client.send.assert_called_once_with(f"P1VM{db_rounded:+.1f}")


async def test_set_volume_level_zone2_uses_v_format(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message
    on_message("P2P1")
    await hass.async_block_till_done()
    mock_client.send.reset_mock()

    entity_id = zone_entity_id(hass, ZONE_2)
    await hass.services.async_call(
        "media_player", "volume_set", {"entity_id": entity_id, "volume_level": 0.5},
        blocking=True,
    )

    sent = mock_client.send.call_args[0][0]
    # Zone 2 uses P2V (no M) with 1.25 dB steps
    assert sent.startswith("P2V") and "VM" not in sent


async def test_mute_sends_mute_command(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message
    on_message("P1P1")
    await hass.async_block_till_done()
    mock_client.send.reset_mock()

    entity_id = zone_entity_id(hass, ZONE_MAIN)
    await hass.services.async_call(
        "media_player", "volume_mute", {"entity_id": entity_id, "is_volume_muted": True},
        blocking=True,
    )
    mock_client.send.assert_called_once_with("P1M1")


async def test_unmute_sends_unmute_command(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message
    on_message("P1P1")
    await hass.async_block_till_done()
    mock_client.send.reset_mock()

    entity_id = zone_entity_id(hass, ZONE_MAIN)
    await hass.services.async_call(
        "media_player", "volume_mute", {"entity_id": entity_id, "is_volume_muted": False},
        blocking=True,
    )
    mock_client.send.assert_called_once_with("P1M0")


async def test_select_source_sends_source_command(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message
    on_message("P1P1")
    await hass.async_block_till_done()
    mock_client.send.reset_mock()

    entity_id = zone_entity_id(hass, ZONE_MAIN)
    await hass.services.async_call(
        "media_player", "select_source", {"entity_id": entity_id, "source": "CD"},
        blocking=True,
    )
    mock_client.send.assert_called_once_with("P1S0")


async def test_select_unknown_source_logs_warning_and_sends_nothing(
    hass, setup_integration, caplog
):
    _, mock_client = setup_integration
    on_message = mock_client._on_message
    on_message("P1P1")
    await hass.async_block_till_done()
    mock_client.send.reset_mock()

    entity_id = zone_entity_id(hass, ZONE_MAIN)
    with caplog.at_level("WARNING"):
        await hass.services.async_call(
            "media_player",
            "select_source",
            {"entity_id": entity_id, "source": "Laserdisc"},
            blocking=True,
        )

    mock_client.send.assert_not_called()
    assert "unknown source" in caplog.text.lower()


# ── Tuner ──────────────────────────────────────────────────────────────────────

async def test_tuner_becomes_available_when_zone_reports_source(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    on_message("P1P1")
    on_message("P1S0")  # any source — triggers notify_zone_source
    await hass.async_block_till_done()

    state = hass.states.get(tuner_entity_id(hass))
    assert state.state != "unavailable"


async def test_tuner_on_when_zone_selects_tuner_source(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    on_message("P1P1")
    on_message("P1S4")  # source 4 = Tuner
    await hass.async_block_till_done()

    state = hass.states.get(tuner_entity_id(hass))
    assert state.state == MediaPlayerState.ON


async def test_tuner_idle_when_no_zone_on_tuner(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    on_message("P1P1")
    on_message("P1S4")  # select tuner
    await hass.async_block_till_done()
    on_message("P1S0")  # switch away
    await hass.async_block_till_done()

    state = hass.states.get(tuner_entity_id(hass))
    assert state.state == MediaPlayerState.IDLE


async def test_tuner_remains_on_while_any_zone_uses_tuner(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    # Zone 1 and Zone 2 both on tuner.
    on_message("P1P1")
    on_message("P1S4")
    on_message("P2P1")
    on_message("P2S4")
    await hass.async_block_till_done()

    # Zone 1 switches away — Zone 2 still on tuner.
    on_message("P1S0")
    await hass.async_block_till_done()

    state = hass.states.get(tuner_entity_id(hass))
    assert state.state == MediaPlayerState.ON


async def test_tuner_fm_frequency_parsed(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    on_message("TFT 87.5")
    await hass.async_block_till_done()

    state = hass.states.get(tuner_entity_id(hass))
    assert state.attributes.get("media_title") == "FM 87.5 MHz"


async def test_tuner_am_frequency_parsed(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    on_message("TAT 530")
    await hass.async_block_till_done()

    state = hass.states.get(tuner_entity_id(hass))
    assert state.attributes.get("media_title") == "AM 530 kHz"


async def test_tuner_mode_attribute_parsed(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message

    # Make tuner available first (HA omits extra_state_attributes for unavailable entities).
    on_message("P1S0")
    await hass.async_block_till_done()

    on_message("TH0")
    await hass.async_block_till_done()
    assert hass.states.get(tuner_entity_id(hass)).attributes.get("tuner_mode") == "Stereo"

    on_message("TH1")
    await hass.async_block_till_done()
    assert hass.states.get(tuner_entity_id(hass)).attributes.get("tuner_mode") == "Hi-blend"

    on_message("TH2")
    await hass.async_block_till_done()
    assert hass.states.get(tuner_entity_id(hass)).attributes.get("tuner_mode") == "Mono"


async def test_tuner_queries_mode_on_added_to_hass(hass, setup_integration):
    _, mock_client = setup_integration
    assert any(call.args == ("TH?",) for call in mock_client.send.call_args_list)


async def test_tuner_next_track_sends_command(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message
    # Any zone source message makes the tuner available.
    on_message("P1S0")
    await hass.async_block_till_done()
    mock_client.send.reset_mock()

    entity_id = tuner_entity_id(hass)
    await hass.services.async_call(
        "media_player", "media_next_track", {"entity_id": entity_id}, blocking=True
    )
    mock_client.send.assert_called_once_with("T+")


async def test_tuner_previous_track_sends_command(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message
    on_message("P1S0")
    await hass.async_block_till_done()
    mock_client.send.reset_mock()

    entity_id = tuner_entity_id(hass)
    await hass.services.async_call(
        "media_player", "media_previous_track", {"entity_id": entity_id}, blocking=True
    )
    mock_client.send.assert_called_once_with("T-")


async def test_tuner_mark_unavailable(hass, setup_integration):
    _, mock_client = setup_integration
    on_message = mock_client._on_message
    on_connection_lost = mock_client._on_connection_lost

    on_message("P1S4")
    await hass.async_block_till_done()
    on_connection_lost()
    await hass.async_block_till_done()

    state = hass.states.get(tuner_entity_id(hass))
    assert state.state == "unavailable"
