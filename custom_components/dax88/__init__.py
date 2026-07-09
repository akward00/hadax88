"""Home Assistant integration for Dayton Audio DAX88 matrix amplifiers."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .client import Dax88Client, Dax88Error
from .const import DEFAULT_PORT, DOMAIN, PLATFORMS
from .coordinator import Dax88Coordinator

Dax88ConfigEntry = ConfigEntry[Dax88Coordinator]


async def async_setup_entry(hass: HomeAssistant, entry: Dax88ConfigEntry) -> bool:
    """Set up DAX88 from a config entry."""

    client = Dax88Client(
        entry.data[CONF_HOST],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
    )
    coordinator = Dax88Coordinator(hass, entry, client)

    try:
        await coordinator.async_config_entry_first_refresh()
    except Dax88Error as err:
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: Dax88ConfigEntry) -> bool:
    """Unload a DAX88 config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok
