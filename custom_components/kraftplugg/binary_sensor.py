"""Binary sensor entities for KraftPlugg."""

from datetime import UTC, datetime, timedelta

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KraftPluggCoordinator
from .entity import KraftPluggEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up KraftPlugg connectivity."""
    async_add_entities([KraftPluggConnectivity(entry.runtime_data.coordinator)])


class KraftPluggConnectivity(KraftPluggEntity, BinarySensorEntity):
    """Whether the reader has checked in recently."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "connectivity"

    def __init__(self, coordinator: KraftPluggCoordinator) -> None:
        super().__init__(coordinator, "connectivity")

    @property
    def is_on(self) -> bool | None:
        """Return true when the reader has supplied recent data."""
        latest_contact = max(
            (
                timestamp
                for timestamp in (
                    self.coordinator.data.last_seen,
                    self.coordinator.data.power_read_time,
                )
                if timestamp is not None
            ),
            default=None,
        )
        if latest_contact is None:
            return None
        return datetime.now(UTC) - latest_contact.astimezone(UTC) < timedelta(
            minutes=10
        )
