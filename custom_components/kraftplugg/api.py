"""Cloud API client for Haugaland Kraft KraftPlugg."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
import json
import logging
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

from .const import (
    ACCESS_API_URL,
    API_KEY,
    APP_BUILD_VERSION,
    APP_VERSION,
    MY_HOME_URL,
    PROVIDER_ID,
    REFRESH_COOKIE_NAME,
    REQUEST_TIMEOUT,
    STROMME_URL,
    STREAM_READ_TIMEOUT,
)
from .models import KraftPluggCredentials, KraftPluggLocation

_LOGGER = logging.getLogger(__name__)


class KraftPluggError(Exception):
    """Base error for the KraftPlugg API."""


class KraftPluggAuthError(KraftPluggError):
    """Authentication is invalid or expired."""


class KraftPluggConnectionError(KraftPluggError):
    """The KraftPlugg service could not be reached."""


class KraftPluggValidationError(KraftPluggError):
    """User input or an API response was invalid."""


def _normalise_phone(phone: str) -> str:
    """Return the Norwegian subscriber number expected by Mitt Hjem."""
    value = "".join(character for character in phone if character.isdigit())
    if value.startswith("0047"):
        value = value[4:]
    elif value.startswith("47") and len(value) == 10:
        value = value[2:]
    if value.startswith(("01", "02")):
        value = value[2:]
    if len(value) != 8:
        raise KraftPluggValidationError("Phone number must contain eight digits")
    return value


def _parse_datetime(value: Any) -> datetime | None:
    """Parse an API timestamp as a timezone-aware datetime."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _utc_iso(value: datetime) -> str:
    """Format a datetime for the KraftPlugg API."""
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _location_name(location: dict[str, Any]) -> str:
    """Build a useful private label for a meter location."""
    if name := location.get("name"):
        return str(name)
    address = location.get("address") or {}
    parts = [address.get("street"), address.get("city")]
    label = ", ".join(str(part) for part in parts if part)
    return label or "KraftPlugg"


def _parse_power_reading(
    payload: Any,
) -> tuple[float, datetime | None] | None:
    """Parse a live or historical power reading."""
    if not isinstance(payload, dict):
        return None
    power_values = payload.get("powerValues")
    if not isinstance(power_values, dict):
        return None
    value = power_values.get("activeImport")
    if value is None:
        return None
    try:
        power_w = float(value)
    except (TypeError, ValueError):
        return None
    return power_w, _parse_datetime(payload.get("readTime"))


