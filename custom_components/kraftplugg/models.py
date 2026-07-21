"""Data models for KraftPlugg."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class KraftPluggCredentials:
    """Authentication credentials returned by Mitt Hjem."""

    access_token: str
    refresh_token: str


@dataclass(frozen=True, slots=True)
class KraftPluggLocation:
    """A meter location available to the signed-in account."""

    meter_id: str
    meter_point_id: str
    name: str


@dataclass(frozen=True, slots=True)
class KraftPluggData:
    """Latest values exposed to Home Assistant."""

    power_w: float | None = None
    power_read_time: datetime | None = None
    energy_today_kwh: float | None = None
    reader_temperature_c: float | None = None
    last_seen: datetime | None = None
