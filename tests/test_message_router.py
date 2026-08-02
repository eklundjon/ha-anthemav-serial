"""Unit tests for the message/connection router (a broadcaster)."""
from __future__ import annotations

import logging
from types import SimpleNamespace

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from custom_components.anthemav_serial.const import connection_signal, message_signal
from custom_components.anthemav_serial.router import MessageRouter

ENTRY_ID = "test_entry"


def _make_router(hass):
    client = SimpleNamespace(last_command="P1P?", url="socket://host:14000")
    return MessageRouter(hass, client, ENTRY_ID)


def _capture(hass, signal):
    """Subscribe a callback to `signal` and return the list it appends to."""
    seen: list = []

    @callback
    def _handle(value):
        seen.append(value)

    async_dispatcher_connect(hass, signal, _handle)
    return seen


async def test_dispatch_broadcasts_message(hass):
    seen = _capture(hass, message_signal(ENTRY_ID))
    _make_router(hass).dispatch("P1P1")
    await hass.async_block_till_done()
    assert seen == ["P1P1"]


async def test_error_message_logs_last_command(hass, caplog):
    with caplog.at_level(logging.WARNING):
        _make_router(hass).dispatch("Invalid Command")
    assert "P1P?" in caplog.text


async def test_connection_lost_dispatches_false(hass):
    seen = _capture(hass, connection_signal(ENTRY_ID))
    _make_router(hass).connection_lost()
    await hass.async_block_till_done()
    assert seen == [False]


async def test_connection_restored_dispatches_true(hass):
    seen = _capture(hass, connection_signal(ENTRY_ID))
    _make_router(hass).connection_restored()
    await hass.async_block_till_done()
    assert seen == [True]
