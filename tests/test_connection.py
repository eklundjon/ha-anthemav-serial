"""Connection-outage behavior: every entity goes unavailable on a drop and
re-queries on reconnect (driven by the router's connection_signal)."""
from __future__ import annotations

from homeassistant.helpers import entity_registry as er

from tests.conftest import MOCK_ID


def _eid(hass, unique_id: str) -> str:
    reg = er.async_get(hass)
    e = next(x for x in reg.entities.values() if x.unique_id == unique_id)
    return e.entity_id


async def test_connection_lost_marks_entities_unavailable(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client._on_message("P1P1")     # main media_player -> available
    mock_client._on_message("HV-35.0")  # headphone volume -> available
    mock_client._on_message("P1TE0")    # main tone defeat -> available
    await hass.async_block_till_done()
    for uid in (f"{MOCK_ID}_zone1", f"{MOCK_ID}_hp_volume", f"{MOCK_ID}_zone1_tone"):
        assert hass.states.get(_eid(hass, uid)).state != "unavailable"

    mock_client._on_connection_lost()
    await hass.async_block_till_done()

    for uid in (f"{MOCK_ID}_zone1", f"{MOCK_ID}_hp_volume", f"{MOCK_ID}_zone1_tone"):
        assert hass.states.get(_eid(hass, uid)).state == "unavailable"


async def test_connection_restored_requeries(hass, setup_integration):
    _, mock_client = setup_integration
    mock_client._on_connection_lost()
    await hass.async_block_till_done()
    mock_client.send.reset_mock()

    mock_client._on_connection_restored()
    await hass.async_block_till_done()

    sent = [c.args[0] for c in mock_client.send.call_args_list if c.args]
    assert any("P1P?" in s for s in sent)  # media_player zone refresh
    assert "HV?" in sent                    # headphone volume re-query
    assert "P1TE?" in sent                  # main tone defeat re-query


async def test_tuner_tracks_zone_source_over_dispatcher(hass, setup_integration):
    """The tuner now self-parses the broadcast stream (no router coupling)."""
    _, mock_client = setup_integration
    mock_client._on_message("P1S4")  # main selects the tuner (source 4)
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, f"{MOCK_ID}_tuner")).state == "on"

    mock_client._on_message("P1S5")  # main switches away to DVD1
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, f"{MOCK_ID}_tuner")).state == "idle"
