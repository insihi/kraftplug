"""Data coordinator for KraftPlugg."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import logging
from time import monotonic

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import KraftPluggApiClient, KraftPluggAuthError, KraftPluggError
from .const import (
    DOMAIN,
    SCAN_INTERVAL,
    SLOW_REFRESH_INTERVAL,
    STREAM_RECONNECT_DELAY,
    STREAM_RECONNECT_MAX_DELAY,
    STREAM_UPDATE_INTERVAL,
)
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
        self._last_slow_refresh = 0.0
        self._slow_refresh_lock = asyncio.Lock()
        self._last_stream_update = 0.0

    async def _async_update_data(self) -> KraftPluggData:
        previous = self.data or KraftPluggData()
        try:
            power_w, power_read_time = await self.client.async_get_power()
            data = replace(
                previous,
                power_w=power_w,
                power_read_time=power_read_time,
            )
            return await self._async_refresh_slow_data(data)
        except KraftPluggAuthError as err:
            raise ConfigEntryAuthFailed from err
        except KraftPluggError as err:
            raise UpdateFailed(str(err)) from err

    async def async_listen(self) -> None:
        """Listen for live power and reconnect after transient failures."""
        reconnect_delay = STREAM_RECONNECT_DELAY
        while True:
            received_data = False
            try:
                async for power_w, power_read_time in self.client.async_stream_power():
                    previous = self.data or KraftPluggData()
                    if (
                        power_read_time is not None
                        and previous.power_read_time is not None
                        and power_read_time < previous.power_read_time
                    ):
                        continue
                    if monotonic() - self._last_stream_update < STREAM_UPDATE_INTERVAL:
                        continue
                    received_data = True
                    reconnect_delay = STREAM_RECONNECT_DELAY
                    self._last_stream_update = monotonic()
                    data = replace(
                        previous,
                        power_w=power_w,
                        power_read_time=power_read_time,
                    )
                    data = await self._async_refresh_slow_data(data)
                    self.async_set_updated_data(data)
            except asyncio.CancelledError:
                raise
            except KraftPluggAuthError as err:
                _LOGGER.debug("KraftPlugg live stream authentication failed: %s", err)
            except KraftPluggError as err:
                _LOGGER.debug("KraftPlugg live stream disconnected: %s", err)

            if received_data:
                reconnect_delay = STREAM_RECONNECT_DELAY
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(
                reconnect_delay * 2,
                STREAM_RECONNECT_MAX_DELAY,
            )

    async def _async_refresh_slow_data(
        self, data: KraftPluggData
    ) -> KraftPluggData:
        """Refresh low-frequency values at most once every five minutes."""
        interval = SLOW_REFRESH_INTERVAL.total_seconds()
        if monotonic() - self._last_slow_refresh < interval:
            return data

        async with self._slow_refresh_lock:
            if monotonic() - self._last_slow_refresh < interval:
                return data
            results = await asyncio.gather(
                self.client.async_get_energy_today(),
                self.client.async_get_temperature(),
                self.client.async_get_last_seen(),
                return_exceptions=True,
            )
            self._last_slow_refresh = monotonic()

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
