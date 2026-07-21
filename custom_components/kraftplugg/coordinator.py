"""Data coordinator for KraftPlugg."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import KraftPluggApiClient, KraftPluggAuthError, KraftPluggError
from .const import DOMAIN, SCAN_INTERVAL, SLOW_REFRESH_CYCLES
from .models import KraftPluggData

_LOGGER = logging.getLogger(__name__)


class KraftPluggCoordinator(DataUpdateCoordinator[KraftPluggData]):
    """Fetch KraftPlugg data and share it between entities."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: KraftPluggApiClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self._cycles_since_slow_refresh = SLOW_REFRESH_CYCLES

    async def _async_update_data(self) -> KraftPluggData:
        previous = self.data or KraftPluggData()
        try:
            power_w, power_read_time = await self.client.async_get_power()
            data = replace(
                previous,
                power_w=power_w,
                power_read_time=power_read_time,
            )

            if self._cycles_since_slow_refresh < SLOW_REFRESH_CYCLES:
                self._cycles_since_slow_refresh += 1
                return data

            self._cycles_since_slow_refresh = 0
            results = await asyncio.gather(
                self.client.async_get_energy_today(),
                self.client.async_get_temperature(),
                self.client.async_get_last_seen(),
                return_exceptions=True,
            )
            fields = ("energy_today_kwh", "reader_temperature_c", "last_seen")
            updates = {}
            for field, result in zip(fields, results, strict=True):
                if isinstance(result, KraftPluggAuthError):
                    raise result
                if isinstance(result, Exception):
                    _LOGGER.debug("Could not update %s: %s", field, result)
                    continue
                updates[field] = result
            return replace(data, **updates)
        except KraftPluggAuthError as err:
            raise ConfigEntryAuthFailed from err
        except KraftPluggError as err:
            raise UpdateFailed(str(err)) from err
