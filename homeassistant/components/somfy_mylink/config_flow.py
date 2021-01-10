"""Config flow for Somfy MyLink integration."""
import asyncio
import logging

from somfy_mylink_synergy import SomfyMyLinkSynergy
import voluptuous as vol

from homeassistant import config_entries, core, exceptions
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback

from .const import (
    CONF_REVERSE,
    CONF_REVERSED_TARGET_IDS,
    CONF_SYSTEM_ID,
    CONF_TARGET_ID,
    CONF_TARGET_NAME,
    DEFAULT_PORT,
    MYLINK_STATUS,
)
from .const import DOMAIN  # pylint:disable=unused-import

_LOGGER = logging.getLogger(__name__)

TARGET_CONFIG_VERSION = "target_config_version"

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_SYSTEM_ID): int,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
    }
)


async def validate_input(hass: core.HomeAssistant, data):
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    somfy_mylink = SomfyMyLinkSynergy(
        data[CONF_SYSTEM_ID], data[CONF_HOST], data[CONF_PORT]
    )

    try:
        status_info = await somfy_mylink.status_info()
    except asyncio.TimeoutError as ex:
        raise CannotConnect from ex

    if not status_info or "error" in status_info:
        raise InvalidAuth

    return {"title": f"MyLink {data[CONF_HOST]}"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Somfy MyLink."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_ASSUMED

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
            )

        if self._host_already_configured(user_input[CONF_HOST]):
            return self.async_abort(reason="already_configured")

        try:
            info = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_import(self, user_input):
        """Handle import."""
        if self._host_already_configured(user_input[CONF_HOST]):
            return self.async_abort(reason="already_configured")

        return await self.async_step_user(user_input)

    def _host_already_configured(self, host):
        """See if we already have an entry matching the host."""
        for entry in self._async_current_entries():
            if entry.data[CONF_HOST] == host:
                return True
        return False

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle a option flow for somfy_mylink."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        """Initialize options flow."""
        self.config_entry = config_entry
        self.options = config_entry.options.copy()
        self._target_id = None

    @callback
    def _async_callback_targets(self):
        """Return the list of targets."""
        return self.hass.data[DOMAIN][self.config_entry.entry_id][MYLINK_STATUS][
            "result"
        ]

    @callback
    def _async_get_target_name(self, target_id) -> None:
        """Find the name of a target in the api data."""
        mylink_targets = self._async_callback_targets()
        for cover in mylink_targets:
            if cover["targetID"] == target_id:
                return cover["name"]
        raise KeyError

    async def async_step_init(self, user_input=None):
        """Handle options flow."""

        if self.config_entry.state != config_entries.ENTRY_STATE_LOADED:
            _LOGGER.error("MyLink must be connected to manage device options")
            return self.async_abort(reason="cannot_connect")

        if user_input is not None:
            target_id = user_input.get(CONF_TARGET_ID)
            if target_id:
                return await self.async_step_target_config(None, target_id)

            return self.async_create_entry(title="", data=self.options)

        cover_dict = {None: None}
        mylink_targets = self._async_callback_targets()
        if mylink_targets:
            for cover in mylink_targets:
                cover_dict[cover["targetID"]] = cover["name"]

        data_schema = vol.Schema({vol.Optional(CONF_TARGET_ID): vol.In(cover_dict)})

        return self.async_show_form(step_id="init", data_schema=data_schema, errors={})

    async def async_step_target_config(self, user_input=None, target_id=None):
        """Handle options flow for target."""
        reversed_target_ids = self.options.setdefault(CONF_REVERSED_TARGET_IDS, {})

        if user_input is not None:
            target_reversed = reversed_target_ids.get(self._target_id)
            if user_input[CONF_REVERSE] != target_reversed:
                reversed_target_ids[self._target_id] = user_input[CONF_REVERSE]
                # If we do not modify a top level key
                # the target config will never be written
                self.options.setdefault(TARGET_CONFIG_VERSION, 0)
                self.options[TARGET_CONFIG_VERSION] += 1
            return await self.async_step_init()

        self._target_id = target_id

        return self.async_show_form(
            step_id="target_config",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_REVERSE,
                        default=reversed_target_ids.get(target_id, False),
                    ): bool
                }
            ),
            description_placeholders={
                CONF_TARGET_NAME: self._async_get_target_name(target_id),
            },
            errors={},
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""
