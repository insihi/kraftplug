"""Shared KraftPlugg entity helpers."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import KraftPluggCoordinator


class KraftPluggEntity(CoordinatorEntity[KraftPluggCoordinator]):
    """Base entity tied to one KraftPlugg reader."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KraftPluggCoordinator, key: str) -> None:
        super().__init__(coordinator)
        meter_id = coordinator.client.meter_id
        self._attr_unique_id = f"{meter_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, meter_id)},
            manufacturer="Haugaland Kraft",
            model="KraftPlugg",
            name=coordinator.config_entry.title,
        )
