"""Button platform for Tessie integration."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from tessie_api import (
    boombox,
    enable_keyless_driving,
    flash_lights,
    honk,
    open_close_rear_trunk,
    open_front_trunk,
    trigger_homelink,
    wake,
)

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import TessieDataUpdateCoordinator
from .entity import TessieEntity


@dataclass(frozen=True, kw_only=True)
class TessieButtonEntityDescription(ButtonEntityDescription):
    """Describes a Tessie Button entity."""

    func: Callable


DESCRIPTIONS: tuple[TessieButtonEntityDescription, ...] = (
    TessieButtonEntityDescription(key="wake", func=wake, icon="mdi:sleep-off"),
    TessieButtonEntityDescription(
        key="flash_lights", func=flash_lights, icon="mdi:flashlight"
    ),
    TessieButtonEntityDescription(key="honk", func=honk, icon="mdi:bullhorn"),
    TessieButtonEntityDescription(
        key="trigger_homelink", func=trigger_homelink, icon="mdi:garage"
    ),
    TessieButtonEntityDescription(
        key="enable_keyless_driving", func=enable_keyless_driving, icon="mdi:car-key"
    ),
    TessieButtonEntityDescription(key="boombox", func=boombox, icon="mdi:volume-high"),
    TessieButtonEntityDescription(key="frunk", func=open_front_trunk, icon="mdi:car"),
    TessieButtonEntityDescription(
        key="trunk", func=open_close_rear_trunk, icon="mdi:car-back"
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Tessie Button platform from a config entry."""
    coordinators = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        TessieButtonEntity(coordinator, description)
        for coordinator in coordinators
        for description in DESCRIPTIONS
    )


class TessieButtonEntity(TessieEntity, ButtonEntity):
    """Base class for Tessie Buttons."""

    entity_description: TessieButtonEntityDescription

    def __init__(
        self,
        coordinator: TessieDataUpdateCoordinator,
        description: TessieButtonEntityDescription,
    ) -> None:
        """Initialize the Button."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Press the button."""
        await self.run(self.entity_description.func)