class KraftPluggAuthenticator:
    """Handle Mitt Hjem phone and SMS authentication."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def async_check_phone(self, phone: str) -> dict[str, Any]:
        """Request an SMS code and return the account challenge."""
        phone = _normalise_phone(phone)
        payload = await self._request(
            "/Account/CheckPhone",
            {"providerId": PROVIDER_ID, "PhoneNumber": phone},
        )
        if payload.get("responseCode") != 100 or not payload.get("userId"):
            raise KraftPluggValidationError(
                str(payload.get("message") or "Phone number was not accepted")
            )
        payload["phoneNumber"] = phone
        return payload

    async def async_verify_sms(
        self, code: str, account: dict[str, Any]
    ) -> KraftPluggCredentials:
        """Exchange an SMS code for access and refresh credentials."""
        body = {
            "providerId": PROVIDER_ID,
            "Id": account["userId"],
            "Code": code.strip(),
            "PhoneNumber": account["phoneNumber"],
            "createRefreshToken": True,
            "refreshTokenInCookie": True,
            "tokenLifetime": "Long_Lifetime",
        }
        try:
            async with self._session.post(
                f"{ACCESS_API_URL}/Account/VerifySms",
                params={"key": API_KEY},
                json=body,
                headers=_common_headers(),
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                payload = await _response_json(response)
                if response.status != 200:
                    raise KraftPluggValidationError(
                        str(payload.get("message") or "The SMS code was not accepted")
                    )
                access_token = payload.get("accessToken")
                cookie = response.cookies.get(REFRESH_COOKIE_NAME)
                refresh_token = cookie.value if cookie else payload.get("refreshToken")
                if not access_token or not refresh_token:
                    raise KraftPluggAuthError("The login response did not contain credentials")
                return KraftPluggCredentials(str(access_token), str(refresh_token))
        except KraftPluggError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise KraftPluggConnectionError("Could not reach Mitt Hjem") from err

    async def _request(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            async with self._session.post(
                f"{ACCESS_API_URL}{path}",
                params={"key": API_KEY},
                json=body,
                headers=_common_headers(),
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                payload = await _response_json(response)
                if response.status != 200:
                    raise KraftPluggValidationError(
                        str(payload.get("message") or "Mitt Hjem rejected the request")
                    )
                return payload
        except KraftPluggError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise KraftPluggConnectionError("Could not reach Mitt Hjem") from err


class KraftPluggApiClient:
    """Authenticated API client for a single KraftPlugg meter."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        credentials: KraftPluggCredentials,
        meter_id: str,
        meter_point_id: str,
        time_zone: str = "Europe/Oslo",
        token_updated: Callable[[KraftPluggCredentials], None] | None = None,
    ) -> None:
        self._session = session
        self._access_token = credentials.access_token
        self._refresh_token = credentials.refresh_token
        self.meter_id = meter_id
        self.meter_point_id = meter_point_id
        self._time_zone = ZoneInfo(time_zone)
        self._token_updated = token_updated
        self._refresh_lock = asyncio.Lock()

    @property
    def credentials(self) -> KraftPluggCredentials:
        """Return the current credentials."""
        return KraftPluggCredentials(self._access_token, self._refresh_token)

    async def async_fetch_locations(self) -> list[KraftPluggLocation]:
        """Fetch all metered locations available to the account."""
        payload = await self._request_json("GET", f"{MY_HOME_URL}/v1/actors")
        locations: list[KraftPluggLocation] = []
        seen: set[str] = set()
        for actor in payload.get("actors") or []:
            for location in actor.get("locations") or []:
                meter_id = str(location.get("meterID") or "")
                meter_point_id = str(location.get("locationID") or "")
                if not meter_id or not meter_point_id or meter_id in seen:
                    continue
                seen.add(meter_id)
                locations.append(
                    KraftPluggLocation(
                        meter_id=meter_id,
                        meter_point_id=meter_point_id,
                        name=_location_name(location),
                    )
                )
        return locations

    async def async_validate(self) -> None:
        """Validate the session and selected meter."""
        payload = await self._han_request("exists")
        if not isinstance(payload, dict) or not payload.get("lastSeen"):
            raise KraftPluggValidationError("The selected KraftPlugg was not found")

    async def async_get_power(self) -> tuple[float | None, datetime | None]:
        """Return the latest active import in watts and its timestamp."""
        now = datetime.now(UTC)
        payload = await self._han_request(
            "power",
            {
                "from": _utc_iso(now - timedelta(minutes=10)),
                "resolution": "Minute",
                "maxvalues": 10,
            },
        )
        readings = payload.get("readings") if isinstance(payload, dict) else None
        if not readings:
            return None, None
        reading = max(
            readings,
            key=lambda item: _parse_datetime(item.get("readTime")) or datetime.min.replace(tzinfo=UTC),
        )
        return _parse_power_reading(reading) or (None, None)

    async def async_stream_power(
        self, *, allow_refresh: bool = True
    ) -> AsyncIterator[tuple[float, datetime | None]]:
        """Yield active-import readings from the KraftPlugg event stream."""
        request_token = self._access_token
        headers = {
            **_common_headers(),
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {request_token}",
            "Cache-Control": "no-cache",
            "MeterPointID": self.meter_point_id,
        }
        params = {
            "key": API_KEY,
            "meterid": self.meter_id,
        }
        timeout = aiohttp.ClientTimeout(
            total=None,
            sock_connect=REQUEST_TIMEOUT,
            sock_read=STREAM_READ_TIMEOUT,
        )
        try:
            async with self._session.get(
                f"{STROMME_URL}/v1/sse",
                params=params,
                headers=headers,
                timeout=timeout,
            ) as response:
                if response.status == 401 and allow_refresh:
                    await response.read()
                    await self._async_refresh_access_token(request_token)
                    async for reading in self.async_stream_power(allow_refresh=False):
                        yield reading
                    return
                if response.status in (401, 403):
                    await response.read()
                    raise KraftPluggAuthError("Mitt Hjem authentication expired")
                if response.status >= 400:
                    await response.read()
                    raise KraftPluggError(
                        f"KraftPlugg stream returned HTTP {response.status}"
                    )

                data_lines: list[str] = []
                async for raw_line in response.content:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if not line:
                        if reading := _parse_stream_event(data_lines):
                            yield reading
                        data_lines.clear()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())

                if reading := _parse_stream_event(data_lines):
                    yield reading
        except KraftPluggError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise KraftPluggConnectionError(
                "Could not receive live KraftPlugg data"
            ) from err

    async def async_get_energy_today(self) -> float | None:
        """Return imported energy since local midnight in kWh."""
        now_local = datetime.now(self._time_zone)
        midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        payload = await self._han_request("energy", {"from": _utc_iso(midnight)})
        readings = payload.get("readings") if isinstance(payload, dict) else None
        if readings is None:
            return None
        watt_hours = sum(
            float((reading.get("volumeValues") or {}).get("activeImport") or 0)
            for reading in readings
        )
        return round(watt_hours / 1000, 3)

    async def async_get_temperature(self) -> float | None:
        """Return the KraftPlugg reader temperature in Celsius."""
        payload = await self._han_request("temperature", {"maxvalues": 1})
        if not isinstance(payload, list) or not payload:
            return None
        value = payload[-1].get("averageTemperature")
        return round(float(value) / 100, 2) if value is not None else None

    async def async_get_last_seen(self) -> datetime | None:
        """Return when the KraftPlugg reader last contacted the service."""
        payload = await self._han_request("exists")
        return _parse_datetime(payload.get("lastSeen")) if isinstance(payload, dict) else None

    async def _han_request(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> Any:
        return await self._request_json(
            "GET",
            f"{STROMME_URL}/v1/{endpoint}",
            params={"meterid": self.meter_id, **(params or {})},
            meter_headers=True,
        )

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        meter_headers: bool = False,
        allow_refresh: bool = True,
    ) -> Any:
        request_token = self._access_token
        headers = {**_common_headers(), "Authorization": f"Bearer {request_token}"}
        if meter_headers:
            headers["MeterPointID"] = self.meter_point_id
        request_params = {"key": API_KEY, **(params or {})}
        try:
            async with self._session.request(
                method,
                url,
                params=request_params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                if response.status == 401 and allow_refresh:
                    await response.read()
                    await self._async_refresh_access_token(request_token)
                    return await self._request_json(
                        method,
                        url,
                        params=params,
                        meter_headers=meter_headers,
                        allow_refresh=False,
                    )
                if response.status in (401, 403):
                    await response.read()
                    raise KraftPluggAuthError("Mitt Hjem authentication expired")
                if response.status >= 400:
                    await response.read()
                    raise KraftPluggError(
                        f"KraftPlugg request returned HTTP {response.status}"
                    )
                return await response.json(content_type=None)
        except KraftPluggError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise KraftPluggConnectionError("Could not reach KraftPlugg") from err

    async def _async_refresh_access_token(self, failed_token: str) -> None:
        async with self._refresh_lock:
            if self._access_token != failed_token:
                return
            headers = {
                **_common_headers(),
                "Authorization": f"Bearer {self._access_token}",
                "Cookie": f"{REFRESH_COOKIE_NAME}={self._refresh_token}",
            }
            try:
                async with self._session.post(
                    f"{ACCESS_API_URL}/Account/Refresh",
                    params={"key": API_KEY},
                    json={"refreshTokenInCookie": True},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                ) as response:
                    payload = await _response_json(response)
                    if response.status != 200 or not payload.get("accessToken"):
                        raise KraftPluggAuthError("Mitt Hjem session could not be renewed")
                    self._access_token = str(payload["accessToken"])
                    if cookie := response.cookies.get(REFRESH_COOKIE_NAME):
                        self._refresh_token = cookie.value
                    if self._token_updated:
                        self._token_updated(self.credentials)
            except KraftPluggError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                raise KraftPluggConnectionError("Could not renew Mitt Hjem session") from err


def _common_headers() -> dict[str, str]:
    """Return the client metadata sent by the official app."""
    return {
        "HKOSType": "android",
        "HKOSVersion": "16",
        "HKSource": "app",
        "HKAppVersion": APP_VERSION,
        "HKAppBuildVersion": APP_BUILD_VERSION,
    }


def _parse_stream_event(
    data_lines: list[str],
) -> tuple[float, datetime | None] | None:
    """Parse one server-sent event without failing the stream."""
    if not data_lines:
        return None
    try:
        payload = json.loads("\n".join(data_lines))
    except (TypeError, ValueError):
        return None
    return _parse_power_reading(payload)


async def _response_json(response: aiohttp.ClientResponse) -> dict[str, Any]:
    """Read an API JSON object without trusting its content type."""
    try:
        payload = await response.json(content_type=None)
    except (aiohttp.ContentTypeError, ValueError):
        await response.read()
        return {}
    return payload if isinstance(payload, dict) else {}
