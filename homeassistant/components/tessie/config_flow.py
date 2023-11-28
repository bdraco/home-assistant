"""Config Flow for Advantage Air integration."""
from __future__ import annotations

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from aiohttp import ClientConnectionError, ClientResponseError
from tessie_api import get_state_of_all_vehicles
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN

TESSIE_SCHEMA = vol.Schema({vol.Required(CONF_API_KEY): str})


class TessieConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config Tessie API connection."""

    VERSION = 1
    DOMAIN = DOMAIN

    def __init__(self) -> None:
        """Initialize."""
        self._reauth_entry: ConfigEntry | None = None

    async def async_step_user(
        self, user_input: Mapping[str, Any] | None = None
    ) -> FlowResult:
        """Get configuration from the user."""
        errors = {}
        if user_input and CONF_API_KEY in user_input:
            try:
                await get_state_of_all_vehicles(
                    session=async_get_clientsession(self.hass),
                    api_key=user_input[CONF_API_KEY],
                )
            except ClientResponseError as e:
                if e.status == HTTPStatus.FORBIDDEN:
                    errors["base"] = "invalid_api_key"
                else:
                    errors["base"] = "unknown"
            except ClientConnectionError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(user_input[CONF_API_KEY])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="Tessie",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=TESSIE_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(self, user_input: Mapping[str, Any]) -> FlowResult:
        """Handle re-auth."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: Mapping[str, Any] | None = None
    ) -> FlowResult:
        """Get update API Key from the user."""
        errors = {}
        assert self._reauth_entry
        if user_input and CONF_API_KEY in user_input:
            try:
                await get_state_of_all_vehicles(
                    session=async_get_clientsession(self.hass),
                    api_key=user_input[CONF_API_KEY],
                )
            except ClientResponseError as e:
                if e.status == HTTPStatus.FORBIDDEN:
                    errors["base"] = "invalid_api_key"
                else:
                    errors["base"] = "unknown"
            except ClientConnectionError:
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry, data=user_input
                )
                self.hass.async_create_task(
                    self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                )
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=TESSIE_SCHEMA,
            errors=errors,
        )
