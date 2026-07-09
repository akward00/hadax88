"""Connectivity sensor for the Dayton Audio DAX88 integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Dax88Coordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DAX88 binary sensors."""

    coordinator: Dax88Coordinator = entry.runtime_data
    async_add_entities([Dax88ConnectionBinarySensor(coordinator, entry)])


class Dax88ConnectionBinarySensor(CoordinatorEntity[Dax88Coordinator], BinarySensorEntity):
    """Connection status for the DAX88 persistent socket."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_name = "Connection"

    def __init__(self, coordinator: Dax88Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_connection"

    @property
    def device_info(self) -> dict:
        """Return the parent DAX88 device info."""

        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "manufacturer": "Dayton Audio",
            "model": "DAX88",
            "name": self.coordinator.data.device_name if self.coordinator.data else self._entry.title,
        }

    @property
    def is_on(self) -> bool:
        """Return whether the DAX88 socket is connected."""

        return self.coordinator.client.connected and self.coordinator.last_update_success