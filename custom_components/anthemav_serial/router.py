"""Fan raw device messages out to entities and broadcast connection state.

Every platform subscribes to `message_signal` and self-filters, so this router
is just the single client handler that broadcasts each message (no entity's
add-time query reply is lost to a not-yet-wired handler) plus the
connection-state broadcaster on `connection_signal`.
"""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .client import AnthemClient
from .const import connection_signal, message_signal

_LOGGER = logging.getLogger(__name__)

_ERROR_MESSAGES = ("Invalid Command", "Parameter Out-of-range", "Already in use")


class MessageRouter:
    """Wired as the client's message / connection handler in async_setup_entry."""

    def __init__(self, hass: HomeAssistant, client: AnthemClient, entry_id: str) -> None:
        self._hass = hass
        self._client = client
        self._message_signal = message_signal(entry_id)
        self._connection_signal = connection_signal(entry_id)

    @callback
    def dispatch(self, message: str) -> None:
        _LOGGER.debug("RX: %r", message)
        if message in _ERROR_MESSAGES:
            # "Already in use" = the selected source's digital input is assigned
            # to another source (input conflict); the command didn't fully apply.
            _LOGGER.warning(
                "Device returned %r (last sent: %r)", message, self._client.last_command
            )
        async_dispatcher_send(self._hass, self._message_signal, message)

    @callback
    def connection_lost(self) -> None:
        _LOGGER.warning("Lost connection to Anthem device at %s", self._client.url)
        async_dispatcher_send(self._hass, self._connection_signal, False)

    @callback
    def connection_restored(self) -> None:
        _LOGGER.info("Reconnected to Anthem device at %s; refreshing state", self._client.url)
        async_dispatcher_send(self._hass, self._connection_signal, True)
