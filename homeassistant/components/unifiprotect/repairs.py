"""unifiprotect.repairs."""

from __future__ import annotations

from typing import cast

from aiohttp import CookieJar
from pyunifiprotect import ProtectApiClient
import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.issue_registry import async_get as async_get_issue_registry

from .const import (
    CONF_ALL_UPDATES,
    CONF_ALLOW_EA,
    CONF_OVERRIDE_CHOST,
    DEVICES_FOR_SUBSCRIBE,
)


class EAConfirm(RepairsFlow):
    """Handler for an issue fixing flow."""

    _hass: HomeAssistant
    _api: ProtectApiClient
    _entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, api: ProtectApiClient, entry: ConfigEntry
    ) -> None:
        """Create flow."""

        self._hass = hass
        self._api = api
        self._entry = entry
        super().__init__()

    @callback
    def _async_get_placeholders(self) -> dict[str, str] | None:
        issue_registry = async_get_issue_registry(self.hass)
        description_placeholders = None
        if issue := issue_registry.async_get_issue(self.handler, self.issue_id):
            description_placeholders = issue.translation_placeholders

        return description_placeholders

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the first step of a fix flow."""

        return await (self.async_step_start())

    async def async_step_start(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the confirm step of a fix flow."""
        if user_input is None:
            placeholders = self._async_get_placeholders()
            return self.async_show_form(
                step_id="start",
                data_schema=vol.Schema({}),
                description_placeholders=placeholders,
            )

        nvr = await self._api.get_nvr()
        if await nvr.get_is_prerelease():
            return await (self.async_step_confirm())
        await self.hass.config_entries.async_reload(self._entry.entry_id)
        return self.async_create_entry(title="", data={})

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the confirm step of a fix flow."""
        if user_input is not None:
            options = dict(self._entry.options)
            options[CONF_ALLOW_EA] = True
            self.hass.config_entries.async_update_entry(self._entry, options=options)
            return self.async_create_entry(title="", data={})

        placeholders = self._async_get_placeholders()
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders=placeholders,
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create flow."""
    if data is not None and issue_id == "ea_block":
        entry_id = cast(str, data["entry_id"])
        if (entry := hass.config_entries.async_get_entry(entry_id)) is not None:
            session = async_create_clientsession(
                hass, cookie_jar=CookieJar(unsafe=True)
            )
            api = ProtectApiClient(
                host=entry.data[CONF_HOST],
                port=entry.data[CONF_PORT],
                username=entry.data[CONF_USERNAME],
                password=entry.data[CONF_PASSWORD],
                verify_ssl=entry.data[CONF_VERIFY_SSL],
                session=session,
                subscribed_models=DEVICES_FOR_SUBSCRIBE,
                override_connection_host=entry.options.get(CONF_OVERRIDE_CHOST, False),
                ignore_stats=not entry.options.get(CONF_ALL_UPDATES, False),
                ignore_unadopted=False,
            )
            return EAConfirm(hass, api, entry)
    return ConfirmRepairFlow()
