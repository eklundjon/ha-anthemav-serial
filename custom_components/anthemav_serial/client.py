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
        self._on_connection_restored: Callable[[], None] | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()
        self._listen_task: asyncio.Task | None = None
        self._running = False
        self.last_command: str = ""
        # Each pending query is a (matcher, future) pair. The first received
        # message for which matcher(message) is True resolves the future.
        self._pending_queries: list[tuple[Callable[[str], bool], asyncio.Future[str]]] = []

    def set_handlers(
        self,
        on_message: Callable[[str], None],
        on_connection_lost: Callable[[], None] | None = None,
        on_connection_restored: Callable[[], None] | None = None,
    ) -> None:
        """Set the message / connection handlers after construction.

        Used by the media_player platform to wire the central message router
        once entities exist. Keeps the constructor's callback optional.
        on_connection_restored fires after the listener reconnects following a
        drop, so entities can re-query state (the device only pushes on change).
        """
        self._on_message = on_message
        if on_connection_lost is not None:
            self._on_connection_lost = on_connection_lost
        if on_connection_restored is not None:
            self._on_connection_restored = on_connection_restored

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        # serialx.open_serial_connection mirrors asyncio.open_connection and
        # returns the same (StreamReader, StreamWriter) pair, dispatching on
        # the URL scheme. baudrate is required by serialx for every scheme.
        # The lock serializes the lazy reconnect in send() against the
        # supervisor's reconnect loop so only one transport is ever opened.
        async with self._connect_lock:
            if self.connected:
                return
            self._reader, self._writer = await asyncio.wait_for(
                serialx.open_serial_connection(url=self.url, baudrate=self.baudrate),
                timeout=CONNECT_TIMEOUT,
            )
            _LOGGER.debug("Connected to %s", self.url)

    async def start(self) -> None:
        """Connect and begin listening for unsolicited messages."""
        self._running = True
        await self.connect()
        self._listen_task = asyncio.create_task(self._supervise())

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
            try:
                await self._writer.wait_closed()
            except OSError as err:
                # Teardown is best-effort: wait_closed() re-raises whatever
                # closed the transport (e.g. "socket closed by peer" when a
                # single-client serial gateway drops us). Not a failure to act on.
                _LOGGER.debug("Ignoring error closing %s: %s", self.url, err)
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

    async def query_one(
        self,
        command: str,
        prefix: str = "",
        *,
        match: Callable[[str], bool] | None = None,
        timeout: float = 3.0,
    ) -> str | None:
        """Send a command and return the first response that matches.

        By default a response matches when it starts with `prefix`. Pass an
        explicit `match` predicate for finer control — e.g. probing device
        identity, where no fixed prefix exists and an unsolicited push must not
        be mistaken for the reply.
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        matcher = match if match is not None else (lambda msg: msg.startswith(prefix))
        entry = (matcher, fut)
        self._pending_queries.append(entry)
        try:
            await self.send(command)
            return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            if entry in self._pending_queries:
                self._pending_queries.remove(entry)

    async def _supervise(self) -> None:
        """Run the read loop, reconnecting after drops until stopped."""
        while self._running:
            await self._listen()  # returns on disconnect (fires on_connection_lost)
            if not self._running:
                break
            await self._reconnect()
            if self._running and self._on_connection_restored:
                self._on_connection_restored()

    async def _reconnect(self) -> None:
        """Retry connect() every RECONNECT_DELAY until it succeeds or we stop."""
        # Tear down the dead transport so `connected` reports False and a fresh
        # connection is actually opened (a half-open socket can still look open).
        if self._writer is not None:
            self._writer.close()
            self._writer = None
            self._reader = None
        while self._running:
            try:
                await self.connect()
                _LOGGER.info("Reconnected to %s", self.url)
                return
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Reconnect to %s failed: %s; retrying in %ds",
                    self.url, err, RECONNECT_DELAY,
                )
                await asyncio.sleep(RECONNECT_DELAY)

    async def _listen(self) -> None:
        """Read lines from the socket and dispatch until the connection drops."""
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
                    for matcher, fut in list(self._pending_queries):
                        if not fut.done() and matcher(message):
                            fut.set_result(message)
                    self._on_message(message)
            except asyncio.CancelledError:
                # Propagate so the supervisor task actually dies when cancelled
                # (e.g. on HA shutdown, which cancels the task without setting
                # _running=False). Swallowing it left _supervise reconnecting
                # forever — an unkillable task that segfaulted at interpreter
                # teardown while still holding the socket transport.
                raise
            except Exception as err:
                _LOGGER.error("Error reading from %s: %s", self.url, err)
                break

        if self._running and self._on_connection_lost:
            self._on_connection_lost()
