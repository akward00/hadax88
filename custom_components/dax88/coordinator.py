"""Coordinator for DAX88 polling."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import Dax88Client, Dax88Error, with_retries
from .const import DEFAULT_UPDATE_INTERVAL, DOMAIN
from .protocol import DaxState, ZoneStatus

_LOGGER = logging.getLogger(__name__)


class Dax88Coordinator(DataUpdateCoordinator[DaxState]):
    """Poll DAX88 status and provide command helpers."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: Dax88Client) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_UPDATE_INTERVAL),
        )
        self.client = client

    async def _async_update_data(self) -> DaxState:
        try:
            return await with_retries(self.client.query)
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

    async def async_send_and_refresh(self, zone: int, command: str, value: int | bool) -> None:
        """Send a command, then refresh status immediately."""

        await self.client.send(zone, command, value)
        await self.async_request_refresh()
