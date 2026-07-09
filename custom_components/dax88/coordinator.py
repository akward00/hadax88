"""Push coordinator for DAX88."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import Dax88Client, Dax88Error
from .const import DOMAIN
from .protocol import DaxState, ZoneStatus

_LOGGER = logging.getLogger(__name__)


class Dax88Coordinator(DataUpdateCoordinator[DaxState]):
    """Receive DAX88 state from the persistent push socket."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: Dax88Client) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
        )
        self.client = client
        self._started = False

    async def _async_update_data(self) -> DaxState:
        """Start the push socket and wait for initial config/status data."""

        try:
            if not self._started:
                await self.client.async_start(self._handle_state_update, self._handle_connection_update)
                self._started = True
            return await self.client.async_wait_ready()
        except Dax88Error as err:
            raise UpdateFailed(str(err)) from err

    def zone(self, zone: int) -> ZoneStatus | None:
        """Return current status for one zone."""

        if self.data is None:
            return None
        for status in self.data.zones:
            if status.zone == zone:
                return status
        return None

    async def async_send(self, zone: int, command: str, value: int | bool) -> None:
        """Send a command and let the socket echo/status update the coordinator."""

        await self.client.async_send(zone, command, value)

    async def async_shutdown(self) -> None:
        """Close the push socket."""

        await self.client.async_stop()

    def _handle_state_update(self, state: DaxState) -> None:
        self.async_set_updated_data(state)

    def _handle_connection_update(self, connected: bool) -> None:
        self.last_update_success = connected
        self.async_update_listeners()
