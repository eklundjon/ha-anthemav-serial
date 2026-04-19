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
MOCK_MODEL = "AVM 50v"
MOCK_SW_VERSION = "v3.09"
MOCK_IDENTITY = f"{MOCK_MODEL} {MOCK_SW_VERSION} Aug 21 2012-12:07:09"
ENTRY_DATA = {
    "host": MOCK_HOST,
    "port": MOCK_PORT,
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
    client.host = MOCK_HOST
    client.port = MOCK_PORT
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
    return client


@pytest.fixture
def config_entry(hass):
    """A MockConfigEntry pre-added to hass."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_MODEL,
        data=ENTRY_DATA,
        options={},
        unique_id=f"{MOCK_HOST}:{MOCK_PORT}",
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
