"""Tests for the sub-device topology (processor + zone/tuner/headphone children)."""
from __future__ import annotations

from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.anthemav_serial.const import DOMAIN
from tests.conftest import MOCK_ID


def _device(hass, suffix: str | None = None):
    ident = MOCK_ID if suffix is None else f"{MOCK_ID}_{suffix}"
    return dr.async_get(hass).async_get_device(identifiers={(DOMAIN, ident)})


def _device_of(hass, unique_id: str):
    ent_reg = er.async_get(hass)
    entry = next(e for e in ent_reg.entities.values() if e.unique_id == unique_id)
    return dr.async_get(hass).async_get(entry.device_id)


async def test_processor_device_exists(hass, setup_integration):
    assert _device(hass) is not None


async def test_subdevices_hang_off_processor(hass, setup_integration):
    processor = _device(hass)
    for suffix in ("zone1", "zone2", "zone3", "tuner", "headphone"):
        sub = _device(hass, suffix)
        assert sub is not None, f"missing sub-device {suffix}"
        assert sub.via_device_id == processor.id, f"{suffix} not linked via processor"


async def test_entities_land_on_the_right_device(hass, setup_integration):
    cases = {
        f"{MOCK_ID}_zone1": f"{MOCK_ID}_zone1",          # main media_player
        f"{MOCK_ID}_zone1_remote": f"{MOCK_ID}_zone1",   # main remote
        f"{MOCK_ID}_zone1_tone": f"{MOCK_ID}_zone1",     # tone defeat
        f"{MOCK_ID}_zone2": f"{MOCK_ID}_zone2",
        f"{MOCK_ID}_tuner": f"{MOCK_ID}_tuner",          # tuner media_player
        f"{MOCK_ID}_tuner_mode": f"{MOCK_ID}_tuner",     # tuner mode select
        f"{MOCK_ID}_hp_volume": f"{MOCK_ID}_headphone",
        f"{MOCK_ID}_hp_mute": f"{MOCK_ID}_headphone",
        f"{MOCK_ID}_panel_lock": MOCK_ID,                # processor-global
        f"{MOCK_ID}_rec_source": MOCK_ID,
        f"{MOCK_ID}_fp_brightness": MOCK_ID,
    }
    for unique_id, expected_ident in cases.items():
        device = _device_of(hass, unique_id)
        assert device.identifiers == {(DOMAIN, expected_ident)}, (
            f"{unique_id} on {device.identifiers}, expected {expected_ident}"
        )


async def test_default_disabled_entities(hass, config_entry, mock_client):
    """Niche/redundant entities ship disabled-by-default; primary ones don't.

    Sets up directly (not via setup_integration, which force-enables them) so
    the real registry disabled_by flags are observed.
    """
    from unittest.mock import AsyncMock, patch

    with (
        patch("custom_components.anthemav_serial.AnthemClient", return_value=mock_client),
        patch("custom_components.anthemav_serial.media_player.asyncio.sleep", AsyncMock()),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    by_uid = {e.unique_id: e for e in er.async_get(hass).entities.values()}

    for uid in (
        f"{MOCK_ID}_zone1_remote", f"{MOCK_ID}_zone2_remote", f"{MOCK_ID}_zone3_remote",
        f"{MOCK_ID}_panel_lock", f"{MOCK_ID}_auto_timers", f"{MOCK_ID}_rec_source",
    ):
        assert by_uid[uid].disabled_by is not None, f"{uid} should be disabled by default"

    for uid in (f"{MOCK_ID}_zone1", f"{MOCK_ID}_fp_brightness", f"{MOCK_ID}_hp_volume"):
        assert by_uid[uid].disabled_by is None, f"{uid} should be enabled by default"
