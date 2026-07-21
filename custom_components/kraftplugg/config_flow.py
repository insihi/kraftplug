"""Config flow for KraftPlugg."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    KraftPluggApiClient,
    KraftPluggAuthError,
    KraftPluggAuthenticator,
    KraftPluggConnectionError,
    KraftPluggError,
    KraftPluggValidationError,
)
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_LOCATION_NAME,
    CONF_METER_ID,
    CONF_METER_POINT_ID,
    CONF_PHONE,
    CONF_REFRESH_TOKEN,
    CONF_SMS_CODE,
    DOMAIN,
)
from .models import KraftPluggCredentials, KraftPluggLocation


class KraftPluggConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a KraftPlugg config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._account: dict[str, Any] | None = None
        self._phone: str | None = None
        self._credentials: KraftPluggCredentials | None = None
        self._locations: list[KraftPluggLocation] = []
        self._reauth_entry: ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer normal sign-in or a one-time app-session import."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["phone", "session"],
        )

    async def async_step_phone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Request a code for the Mitt Hjem phone number."""
        errors: dict[str, str] = {}
        suggested_phone = ""
        if self._reauth_entry:
            suggested_phone = str(self._reauth_entry.data.get(CONF_PHONE, ""))

        if user_input is not None:
            self._phone = str(user_input[CONF_PHONE])
            authenticator = KraftPluggAuthenticator(async_get_clientsession(self.hass))
            try:
                self._account = await authenticator.async_check_phone(self._phone)
            except KraftPluggValidationError:
                errors["base"] = "invalid_phone"
            except KraftPluggConnectionError:
                errors["base"] = "cannot_connect"
            except KraftPluggError:
                errors["base"] = "unknown"
            else:
                return await self.async_step_sms()

        return self.async_show_form(
            step_id="phone",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PHONE,
                        default=suggested_phone,
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEL,
                            autocomplete="tel",
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_sms(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Verify the SMS code and discover meter locations."""
        errors: dict[str, str] = {}
        if user_input is not None and self._account is not None:
            authenticator = KraftPluggAuthenticator(async_get_clientsession(self.hass))
            try:
                credentials = await authenticator.async_verify_sms(
                    str(user_input[CONF_SMS_CODE]), self._account
                )
                client = KraftPluggApiClient(
                    async_get_clientsession(self.hass),
                    credentials,
                    meter_id="",
                    meter_point_id="",
                    time_zone=self.hass.config.time_zone,
                )
                locations = await client.async_fetch_locations()
            except KraftPluggValidationError:
                errors["base"] = "invalid_code"
            except KraftPluggConnectionError:
                errors["base"] = "cannot_connect"
            except KraftPluggAuthError:
                errors["base"] = "invalid_auth"
            except KraftPluggError:
                errors["base"] = "unknown"
            else:
                if not locations:
                    return self.async_abort(reason="no_devices")
                self._credentials = client.credentials
                self._locations = locations
                if self._reauth_entry:
                    current_meter = str(
                        self._reauth_entry.data.get(CONF_METER_ID, "")
                    )
                    if location := next(
                        (item for item in locations if item.meter_id == current_meter),
                        None,
                    ):
                        return await self._async_finish(location)
                if len(locations) == 1:
                    return await self._async_finish(locations[0])
                return await self.async_step_location()

        return self.async_show_form(
            step_id="sms",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SMS_CODE): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="one-time-code",
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_location(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose when an account has multiple meters."""
        if user_input is not None:
            selected = str(user_input[CONF_METER_ID])
            location = next(item for item in self._locations if item.meter_id == selected)
            return await self._async_finish(location)

        options = {item.meter_id: item.name for item in self._locations}
        return self.async_show_form(
            step_id="location",
            data_schema=vol.Schema({vol.Required(CONF_METER_ID): vol.In(options)}),
        )

    async def async_step_session(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Import credentials from an already authenticated Mitt Hjem session."""
        errors: dict[str, str] = {}
        if user_input is not None:
            credentials = KraftPluggCredentials(
                access_token=str(user_input[CONF_ACCESS_TOKEN]),
                refresh_token=str(user_input[CONF_REFRESH_TOKEN]),
            )
            latest_credentials = credentials

            def token_updated(updated: KraftPluggCredentials) -> None:
                nonlocal latest_credentials
                latest_credentials = updated

            client = KraftPluggApiClient(
                async_get_clientsession(self.hass),
                credentials,
                meter_id=str(user_input[CONF_METER_ID]),
                meter_point_id=str(user_input[CONF_METER_POINT_ID]),
                time_zone=self.hass.config.time_zone,
                token_updated=token_updated,
            )
            try:
                await client.async_validate()
            except KraftPluggAuthError:
                errors["base"] = "invalid_auth"
            except KraftPluggConnectionError:
                errors["base"] = "cannot_connect"
            except KraftPluggError:
                errors["base"] = "invalid_meter"
            else:
                self._credentials = latest_credentials
                location = KraftPluggLocation(
                    meter_id=client.meter_id,
                    meter_point_id=client.meter_point_id,
                    name=str(user_input.get(CONF_LOCATION_NAME) or "KraftPlugg"),
                )
                return await self._async_finish(location)

        secret_selector = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
        return self.async_show_form(
            step_id="session",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ACCESS_TOKEN): secret_selector,
                    vol.Required(CONF_REFRESH_TOKEN): secret_selector,
                    vol.Required(CONF_METER_ID): str,
                    vol.Required(CONF_METER_POINT_ID): str,
                    vol.Optional(
                        CONF_LOCATION_NAME, default="KraftPlugg"
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication for an expired Mitt Hjem session."""
        self._reauth_entry = self._get_reauth_entry()
        return await self.async_step_phone()

    async def _async_finish(
        self, location: KraftPluggLocation
    ) -> ConfigFlowResult:
        """Create or update the config entry."""
        if self._credentials is None:
            return self.async_abort(reason="invalid_auth")

        data = {
            CONF_ACCESS_TOKEN: self._credentials.access_token,
            CONF_REFRESH_TOKEN: self._credentials.refresh_token,
            CONF_METER_ID: location.meter_id,
            CONF_METER_POINT_ID: location.meter_point_id,
            CONF_LOCATION_NAME: location.name,
        }
        if self._phone:
            data[CONF_PHONE] = self._phone

        if self._reauth_entry:
            return self.async_update_reload_and_abort(
                self._reauth_entry,
                data_updates=data,
            )

        await self.async_set_unique_id(location.meter_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=location.name, data=data)
