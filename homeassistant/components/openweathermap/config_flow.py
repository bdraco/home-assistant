"""Config flow for OpenWeatherMap."""

from __future__ import annotations

from pyopenweathermap import OWMClient, RequestError
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_API_KEY,
    CONF_LANGUAGE,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_NAME,
)
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv

from .const import (
    CONFIG_FLOW_VERSION,
    DEFAULT_LANGUAGE,
    DEFAULT_NAME,
    DOMAIN,
    LANGUAGES,
)


class OpenWeatherMapConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for OpenWeatherMap."""

    VERSION = CONFIG_FLOW_VERSION

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OpenWeatherMapOptionsFlow:
        """Get the options flow for this handler."""
        return OpenWeatherMapOptionsFlow(config_entry)

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        errors = {}

        if user_input is not None:
            latitude = user_input[CONF_LATITUDE]
            longitude = user_input[CONF_LONGITUDE]

            await self.async_set_unique_id(f"{latitude}-{longitude}")
            self._abort_if_unique_id_configured()

            api_key_valid = None
            try:
                api_key_valid = await _is_owm_api_key_valid(user_input[CONF_API_KEY])
            except RequestError:
                errors["base"] = "cannot_connect"

            if api_key_valid is False:
                errors["base"] = "invalid_api_key"

            if not errors:
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data=user_input
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): str,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Optional(
                    CONF_LATITUDE, default=self.hass.config.latitude
                ): cv.latitude,
                vol.Optional(
                    CONF_LONGITUDE, default=self.hass.config.longitude
                ): cv.longitude,
                vol.Optional(CONF_LANGUAGE, default=DEFAULT_LANGUAGE): vol.In(
                    LANGUAGES
                ),
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


class OpenWeatherMapOptionsFlow(OptionsFlow):
    """Handle options."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self._get_options_schema(),
        )

    def _get_options_schema(self):
        return vol.Schema(
            {
                vol.Optional(
                    CONF_LANGUAGE,
                    default=self.config_entry.options.get(
                        CONF_LANGUAGE,
                        self.config_entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
                    ),
                ): vol.In(LANGUAGES),
            }
        )


async def _is_owm_api_key_valid(api_key):
    owm_client = OWMClient(api_key)
    return await owm_client.validate_key()
