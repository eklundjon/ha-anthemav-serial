"""Tests for AnthemClient."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.anthemav_serial.client import AnthemClient


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_stream(lines: list[bytes] | None = None):
    """Return a (reader, writer) pair with optional read data."""
    reader = MagicMock(spec=asyncio.StreamReader)
    writer = MagicMock(spec=asyncio.StreamWriter)
    writer.is_closing.return_value = False
    writer.write = MagicMock()
    writer.drain = AsyncMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()
    if lines is not None:
        reader.readline = AsyncMock(side_effect=lines)
    return reader, writer


async def _connected_client(reader, writer, on_message=None, on_connection_lost=None):
    client = AnthemClient(
        host="192.168.1.100",
        port=14000,
        on_message=on_message or (lambda _: None),
        on_connection_lost=on_connection_lost,
    )
    with patch("asyncio.open_connection", AsyncMock(return_value=(reader, writer))):
        await client.connect()
    return client


# ── connect ────────────────────────────────────────────────────────────────────

async def test_connect_opens_connection():
    reader, writer = _make_stream()
    with patch("asyncio.open_connection", AsyncMock(return_value=(reader, writer))) as mock_open:
        client = AnthemClient("host", 14000, on_message=lambda _: None)
        await client.connect()
    mock_open.assert_called_once_with("host", 14000)
    assert client.connected


async def test_connect_timeout_raises():
    client = AnthemClient("host", 14000, on_message=lambda _: None)
    with patch("asyncio.open_connection", AsyncMock(side_effect=TimeoutError)):
        with pytest.raises(TimeoutError):
            await client.connect()


# ── send ───────────────────────────────────────────────────────────────────────

async def test_send_writes_command_with_newline():
    reader, writer = _make_stream()
    client = await _connected_client(reader, writer)
    await client.send("P1P?")
    writer.write.assert_called_once_with(b"P1P?\n")


async def test_send_records_last_command():
    reader, writer = _make_stream()
    client = await _connected_client(reader, writer)
    await client.send("P1P1")
    await client.send("P1VM-35.0")
    assert client.last_command == "P1VM-35.0"


async def test_send_reconnects_when_not_connected():
    reader, writer = _make_stream()
    client = AnthemClient("host", 14000, on_message=lambda _: None)
    # No prior connect — send should open the connection automatically.
    with patch("asyncio.open_connection", AsyncMock(return_value=(reader, writer))):
        await client.send("P1P?")
    writer.write.assert_called_once_with(b"P1P?\n")


# ── _listen ────────────────────────────────────────────────────────────────────

async def test_listen_dispatches_decoded_messages():
    received = []
    reader, writer = _make_stream(lines=[b"P1P1\n", b""])
    client = await _connected_client(reader, writer, on_message=received.append)
    client._running = True
    await client._listen()
    assert received == ["P1P1"]


async def test_listen_strips_whitespace():
    received = []
    reader, writer = _make_stream(lines=[b"P1P1\r\n", b""])
    client = await _connected_client(reader, writer, on_message=received.append)
    client._running = True
    await client._listen()
    assert received == ["P1P1"]


async def test_listen_ignores_empty_lines():
    received = []
    reader, writer = _make_stream(lines=[b"\n", b"P1P1\n", b""])
    client = await _connected_client(reader, writer, on_message=received.append)
    client._running = True
    await client._listen()
    assert received == ["P1P1"]


async def test_listen_calls_on_connection_lost_on_eof():
    lost = []
    reader, writer = _make_stream(lines=[b""])
    client = await _connected_client(
        reader, writer, on_connection_lost=lambda: lost.append(True)
    )
    client._running = True
    await client._listen()
    assert lost == [True]


async def test_listen_does_not_call_on_connection_lost_when_stopped():
    """If _running is False (clean stop), on_connection_lost must not fire."""
    lost = []
    reader, writer = _make_stream(lines=[b""])
    client = await _connected_client(
        reader, writer, on_connection_lost=lambda: lost.append(True)
    )
    client._running = False
    await client._listen()
    assert lost == []


async def test_listen_resolves_pending_queries():
    """Messages matching a pending query prefix must resolve the future."""
    resolved = []
    reader, writer = _make_stream(lines=[b"STF1\n", b""])

    client = await _connected_client(reader, writer)
    client._running = True

    fut = asyncio.get_event_loop().create_future()
    client._pending_queries["STF"] = fut

    await client._listen()

    assert fut.done()
    assert fut.result() == "STF1"


# ── query_one ──────────────────────────────────────────────────────────────────

async def test_query_one_returns_matching_response():
    reader, writer = _make_stream()
    client = await _connected_client(reader, writer)

    async def fake_send(cmd):
        # Simulate the device responding immediately after the command.
        for prefix, fut in list(client._pending_queries.items()):
            if "STF1".startswith(prefix) and not fut.done():
                fut.set_result("STF1")

    client.send = fake_send
    result = await client.query_one("STF?", "STF")
    assert result == "STF1"


async def test_query_one_returns_none_on_timeout():
    reader, writer = _make_stream()
    client = await _connected_client(reader, writer)
    client.send = AsyncMock()  # no response ever arrives
    result = await client.query_one("STF?", "STF", timeout=0.01)
    assert result is None


async def test_query_one_cleans_up_pending_query_after_timeout():
    reader, writer = _make_stream()
    client = await _connected_client(reader, writer)
    client.send = AsyncMock()
    await client.query_one("STF?", "STF", timeout=0.01)
    assert "STF" not in client._pending_queries


# ── stop ───────────────────────────────────────────────────────────────────────

async def test_stop_closes_writer():
    reader, writer = _make_stream(lines=[b""])
    client = await _connected_client(reader, writer)
    client._running = True
    client._listen_task = asyncio.create_task(client._listen())
    await client.stop()
    writer.close.assert_called_once()
    writer.wait_closed.assert_called_once()
    assert client._writer is None


async def test_stop_sets_running_false():
    reader, writer = _make_stream(lines=[b""])
    client = await _connected_client(reader, writer)
    client._running = True
    client._listen_task = asyncio.create_task(client._listen())
    await client.stop()
    assert not client._running
