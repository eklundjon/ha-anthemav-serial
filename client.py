import asyncio
import logging
from collections.abc import Callable

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10
RECONNECT_DELAY = 5


class AnthemClient:
    def __init__(
        self,
        host: str,
        port: int,
        on_message: Callable[[str], None],
        on_connection_lost: Callable[[], None] | None = None,
    ):
        self.host = host
        self.port = port
        self._on_message = on_message
        self._on_connection_lost = on_connection_lost
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._listen_task: asyncio.Task | None = None
        self._running = False
        self.last_command: str = ""

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port),
            timeout=CONNECT_TIMEOUT,
        )
        _LOGGER.debug("Connected to %s:%s", self.host, self.port)

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

    async def _listen(self) -> None:
        """Read lines from the socket indefinitely and dispatch to callback."""
        while self._running:
            try:
                line = await self._reader.readline()
                if not line:
                    # Connection closed by remote
                    _LOGGER.warning("Connection closed by %s", self.host)
                    break
                message = line.decode().strip()
                if message:
                    _LOGGER.debug("Received: %s", message)
                    self._on_message(message)
            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.error("Error reading from %s: %s", self.host, err)
                break

        if self._running and self._on_connection_lost:
            self._on_connection_lost()

