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
        url="socket://192.168.1.100:14000",
        baudrate=9600,
        on_message=on_message or (lambda _: None),
        on_connection_lost=on_connection_lost,
    )
    with patch(
        "serialx.open_serial_connection", AsyncMock(return_value=(reader, writer))
    ):
        await client.connect()
    return client


# ── connect ────────────────────────────────────────────────────────────────────

async def test_connect_opens_connection():
    reader, writer = _make_stream()
    with patch(
        "serialx.open_serial_connection", AsyncMock(return_value=(reader, writer))
    ) as mock_open:
        client = AnthemClient("socket://host:14000", 9600, on_message=lambda _: None)
        await client.connect()
    mock_open.assert_called_once_with(url="socket://host:14000", baudrate=9600)
    assert client.connected


async def test_connect_timeout_raises():
    client = AnthemClient("socket://host:14000", 9600, on_message=lambda _: None)
    with patch("serialx.open_serial_connection", AsyncMock(side_effect=TimeoutError)):
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
    client = AnthemClient("socket://host:14000", 9600, on_message=lambda _: None)
    # No prior connect — send should open the connection automatically.
    with patch("serialx.open_serial_connection", AsyncMock(return_value=(reader, writer))):
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
    client._pending_queries.append((lambda m: m.startswith("STF"), fut))

    await client._listen()

    assert fut.done()
    assert fut.result() == "STF1"


# ── query_one ──────────────────────────────────────────────────────────────────

async def test_query_one_returns_matching_response():
    reader, writer = _make_stream()
    client = await _connected_client(reader, writer)

    async def fake_send(cmd):
        # Simulate the device responding immediately after the command.
        for matcher, fut in list(client._pending_queries):
            if matcher("STF1") and not fut.done():
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
    assert client._pending_queries == []


async def test_listen_match_predicate_skips_nonmatching():
    """A custom matcher resolves only on a matching line, ignoring earlier pushes."""
    reader, writer = _make_stream(lines=[b"P1P1\n", b"AVM 50v v3.09\n", b""])
    client = await _connected_client(reader, writer)
    client._running = True

    fut = asyncio.get_event_loop().create_future()
    client._pending_queries.append((lambda m: m.startswith("AVM"), fut))

    await client._listen()

    # The unsolicited "P1P1" push must not resolve the identity query.
    assert fut.result() == "AVM 50v v3.09"


# ── reconnection ─────────────────────────────────────────────────────────────────

async def test_reconnect_retries_until_connected():
    reader, writer = _make_stream()
    client = AnthemClient("socket://host:14000", 9600)
    client._running = True
    opens = AsyncMock(side_effect=[OSError("down"), (reader, writer)])
    with patch("serialx.open_serial_connection", opens), patch(
        "custom_components.anthemav_serial.client.asyncio.sleep", AsyncMock()
    ):
        await client._reconnect()
    assert client.connected
    assert opens.call_count == 2


async def test_supervise_reconnects_and_fires_restored():
    """After a drop, the supervisor reconnects and fires on_connection_restored."""
    restored = []
    reader, writer = _make_stream(lines=[b""])  # immediate EOF triggers reconnect
    client = AnthemClient("socket://host:14000", 9600)
    client._reader, client._writer = reader, writer
    client._running = True

    def on_restored():
        restored.append(True)
        client._running = False  # let the supervisor exit after one cycle

    client._on_connection_restored = on_restored

    async def fake_reconnect():
        return  # pretend the reconnect succeeded instantly

    with patch.object(client, "_reconnect", side_effect=fake_reconnect):
        await client._supervise()

    assert restored == [True]


async def test_supervise_propagates_cancellation():
    """HA cancels the background task on shutdown without setting _running=False.
    The read loop must not swallow the cancellation — doing so left _supervise
    reconnecting forever, an unkillable task that segfaulted at teardown.
    """
    reader, writer = _make_stream()
    blocked = asyncio.Event()

    async def _block():
        blocked.set()
        await asyncio.sleep(3600)  # park inside readline until cancelled

    reader.readline = _block
    client = await _connected_client(reader, writer)
    client._running = True
    client._reconnect = AsyncMock()  # would run if the cancel were swallowed

    task = asyncio.create_task(client._supervise())
    await asyncio.wait_for(blocked.wait(), timeout=1)  # we're now inside readline
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)
    client._reconnect.assert_not_called()


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


async def test_stop_survives_peer_closed_socket():
    """wait_closed() re-raises the close cause (e.g. a single-client gateway
    dropping us); stop() must swallow it rather than surface a false error."""
    reader, writer = _make_stream(lines=[b""])
    client = await _connected_client(reader, writer)
    writer.wait_closed = AsyncMock(side_effect=OSError("socket closed by peer"))
    client._running = True
    client._listen_task = asyncio.create_task(client._listen())
    await client.stop()  # must not raise
    assert client._writer is None
