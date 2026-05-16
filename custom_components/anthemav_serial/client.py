import asyncio
import logging
from collections.abc import Callable

import serialx

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10
RECONNECT_DELAY = 5


class AnthemClient:
    def __init__(
        self,
        url: str,
        baudrate: int,
        on_message: Callable[[str], None] | None = None,
        on_connection_lost: Callable[[], None] | None = None,
    ):
        # url is any serialx URL: socket://host:port, rfc2217://host:port,
        # esphome://host:port, or a native device path like /dev/ttyUSB0.
        # baudrate only matters for native serial; serialx requires it but
        # ignores it for the TCP-based schemes.
        self.url = url
        self.baudrate = baudrate
        self._on_message: Callable[[str], None] = on_message or (lambda _: None)
        self._on_connection_lost = on_connection_lost
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._listen_task: asyncio.Task | None = None
        self._running = False
        self.last_command: str = ""
        self._pending_queries: dict[str, asyncio.Future[str]] = {}

    def set_handlers(
        self,
        on_message: Callable[[str], None],
        on_connection_lost: Callable[[], None] | None = None,
    ) -> None:
        """Set the message / connection-lost handlers after construction.

        Used by the media_player platform to wire the central message router
        once entities exist. Keeps the constructor's callback optional.
        """
        self._on_message = on_message
        if on_connection_lost is not None:
            self._on_connection_lost = on_connection_lost

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        # serialx.open_serial_connection mirrors asyncio.open_connection and
        # returns the same (StreamReader, StreamWriter) pair, dispatching on
        # the URL scheme. baudrate is required by serialx for every scheme.
        self._reader, self._writer = await asyncio.wait_for(
            serialx.open_serial_connection(url=self.url, baudrate=self.baudrate),
            timeout=CONNECT_TIMEOUT,
        )
        _LOGGER.debug("Connected to %s", self.url)

    async def start(self) -> None:
        """Connect and begin listening for unsolicited messages."""
        self._running = True
        await self.connect()
        self._listen_task = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        """Disconnect and stop the listener."""
        self._running = False
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
            self._writer = None
            self._reader = None

    async def send(self, command: str) -> None:
        """Send a command. Responses arrive via on_message callback."""
        async with self._lock:
            if not self.connected:
                await self.connect()
            self._writer.write((command + "\n").encode())
            await self._writer.drain()
            self.last_command = command
            _LOGGER.debug("Sent: %s", command)

    async def query_one(self, command: str, prefix: str, timeout: float = 3.0) -> str | None:
        """Send a command and return the first response that starts with prefix."""
        fut: asyncio.Future[str] = asyncio.get_event_loop().create_future()
        self._pending_queries[prefix] = fut
        try:
            await self.send(command)
            return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._pending_queries.pop(prefix, None)

    async def _listen(self) -> None:
        """Read lines from the socket indefinitely and dispatch to callback."""
        while self._running:
            try:
                line = await self._reader.readline()
                if not line:
                    # Connection closed by remote
                    _LOGGER.warning("Connection closed by %s", self.url)
                    break
                message = line.decode().strip()
                if message:
                    _LOGGER.debug("Received: %s", message)
                    for prefix, fut in list(self._pending_queries.items()):
                        if message.startswith(prefix) and not fut.done():
                            fut.set_result(message)
                    self._on_message(message)
            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.error("Error reading from %s: %s", self.url, err)
                break

        if self._running and self._on_connection_lost:
            self._on_connection_lost()

