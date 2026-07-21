"""Haugaland Kraft KraftPlugg integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import KraftPluggApiClient
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_METER_ID,
    CONF_METER_POINT_ID,
    CONF_REFRESH_TOKEN,
    PLATFORMS,
)
from .coordinator import KraftPluggCoordinator
from .models import KraftPluggCredentials


@dataclass(slots=True)
class KraftPluggRuntimeData:
    """Runtime objects associated with a config entry."""

    client: KraftPluggApiClient
    coordinator: KraftPluggCoordinator


KraftPluggConfigEntry = ConfigEntry[KraftPluggRuntimeData]


async def async_setup_entry(
    hass: HomeAssistant, entry: KraftPluggConfigEntry
) -> bool:
    """Set up KraftPlugg from a config entry."""

    def token_updated(credentials: KraftPluggCredentials) -> None:
        if (
            entry.data.get(CONF_ACCESS_TOKEN) == credentials.access_token
            and entry.data.get(CONF_REFRESH_TOKEN) == credentials.refresh_token
        ):
            return
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_ACCESS_TOKEN: credentials.access_token,
                CONF_REFRESH_TOKEN: credentials.refresh_token,
            },
        )

    client = KraftPluggApiClient(
        async_get_clientsession(hass),
        KraftPluggCredentials(
            access_token=str(entry.data[CONF_ACCESS_TOKEN]),
            refresh_token=str(entry.data[CONF_REFRESH_TOKEN]),
        ),
        meter_id=str(entry.data[CONF_METER_ID]),
        meter_point_id=str(entry.data[CONF_METER_POINT_ID]),
        time_zone=hass.config.time_zone,
        token_updated=token_updated,
    )
    coordinator = KraftPluggCoordinator(hass, entry, client)
    entry.runtime_data = KraftPluggRuntimeData(client, coordinator)
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(
        hass,
        coordinator.async_listen(),
        "KraftPlugg live power stream",
    )
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: KraftPluggConfigEntry
) -> bool:
    """Unload a KraftPlugg config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
