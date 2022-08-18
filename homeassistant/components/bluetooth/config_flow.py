"""Config flow to configure the Bluetooth integration."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.components import onboarding
from homeassistant.config_entries import ConfigFlow
from homeassistant.helpers.typing import DiscoveryInfoType

from .const import (
    ADAPTER_ADDRESS,
    ADAPTER_NAME,
    CONF_ADAPTER,
    CONF_DETAILS,
    DOMAIN,
    AdapterDetails,
)
from .util import async_get_bluetooth_adapters

if TYPE_CHECKING:
    from homeassistant.data_entry_flow import FlowResult


class BluetoothConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Bluetooth."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._adapter: str | None = None
        self._details: AdapterDetails | None = None
        self._adapters: dict[str, AdapterDetails] = {}

    async def async_step_integration_discovery(
        self, discovery_info: DiscoveryInfoType
    ) -> FlowResult:
        """Handle a flow initialized by discovery."""
        adapter: str = discovery_info[CONF_ADAPTER]
        details: AdapterDetails = discovery_info[CONF_DETAILS]
        name = details[ADAPTER_NAME]
        address = details[ADAPTER_ADDRESS]

        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()
        self._adapter = adapter
        self._details = details
        self.context["title_placeholders"] = {"name": f"{name} ({adapter})"}
        return await self.async_step_discovered_adapter()

    async def async_step_discovered_adapter(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow for an discovered adapter."""
        adapter = self._adapter
        details = self._details

        assert adapter is not None
        assert details is not None

        name = details[ADAPTER_NAME]

        if user_input is not None or not onboarding.async_is_onboarded(self.hass):
            return self.async_create_entry(title=name, data={})

        return self.async_show_form(
            step_id="discovered_adapter",
            description_placeholders={"name": f"{name} ({adapter})"},
        )

    async def async_step_manual_adapter(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        if user_input is not None:
            assert self._adapters is not None
            adapter = user_input[CONF_ADAPTER]
            address = self._adapters[adapter][ADAPTER_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=adapter, data={})

        self._adapters = await async_get_bluetooth_adapters()
        if not self._adapters:
            return self.async_abort(reason="no_adapters")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADAPTER): vol.In(
                        {
                            adapter: f"{details[ADAPTER_NAME]} ({adapter})"
                            for adapter, details in self._adapters.items()
                        }
                    ),
                }
            ),
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        return await self.async_step_manual_adapter()
