"""Config flow for Hunter Douglas PowerView integration."""
import logging

from aiopvapi.helpers.aiorequest import AioRequest
from aiopvapi.hub import Hub
import async_timeout
import voluptuous as vol

from homeassistant import config_entries, core, exceptions
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN  # pylint:disable=unused-import

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})


async def validate_input(hass: core.HomeAssistant, data):
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.
    """

    hub_address = data[CONF_HOST]
    websession = async_get_clientsession(hass)

    pv_request = AioRequest(hub_address, loop=hass.loop, websession=websession)
    hub = Hub(pv_request)

    async with async_timeout.timeout(10):
        await hub.query_user_data()
    if not hub.ip:
        raise CannotConnect

    # Return info that you want to store in the config entry.
    return {"title": hub.name}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hunter Douglas PowerView."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self):
        """Initialize the powerview config flow."""
        self.powerview_config = {}

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            if self._host_already_configured(user_input[CONF_HOST]):
                return self.async_abort(reason="already_configured")
            try:
                info = await validate_input(self.hass, user_input)

                return self.async_create_entry(title=info["title"], data=user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_import(self, user_input=None):
        """Handle the initial step."""
        return await self.async_step_user(user_input)

    async def async_step_homekit(self, homekit_info):
        """Handle HomeKit discovery."""
        if self._async_current_entries():
            # We can see rachio on the network to tell them to configure
            # it, but since the device will not give up the account it is
            # bound to and there can be multiple rachio systems on a single
            # account, we avoid showing the device as discovered once
            # they already have one configured as they can always
            # add a new one via "+"
            return self.async_abort(reason="already_configured")
        properties = {
            key.lower(): value for (key, value) in homekit_info["properties"].items()
        }
        if self._host_already_configured(homekit_info["host"]):
            return self.async_abort(reason="already_configured")
        await self.async_set_unique_id(properties["id"])

        self.powerview_config = {
            CONF_HOST: homekit_info["host"],
            CONF_NAME: homekit_info["name"],
        }
        return await self.async_step_link()

    async def async_step_link(self, user_input=None):
        """Attempt to link with the Harmony."""
        errors = {}

        if user_input is not None:
            return await self.async_step_user(self.powerview_config)

        return self.async_show_form(
            step_id="link",
            errors=errors,
            description_placeholders=self.powerview_config,
        )

    def _host_already_configured(self, host):
        """See if we already have a hub with the host address configured."""
        existing_hosts = {
            entry.data[CONF_HOST] for entry in self._async_current_entries()
        }
        return host in existing_hosts


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""
