"""Diagnostics support for the Dayton Audio DAX88 integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from .coordinator import Dax88Coordinator

TO_REDACT = {CONF_HOST}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a DAX88 config entry."""

    coordinator: Dax88Coordinator = entry.runtime_data
    state = coordinator.data
    client = coordinator.client

    data: dict[str, Any] = {
        "entry": {
            "title": entry.title,
            CONF_HOST: entry.data.get(CONF_HOST),
            CONF_PORT: entry.data.get(CONF_PORT),
        },
        "connection": {
            "connected": client.connected,
            "last_update_success": coordinator.last_update_success,
        },
        "device_name": state.device_name if state else None,
        "config": {
            "zones": state.config.zones if state and state.config else [],
            "sources": state.config.sources if state and state.config else [],
            "raw_names": state.config.raw_names if state and state.config else [],
        },
        "zones": [_zone_diagnostics(zone) for zone in state.zones] if state else [],
        "last_frames": client.diagnostics(),
    }
    return async_redact_data(data, TO_REDACT)


def _zone_diagnostics(zone) -> dict[str, Any]:
    """Return parsed and raw diagnostics for one zone."""

    return {
        "zone": zone.zone,
        "name": zone.name,
        "source": zone.source,
        "source_name": zone.source_name,
        "volume": zone.volume,
        "treble": zone.treble,
        "bass": zone.bass,
        "balance": zone.balance,
        "power_on": zone.power_on,
        "muted": zone.muted,
        "raw": {
            "source": zone.source_raw,
            "volume": zone.volume_raw,
            "treble": zone.treble_raw,
            "bass": zone.bass_raw,
            "balance": zone.balance_raw,
            "power": zone.power_raw,
            "mute": zone.mute_raw,
        },
    }