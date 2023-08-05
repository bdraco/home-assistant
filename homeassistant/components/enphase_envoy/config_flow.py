"""Config flow for Enphase Envoy integration."""
from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from awesomeversion import AwesomeVersion
from pyenphase import (
    Envoy,
    EnvoyAuthenticationError,
    EnvoyAuthenticationRequired,
    EnvoyError,
)
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import zeroconf
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.util.network import is_ipv4_address

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

ENVOY = "Envoy"

CONF_SERIAL = "serial"

INVALID_AUTH_ERRORS = (EnvoyAuthenticationError, EnvoyAuthenticationRequired)

INSTALLER_AUTH_LAST_WORKING_VERSION = AwesomeVersion("7.0.0")
INSTALLER_AUTH_USERNAME = "installer"


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> Envoy:
    """Validate the user input allows us to connect."""
    envoy = Envoy(data[CONF_HOST], get_async_client(hass))
    await envoy.setup()
    await envoy.authenticate(data[CONF_USERNAME], data[CONF_PASSWORD])
    return envoy


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Enphase Envoy."""

    VERSION = 1

    def __init__(self):
        """Initialize an envoy flow."""
        self.ip_address = None
        self.username = None
        self.protovers: str | None = None
        self._reauth_entry = None

    @callback
    def _async_generate_schema(self) -> vol.Schema:
        """Generate schema."""
        schema = {}

        if self.ip_address:
            schema[vol.Required(CONF_HOST, default=self.ip_address)] = vol.In(
                [self.ip_address]
            )
        else:
            schema[vol.Required(CONF_HOST)] = str

        default_username = ""
        if (
            not self.username
            and self.protovers
            and AwesomeVersion(self.protovers) < INSTALLER_AUTH_LAST_WORKING_VERSION
        ):
            default_username = INSTALLER_AUTH_USERNAME

        schema[
            vol.Optional(CONF_USERNAME, default=self.username or default_username)
        ] = str
        schema[vol.Optional(CONF_PASSWORD, default="")] = str

        return vol.Schema(schema)

    @callback
    def _async_current_hosts(self) -> set[str]:
        """Return a set of hosts."""
        return {
            entry.data[CONF_HOST]
            for entry in self._async_current_entries(include_ignore=False)
            if CONF_HOST in entry.data
        }

    async def async_step_zeroconf(
        self, discovery_info: zeroconf.ZeroconfServiceInfo
    ) -> FlowResult:
        """Handle a flow initialized by zeroconf discovery."""
        if not is_ipv4_address(discovery_info.host):
            return self.async_abort(reason="not_ipv4_address")
        serial = discovery_info.properties["serialnum"]
        self.protovers = discovery_info.properties.get("protovers")
        await self.async_set_unique_id(serial)
        self.ip_address = discovery_info.host
        self._abort_if_unique_id_configured({CONF_HOST: self.ip_address})
        for entry in self._async_current_entries(include_ignore=False):
            if (
                entry.unique_id is None
                and CONF_HOST in entry.data
                and entry.data[CONF_HOST] == self.ip_address
            ):
                title = f"{ENVOY} {serial}" if entry.title == ENVOY else ENVOY
                self.hass.config_entries.async_update_entry(
                    entry, title=title, unique_id=serial
                )
                self.hass.async_create_task(
                    self.hass.config_entries.async_reload(entry.entry_id)
                )
                return self.async_abort(reason="already_configured")

        return await self.async_step_user()

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        """Handle configuration by re-auth."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_user()

    def _async_envoy_name(self) -> str:
        """Return the name of the envoy."""
        return f"{ENVOY} {self.unique_id}" if self.unique_id else ENVOY

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            if (
                not self._reauth_entry
                and user_input[CONF_HOST] in self._async_current_hosts()
            ):
                return self.async_abort(reason="already_configured")
            try:
                envoy = await validate_input(self.hass, user_input)
            except INVALID_AUTH_ERRORS:
                errors["base"] = "invalid_auth"
            except EnvoyError:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                data = user_input.copy()
                data[CONF_NAME] = self._async_envoy_name()

                if self._reauth_entry:
                    self.hass.config_entries.async_update_entry(
                        self._reauth_entry,
                        data=data,
                    )
                    return self.async_abort(reason="reauth_successful")

                if not self.unique_id:
                    await self.async_set_unique_id(envoy.serial_number)
                    data[CONF_NAME] = self._async_envoy_name()

                if self.unique_id:
                    self._abort_if_unique_id_configured({CONF_HOST: data[CONF_HOST]})

                return self.async_create_entry(title=data[CONF_NAME], data=data)

        if self.unique_id:
            self.context["title_placeholders"] = {
                CONF_SERIAL: self.unique_id,
                CONF_HOST: self.ip_address,
            }

        return self.async_show_form(
            step_id="user",
            data_schema=self._async_generate_schema(),
            errors=errors,
        )
