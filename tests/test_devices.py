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
