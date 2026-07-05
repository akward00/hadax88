"""Media player entities for DAX88 zones."""

from __future__ import annotations

from homeassistant.components.media_player import MediaPlayerEntity, MediaPlayerEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MAX_VOLUME
from .coordinator import Dax88Coordinator
from .protocol import ZoneStatus

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.SELECT_SOURCE
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DAX88 media players."""

    coordinator: Dax88Coordinator = entry.runtime_data
    zones = coordinator.data.zones if coordinator.data else []
    async_add_entities(Dax88ZoneMediaPlayer(coordinator, entry, status.zone) for status in zones)


class Dax88ZoneMediaPlayer(CoordinatorEntity[Dax88Coordinator], MediaPlayerEntity):
    """A DAX88 zone exposed as a media player."""

    _attr_supported_features = SUPPORTED_FEATURES
    _attr_has_entity_name = False

    def __init__(self, coordinator: Dax88Coordinator, entry: ConfigEntry, zone: int) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._zone = zone
        initial = coordinator.zone(zone)
        name = initial.name if initial else f"Zone {zone}"
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_zone_{zone}"

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
    def _status(self) -> ZoneStatus | None:
        return self.coordinator.zone(self._zone)

    @property
    def state(self) -> str | None:
        """Return whether the zone is on."""

        status = self._status
        if status is None:
            return None
        return STATE_ON if status.power_on else STATE_OFF

    @property
    def volume_level(self) -> float | None:
        """Return volume as Home Assistant 0.0..1.0."""

        status = self._status
        if status is None:
            return None
        return status.volume / MAX_VOLUME

    @property
    def is_volume_muted(self) -> bool | None:
        """Return mute state."""

        status = self._status
        return None if status is None else status.muted

    @property
    def source(self) -> str | None:
        """Return the current source name."""

        status = self._status
        return None if status is None else status.source_name

    @property
    def source_list(self) -> list[str] | None:
        """Return configured source names."""

        config = self.coordinator.data.config if self.coordinator.data else None
        return config.sources if config else None

    async def async_turn_on(self) -> None:
        """Turn the zone on."""

        await self.coordinator.async_send_and_refresh(self._zone, "power", True)

    async def async_turn_off(self) -> None:
        """Turn the zone off."""

        await self.coordinator.async_send_and_refresh(self._zone, "power", False)

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute the zone."""

        await self.coordinator.async_send_and_refresh(self._zone, "mute", mute)

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume from Home Assistant 0.0..1.0."""

        display_volume = round(max(0.0, min(1.0, volume)) * MAX_VOLUME)
        await self.coordinator.async_send_and_refresh(self._zone, "volume", display_volume)

    async def async_volume_up(self) -> None:
        """Raise zone volume by one display step."""

        status = self._status
        if status is None:
            return
        await self.coordinator.async_send_and_refresh(self._zone, "volume", min(MAX_VOLUME, status.volume + 1))

    async def async_volume_down(self) -> None:
        """Lower zone volume by one display step."""

        status = self._status
        if status is None:
            return
        await self.coordinator.async_send_and_refresh(self._zone, "volume", max(0, status.volume - 1))

    async def async_select_source(self, source: str) -> None:
        """Select a source by name."""

        config = self.coordinator.data.config if self.coordinator.data else None
        if config is None or source not in config.sources:
            return
        await self.coordinator.async_send_and_refresh(self._zone, "source", config.sources.index(source) + 1)
