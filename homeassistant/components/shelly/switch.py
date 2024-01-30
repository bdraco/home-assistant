"""Switch for Shelly."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, cast

from aioshelly.block_device import Block
from aioshelly.const import RPC_GENERATIONS

from homeassistant.components.automation import automations_with_entity
from homeassistant.components.script import scripts_with_entity
from homeassistant.components.switch import (
    DOMAIN as SWITCH_DOMAIN,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.components.valve import DOMAIN as VALVE_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import RegistryEntry
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue

from .const import DOMAIN, GAS_VALVE_OPEN_STATES
from .coordinator import ShellyBlockCoordinator, ShellyRpcCoordinator
from .entity import (
    BlockEntityDescription,
    RpcEntityDescription,
    ShellyBlockAttributeEntity,
    ShellyRpcAttributeEntity,
    async_setup_entry_attribute_entities,
    async_setup_entry_rpc,
)
from .utils import (
    get_device_entry_gen,
    is_block_exclude_from_relay,
    is_rpc_channel_type_light,
)


@dataclass(frozen=True)
class BlockSwitchDescription(BlockEntityDescription, SwitchEntityDescription):
    """Class to describe a BLOCK switch."""


@dataclass(frozen=True)
class RpcSwitchDescription(RpcEntityDescription, SwitchEntityDescription):
    """Class to describe a RPC sensor."""


SWITCHES: Final = {
    ("relay", "output"): BlockSwitchDescription(
        key="relay|output",
        removal_condition=is_block_exclude_from_relay,
    ),
    # This entity description is deprecated and will be removed in Home Assistant 2024.7.0.
    ("valve", "valve"): BlockSwitchDescription(
        key="valve|valve",
        name="Valve",
        available=lambda block: block.valve not in ("failure", "checking"),
        removal_condition=lambda _, block: block.valve in ("not_connected", "unknown"),
        entity_registry_enabled_default=False,
    ),
}

RPC_SWITCHES: Final = {
    "switch": RpcSwitchDescription(
        key="switch",
        sub_key="output",
        removal_condition=is_rpc_channel_type_light,
    )
}


def _build_block_description(entry: RegistryEntry) -> BlockSwitchDescription:
    """Build description when restoring block attribute entities."""
    return BlockSwitchDescription(
        key="",
        name="",
        icon=entry.original_icon,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches for device."""
    if get_device_entry_gen(config_entry) in RPC_GENERATIONS:
        return async_setup_entry_rpc(
            hass, config_entry, async_add_entities, RPC_SWITCHES, RpcRelaySwitch
        )

    return async_setup_entry_attribute_entities(
        hass, config_entry, async_add_entities, SWITCHES, BlockRelaySwitch
    )


class BlockRelaySwitch(ShellyBlockAttributeEntity, SwitchEntity):
    """Entity that controls a relay on Block based Shelly devices."""

    entity_description: BlockSwitchDescription

    def __init__(
        self,
        coordinator: ShellyBlockCoordinator,
        block: Block,
        attribute: str,
        description: BlockSwitchDescription,
    ) -> None:
        """Initialize relay switch."""
        super().__init__(coordinator, block, attribute, description)
        self._attr_unique_id: str = f"{super().unique_id}"
        self.control_result: dict[str, Any] | None = None
        self._valve = description.name == "Valve"

    @property
    def icon(self) -> str:
        """Return the icon."""
        if not self._valve:
            return "mdi:switch-variant"

        return "mdi:valve-open" if self.is_on else "mdi:valve-closed"

    @property
    def is_on(self) -> bool:
        """If switch is on."""
        if self.control_result:
            if self._valve:
                return self.control_result["state"] in GAS_VALVE_OPEN_STATES
            return cast(bool, self.control_result["ison"])

        if self._valve:
            return self.attribute_value in GAS_VALVE_OPEN_STATES

        return bool(self.block.output)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on relay."""
        if self._valve:
            async_create_issue(
                self.hass,
                DOMAIN,
                "deprecated_valve_switch",
                breaks_in_ha_version="2024.7.0",
                is_fixable=True,
                severity=IssueSeverity.WARNING,
                translation_key="deprecated_valve_switch",
                translation_placeholders={
                    "entity": f"{VALVE_DOMAIN}.{cast(str, self.name).lower().replace(' ', '_')}",
                    "service": f"{VALVE_DOMAIN}.open_valve",
                },
            )
            self.control_result = await self.set_state(go="open")
        else:
            self.control_result = await self.set_state(turn="on")
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off relay."""
        if self._valve:
            async_create_issue(
                self.hass,
                DOMAIN,
                "deprecated_valve_switch",
                breaks_in_ha_version="2024.7.0",
                is_fixable=True,
                severity=IssueSeverity.WARNING,
                translation_key="deprecated_valve_switche",
                translation_placeholders={
                    "entity": f"{VALVE_DOMAIN}.{cast(str, self.name).lower().replace(' ', '_')}",
                    "service": f"{VALVE_DOMAIN}.close_valve",
                },
            )
            self.control_result = await self.set_state(go="close")
        else:
            self.control_result = await self.set_state(turn="off")
        self.async_write_ha_state()

    @callback
    def _update_callback(self) -> None:
        """When device updates, clear control result that overrides state."""
        self.control_result = None
        super()._update_callback()

    async def async_added_to_hass(self) -> None:
        """Set up a listener when this entity is added to HA."""
        await super().async_added_to_hass()

        if self._valve:
            entity_automations = automations_with_entity(self.hass, self.entity_id)
            entity_scripts = scripts_with_entity(self.hass, self.entity_id)
            for item in entity_automations + entity_scripts:
                async_create_issue(
                    self.hass,
                    DOMAIN,
                    f"deprecated_valve_{self.entity_id}_{item}",
                    breaks_in_ha_version="2024.7.0",
                    is_fixable=True,
                    severity=IssueSeverity.WARNING,
                    translation_key="deprecated_valve_switch_entity",
                    translation_placeholders={
                        "entity": f"{SWITCH_DOMAIN}.{cast(str, self.name).lower().replace(' ', '_')}",
                        "info": item,
                    },
                )


class RpcRelaySwitch(ShellyRpcAttributeEntity, SwitchEntity):
    """Entity that controls a relay on RPC based Shelly devices."""

    entity_description: RpcSwitchDescription

    def __init__(
        self,
        coordinator: ShellyRpcCoordinator,
        key: str,
        attribute: str,
        description: RpcEntityDescription,
    ) -> None:
        """Initialize sensor."""
        super().__init__(coordinator, key, attribute, description)
        self._attr_unique_id = f"{super().unique_id}"

    @property
    def is_on(self) -> bool:
        """If switch is on."""
        return bool(self.status["output"])

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on relay."""
        await self.call_rpc("Switch.Set", {"id": self.status["id"], "on": True})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off relay."""
        await self.call_rpc("Switch.Set", {"id": self.status["id"], "on": False})
