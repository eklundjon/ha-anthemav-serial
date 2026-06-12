from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import AnthemClient
from .const import (
    CONF_ID,
    CONF_MODEL,
    CONF_SW_VERSION,
    DOMAIN,
    ZONE_2,
    ZONE_3,
    ZONE_MAIN,
    cmd_auto_timers,
    cmd_panel_lock,
    cmd_tone_controls,
    cmd_trigger,
    message_signal,
)

CONF_TRIGGER_CONTROL = "trigger_control"

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

_ZONE_NAMES: dict[int, str] = {ZONE_MAIN: "Main", ZONE_2: "Zone 2", ZONE_3: "Zone 3"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: AnthemClient = hass.data[DOMAIN][entry.entry_id]
    # Tone control is a switch on the Main zone only (it reliably reports
    # P1TE). Zones 2/3 are usually off and don't report tone state, so a switch
    # there would sit in a misleading "unknown"/optimistic state — those zones
    # get fire-and-forget "bypass"/"enable" commands on their remote entities.
    entities: list[SwitchEntity] = [AnthemToneDefeatSwitch(client, ZONE_MAIN, entry)]
    entities.append(AnthemPanelLockSwitch(client, entry))
    entities.append(AnthemAutoTimersSwitch(client, entry))
    # Triggers are opt-in (options flow): enabling them takes the unit's 12V
    # triggers under RS-232 control, detaching them from their auto conditions.
    if entry.options.get(CONF_TRIGGER_CONTROL, False):
        entities += [AnthemTriggerSwitch(client, num, entry) for num in (1, 2, 3)]
    async_add_entities(entities)


class _AnthemSwitchBase(SwitchEntity):
    """Shared wiring: device info, message subscription, initial query."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, client: AnthemClient, entry: ConfigEntry) -> None:
        self._client = client
        self._entry_id = entry.entry_id
        device_id = entry.data[CONF_ID]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.title,
            manufacturer="Anthem",
            model=entry.data.get(CONF_MODEL),
            sw_version=entry.data.get(CONF_SW_VERSION),
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, message_signal(self._entry_id), self._handle_message
            )
        )
        await self._request_state()

    async def _request_state(self) -> None:
        """Send the query that elicits this switch's current state (if any)."""

    @callback
    def _handle_message(self, message: str) -> None:
        """Update state from a raw device message (overridden by subclasses)."""


class AnthemToneDefeatSwitch(_AnthemSwitchBase):
    """Main-zone tone defeat (P{z}TE). On = tone controls bypassed (defeated);
    off = normal operation (enabled) — inverted from the device flag (TE1 =
    enabled) so the switch is off in the default state.

    A powered-off zone can't report its tone state (the P{z}TE? query comes back
    as "Main Off"), so the switch is *unavailable* while the zone is off rather
    than guessing, and a true toggle once the zone is on and reports.
    """

    _attr_icon = "mdi:tune-vertical"

    def __init__(self, client: AnthemClient, zone: int, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self.zone = zone
        self._attr_name = f"{_ZONE_NAMES[zone]} tone defeat"
        self._attr_unique_id = f"{entry.data[CONF_ID]}_zone{zone}_tone"
        self._attr_is_on: bool | None = None
        self._attr_available = False  # until the zone reports its tone state
        self._re = re.compile(rf"^P{zone}TE([01])$")
        zone_off = {ZONE_MAIN: "Main Off", ZONE_2: "Zone2 Off", ZONE_3: "Zone3 Off"}[zone]
        self._power_off = frozenset({f"P{zone}P0", zone_off, "Unit Off"})
        self._power_on = f"P{zone}P1"

    async def _request_state(self) -> None:
        await self._client.send(f"P{self.zone}TE?")

    @callback
    def _handle_message(self, message: str) -> None:
        if m := self._re.match(message):
            defeated = m.group(1) == "0"  # TE0 = bypassed = defeat on
            if defeated != self._attr_is_on or not self._attr_available:
                self._attr_is_on = defeated
                self._attr_available = True
                self.async_write_ha_state()
        elif message in self._power_off:
            if self._attr_available:
                self._attr_available = False
                self._attr_is_on = None
                self.async_write_ha_state()
        elif message == self._power_on:
            # Zone came on — re-query so the toggle reflects the real state.
            self.hass.async_create_task(self._client.send(f"P{self.zone}TE?"))

    async def async_turn_on(self, **kwargs: Any) -> None:
        # Defeat on -> bypass the tone controls (TE0).
        await self._client.send(cmd_tone_controls(self.zone, False))
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        # Defeat off -> normal operation, tone controls enabled (TE1).
        await self._client.send(cmd_tone_controls(self.zone, True))
        self._attr_is_on = False
        self.async_write_ha_state()


class AnthemPanelLockSwitch(_AnthemSwitchBase):
    """Front-panel lockout (FPL). Write-only, but reliably state-trackable: it
    only clears via our command or a unit/main power-off — and we observe those.
    """

    _attr_icon = "mdi:lock"

    # Front-panel lock resets to off whenever the unit/main powers off.
    _POWER_OFF = frozenset({"Unit Off", "Main Off", "P1P0"})

    def __init__(self, client: AnthemClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_name = "Front panel lock"
        self._attr_unique_id = f"{entry.data[CONF_ID]}_panel_lock"
        # Unknown at cold start (no query); default off, then tracked.
        self._attr_is_on = False

    @callback
    def _handle_message(self, message: str) -> None:
        if message in self._POWER_OFF and self._attr_is_on:
            self._attr_is_on = False
            self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._client.send(cmd_panel_lock(True))
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._client.send(cmd_panel_lock(False))
        self._attr_is_on = False
        self.async_write_ha_state()


class AnthemAutoTimersSwitch(_AnthemSwitchBase):
    """Master enable for the auto on/off timers (STE)."""

    _attr_icon = "mdi:timer-cog-outline"

    def __init__(self, client: AnthemClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_name = "Auto on/off timers"
        self._attr_unique_id = f"{entry.data[CONF_ID]}_auto_timers"
        self._attr_is_on: bool | None = None
        self._re = re.compile(r"^STE([01])$")

    async def _request_state(self) -> None:
        await self._client.send("STE?")

    @callback
    def _handle_message(self, message: str) -> None:
        if m := self._re.match(message):
            is_on = m.group(1) == "1"
            if is_on != self._attr_is_on:
                self._attr_is_on = is_on
                self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._client.send(cmd_auto_timers(True))
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._client.send(cmd_auto_timers(False))
        self._attr_is_on = False
        self.async_write_ha_state()


class AnthemTriggerSwitch(_AnthemSwitchBase):
    """A 12V trigger output (t{n}T). Write-only (assumed state). Each write
    asserts RS-232 trigger mode (StE2); on main power-on the held state is
    re-applied, since the outputs come up off after a power cycle.
    """

    _attr_icon = "mdi:flash"
    _attr_assumed_state = True  # no device feedback for trigger state
    _attr_entity_category = None  # a real control (drives external gear), not config

    def __init__(self, client: AnthemClient, num: int, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self.num = num
        self._attr_name = f"Trigger {num}"
        self._attr_unique_id = f"{entry.data[CONF_ID]}_trigger{num}"
        self._attr_is_on = False  # optimistic; HA is the source of truth

    @callback
    def _handle_message(self, message: str) -> None:
        # Re-apply on main power-on — triggers reset to off after a power cycle.
        if message == "P1P1" and self._attr_is_on:
            self.hass.async_create_task(self._client.send(cmd_trigger(self.num, True)))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._client.send(cmd_trigger(self.num, True))
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._client.send(cmd_trigger(self.num, False))
        self._attr_is_on = False
        self.async_write_ha_state()
