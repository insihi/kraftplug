"""Constants for the KraftPlugg integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "kraftplugg"
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]

CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_PHONE = "phone"
CONF_SMS_CODE = "sms_code"
CONF_METER_ID = "meter_id"
CONF_METER_POINT_ID = "meter_point_id"
CONF_LOCATION_NAME = "location_name"

PROVIDER_ID = 2
# Public client identifier used by the official Mitt Hjem app, not a user secret.
API_KEY = "AIzaSyBx0UsO89VrVJ7hvp87OFNZ-QGrtVJsMc4"
ACCESS_API_URL = "https://access.api.hkraft.no/api"
MY_HOME_URL = "https://myhome.api.hkraft.no"
STROMME_URL = "https://stromme.hkraft.run"
REFRESH_COOKIE_NAME = "__Host-__refresh_token_app_hkraft__"

APP_VERSION = "39.3.0"
APP_BUILD_VERSION = "1234568215"
REQUEST_TIMEOUT = 20
SCAN_INTERVAL = timedelta(seconds=30)
SLOW_REFRESH_CYCLES = 10
