"""Unit tests for MessageRouter — exercised directly, no HA setup needed.

This is the payoff of extracting the router out of async_setup_entry: routing
logic is testable in isolation with lightweight fakes.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.anthemav_serial.const import ZONE_2, ZONE_3, ZONE_MAIN
from custom_components.anthemav_serial.media_player import MessageRouter


def _make_router():
    zones = {
        z: SimpleNamespace(handle_message=MagicMock(), source_id="5")
        for z in (ZONE_MAIN, ZONE_2, ZONE_3)
    }
    tuner = SimpleNamespace(
        handle_message=MagicMock(), notify_zone_source=MagicMock(), mark_unavailable=MagicMock()
    )
    client = SimpleNamespace(last_command="P1P?", url="socket://host:14000")
    all_entities = [*zones.values(), tuner]
    router = MessageRouter(zones, tuner, client, all_entities)
    return router, zones, tuner


def test_zone_message_routes_to_zone_and_notifies_tuner():
    router, zones, tuner = _make_router()
    router.dispatch("P1P1")
    zones[ZONE_MAIN].handle_message.assert_called_once_with("P1P1")
    tuner.notify_zone_source.assert_called_once_with(ZONE_MAIN, "5")
    zones[ZONE_2].handle_message.assert_not_called()


def test_tuner_message_routes_to_tuner():
    router, zones, tuner = _make_router()
    router.dispatch("TFT 87.5")
    tuner.handle_message.assert_called_once_with("TFT 87.5")
    zones[ZONE_MAIN].handle_message.assert_not_called()


def test_zone_off_text_routes_to_correct_zone():
    router, zones, tuner = _make_router()
    router.dispatch("Zone2 Off")
    zones[ZONE_2].handle_message.assert_called_once_with("Zone2 Off")


def test_unrouted_message_logs_warning(caplog):
    router, _, _ = _make_router()
    import logging

    with caplog.at_level(logging.WARNING):
        router.dispatch("totally unknown")
    assert "unrouted" in caplog.text.lower()


def test_invalid_command_logs_last_command(caplog):
    router, _, _ = _make_router()
    import logging

    with caplog.at_level(logging.WARNING):
        router.dispatch("Invalid Command")
    assert "P1P?" in caplog.text


def test_already_in_use_logs_last_command(caplog):
    router, _, _ = _make_router()
    import logging

    with caplog.at_level(logging.WARNING):
        router.dispatch("Already in use")
    assert "Already in use" in caplog.text
    assert "unrouted" not in caplog.text.lower()


def test_connection_lost_marks_all_unavailable():
    router, zones, tuner = _make_router()
    for z in zones.values():
        z.mark_unavailable = MagicMock()
    router.connection_lost()
    for z in zones.values():
        z.mark_unavailable.assert_called_once()
    tuner.mark_unavailable.assert_called_once()


def test_connection_restored_refreshes_all():
    router, zones, tuner = _make_router()
    for z in zones.values():
        z.request_refresh = MagicMock()
    tuner.request_refresh = MagicMock()
    router.connection_restored()
    for z in zones.values():
        z.request_refresh.assert_called_once()
    tuner.request_refresh.assert_called_once()
