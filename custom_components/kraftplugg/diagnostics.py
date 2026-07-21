"""Diagnostics for KraftPlugg."""

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from . import KraftPluggConfigEntry


def _mask(value: str) -> str:
    """Mask an identifier while leaving it useful for comparison."""
    return f"***{value[-4:]}" if len(value) > 4 else "***"


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: KraftPluggConfigEntry
) -> dict[str, Any]:
    """Return diagnostics without credentials or full meter identifiers."""
    return {
        "title": entry.title,
        "meter_id": _mask(entry.runtime_data.client.meter_id),
        "meter_point_id": _mask(entry.runtime_data.client.meter_point_id),
        "data": asdict(entry.runtime_data.coordinator.data),
    }
