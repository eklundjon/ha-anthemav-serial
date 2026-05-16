"""Shared fixtures for anthemav_serial tests."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Make custom_components importable from the config directory.
sys.path.insert(0, str(Path(__file__).parent.parent))

from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.anthemav_serial.const import DOMAIN, VOLUME_MAX, VOLUME_MIN  # noqa: E402


# ── Constants ──────────────────────────────────────────────────────────────────

MOCK_HOST = "192.168.1.100"
MOCK_PORT = 14000
MOCK_URL = f"socket://{MOCK_HOST}:{MOCK_PORT}"
MOCK_BAUDRATE = 9600
MOCK_ID = "0123456789abcdef0123456789abcdef"
MOCK_MODEL = "AVM 50v"
MOCK_SW_VERSION = "v3.09"
MOCK_IDENTITY = f"{MOCK_MODEL} {MOCK_SW_VERSION} Aug 21 2012-12:07:09"
ENTRY_DATA = {
    "id": MOCK_ID,
    "url": MOCK_URL,
    "baudrate": MOCK_BAUDRATE,
    "model": MOCK_MODEL,
    "sw_version": MOCK_SW_VERSION,
}


# ── Required by HA 2021.6+: allow custom components to load during tests ───────

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_client():
    """A MagicMock that looks like an AnthemClient."""
    client = MagicMock()
    client.url = MOCK_URL
    client.baudrate = MOCK_BAUDRATE
    client.last_command = ""
    client.connected = True
    client.connect = AsyncMock()
    client.start = AsyncMock()
    client.stop = AsyncMock()
    client.send = AsyncMock()
    client.query_one = AsyncMock(return_value=None)
    client._on_message = None
    client._on_connection_lost = None
    client._pending_queries = {}

    # Mirror the real set_handlers(): store handlers so tests can drive routing
    # via client._on_message / client._on_connection_lost after setup.
    def _set_handlers(on_message, on_connection_lost=None):
        client._on_message = on_message
        if on_connection_lost is not None:
            client._on_connection_lost = on_connection_lost

    client.set_handlers = MagicMock(side_effect=_set_handlers)
    return client


@pytest.fixture
def config_entry(hass):
    """A MockConfigEntry pre-added to hass."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_MODEL,
        data=ENTRY_DATA,
        options={},
        unique_id=MOCK_ID,
        version=2,
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_integration(hass, config_entry, mock_client):
    """Set up the full integration with a mocked AnthemClient.

    Patches asyncio.sleep so _async_query_extra_attrs returns immediately,
    avoiding multi-second delays in the test suite.
    """
    from unittest.mock import patch

    with (
        patch("custom_components.anthemav_serial.AnthemClient", return_value=mock_client),
        patch("custom_components.anthemav_serial.media_player.asyncio.sleep", AsyncMock()),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    return config_entry, mock_client
