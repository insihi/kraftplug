"""Sensor entities for KraftPlugg."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KraftPluggCoordinator
from .entity import KraftPluggEntity
from .models import KraftPluggData


@dataclass(frozen=True, kw_only=True)
class KraftPluggSensorDescription(SensorEntityDescription):
    """Describe a KraftPlugg sensor."""

    value_fn: Callable[[KraftPluggData], Any]


SENSORS: tuple[KraftPluggSensorDescription, ...] = (
    KraftPluggSensorDescription(
        key="power",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        value_fn=lambda data: data.power_w,
    ),
    KraftPluggSensorDescription(
        key="energy_today",
        translation_key="energy_today",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=3,
        value_fn=lambda data: data.energy_today_kwh,
    ),
    KraftPluggSensorDescription(
        key="reader_temperature",
        translation_key="reader_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.reader_temperature_c,
    ),
    KraftPluggSensorDescription(
        key="last_seen",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.last_seen,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up KraftPlugg sensors from a config entry."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        KraftPluggSensor(coordinator, description) for description in SENSORS
    )


class KraftPluggSensor(KraftPluggEntity, SensorEntity):
    """A value reported by KraftPlugg."""

    entity_description: KraftPluggSensorDescription

    def __init__(
        self,
        coordinator: KraftPluggCoordinator,
        description: KraftPluggSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | datetime | None:
        """Return the latest sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)
