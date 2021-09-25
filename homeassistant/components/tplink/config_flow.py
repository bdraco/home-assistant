"""Config flow for TP-Link."""
from __future__ import annotations

import logging

from kasa import SmartDevice, SmartDeviceException
from kasa.discover import Discover
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_DEVICE, CONF_HOST, CONF_MAC, CONF_NAME
from homeassistant.helpers import device_registry as dr

from .const import CONF_LEGACY_ENTRY_ID, DISCOVERED_DEVICES, DOMAIN

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for tplink."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self._discovered_devices: dict[str, SmartDevice] = {}
        self._discovered_name: str | None = None
        self._discovered_device: SmartDevice | None = None
        self._discovered_ip: str | None = None

    async def async_step_discovery(self, discovery_info):
        """Handle discovery."""
        self._discovered_ip = discovery_info[CONF_HOST]
        self._discovered_name = discovery_info[CONF_NAME]
        formatted_mac = dr.format_mac(discovery_info[CONF_MAC])
        await self.async_set_unique_id(formatted_mac)
        self._abort_if_unique_id_configured(updates={CONF_HOST: self._discovered_ip})
        return await self._async_handle_discovery()

    async def _async_handle_discovery(self):
        """Handle any discovery."""
        self.context[CONF_HOST] = self._discovered_ip
        for progress in self._async_in_progress():
            if progress.get("context", {}).get(CONF_HOST) == self._discovered_ip:
                return self.async_abort(reason="already_in_progress")

        try:
            self._discovered_device = await self._async_try_connect(
                self._discovered_ip, raise_on_progress=True
            )
        except SmartDeviceException:
            return self.async_abort(reason="cannot_connect")
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(self, user_input=None):
        """Confirm discovery."""
        assert self._discovered_device is not None
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovered_device.alias,
                data={
                    CONF_HOST: self._discovered_ip,
                },
            )

        self._set_confirm_only()
        placeholders = {
            "name": self._discovered_device.alias,
            "host": self._discovered_ip,
        }
        self.context["title_placeholders"] = placeholders
        return self.async_show_form(
            step_id="discovery_confirm", description_placeholders=placeholders
        )

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            if not user_input.get(CONF_HOST):
                return await self.async_step_pick_device()
            try:
                device = await self._async_try_connect(
                    user_input[CONF_HOST], raise_on_progress=False
                )
            except SmartDeviceException:
                errors["base"] = "cannot_connect"
            else:
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=device.alias,
                    data={
                        CONF_HOST: self._discovered_ip,
                    },
                )

        user_input = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Optional(CONF_HOST, default=user_input.get(CONF_HOST, "")): str}
            ),
            errors=errors,
        )

    async def async_step_pick_device(self, user_input=None):
        """Handle the step to pick discovered device."""
        if user_input is not None:
            mac = user_input[CONF_MAC]
            device: SmartDevice = self._discovered_devices[mac]
            await self.async_set_unique_id(mac, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=device.alias,
                data={
                    CONF_HOST: device.host,
                },
            )

        configured_devices = {
            entry.unique_id
            for entry in self._async_current_entries()
            if entry.unique_id
        }
        self._discovered_devices = {
            dr.format_mac(device.mac): device
            for device in (await Discover.discover()).values()
        }
        devices_name = {
            formatted_mac: f"{device.alias} ({device.host}"
            for formatted_mac, device in self._discovered_devices
            if formatted_mac not in configured_devices
        }
        # Check if there is at least one device
        if not devices_name:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="pick_device",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE): vol.In(devices_name)}),
        )

    async def async_step_migration(self, migration_input=None):
        """Handle migration from legacy config entry to per device config entry."""
        name = migration_input[CONF_NAME]
        mac = migration_input[CONF_MAC]
        discovered_devices = self.hass.data[DOMAIN][DISCOVERED_DEVICES]
        host = None
        if device := discovered_devices.get(mac):
            host = device.host
        await self.async_set_unique_id(dr.format_mac(mac), raise_on_progress=True)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=name,
            data={
                CONF_HOST: host,
                CONF_LEGACY_ENTRY_ID: migration_input[CONF_LEGACY_ENTRY_ID],
            },
        )

    async def async_step_import(self, user_input=None):
        """Handle import step."""
        host = user_input[CONF_HOST]
        try:
            device = await self._async_try_connect(host, raise_on_progress=False)
        except SmartDeviceException:
            _LOGGER.error("Failed to import %s: cannot connect", host)
            return self.async_abort(reason="cannot_connect")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=device.alias,
            data={
                CONF_HOST: device.host,
            },
        )

    async def _async_try_connect(self, host, raise_on_progress=True) -> SmartDevice:
        """Try to connect."""
        self._async_abort_entries_match({CONF_HOST: host})
        device: SmartDevice = await Discover.discover_single(host)
        await self.async_set_unique_id(
            dr.format_mac(device.mac), raise_on_progress=raise_on_progress
        )
        return device
