"""Number entities for DAX88 tone and balance controls."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MAX_BALANCE, MAX_TONE, MIN_BALANCE, MIN_TONE
from .coordinator import Dax88Coordinator
from .protocol import ZoneStatus


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DAX88 number entities."""

    coordinator: Dax88Coordinator = entry.runtime_data
    zones = coordinator.data.zones if coordinator.data else []
    descriptions = [
        Dax88NumberDescription("bass", "Bass", MIN_TONE, MAX_TONE, lambda status: status.bass),
        Dax88NumberDescription("treble", "Treble", MIN_TONE, MAX_TONE, lambda status: status.treble),
        Dax88NumberDescription("balance", "Balance", MIN_BALANCE, MAX_BALANCE, lambda status: status.balance or 10),
    ]
    async_add_entities(
        Dax88ZoneNumber(coordinator, entry, status.zone, description)
        for status in zones
        for description in descriptions
    )


class Dax88NumberDescription:
    """Description for a DAX88 number entity."""

    def __init__(
        self,
        key: str,
        name: str,
        minimum: int,
        maximum: int,
        value_fn: Callable[[ZoneStatus], int],
    ) -> None:
        self.key = key
        self.name = name
        self.minimum = minimum
        self.maximum = maximum
        self.value_fn = value_fn


class Dax88ZoneNumber(CoordinatorEntity[Dax88Coordinator], NumberEntity):
    """Bass, treble, or balance for a DAX88 zone."""

    _attr_native_step = 1

    def __init__(
        self,
        coordinator: Dax88Coordinator,
        entry: ConfigEntry,
        zone: int,
        description: Dax88NumberDescription,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._zone = zone
        self._description = description
        status = coordinator.zone(zone)
        zone_name = status.name if status else f"Zone {zone}"
        self._attr_name = f"{zone_name} {description.name}"
        self._attr_unique_id = f"{entry.entry_id}_zone_{zone}_{description.key}"
        self._attr_native_min_value = description.minimum
        self._attr_native_max_value = description.maximum

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
    def native_value(self) -> int | None:
        """Return the current number value."""

        status = self.coordinator.zone(self._zone)
        if status is None:
            return None
        return self._description.value_fn(status)

    async def async_set_native_value(self, value: float) -> None:
        """Set the DAX88 number value."""

        int_value = round(value)
        int_value = max(self._description.minimum, min(self._description.maximum, int_value))
        await self.coordinator.async_send(self._zone, self._description.key, int_value)
