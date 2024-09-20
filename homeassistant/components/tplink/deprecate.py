"""Helper class for deprecating entities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.automation import automations_with_entity
from homeassistant.components.script import scripts_with_entity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue

from .const import DOMAIN

if TYPE_CHECKING:
    from .entity import TPLinkFeatureEntityDescription


@dataclass(slots=True)
class DeprecatedInfo:
    """Class to define deprecation info for deprecated entities."""

    platform: str
    new_platform: str
    breaks_in_ha_version: str


def async_check_create_deprecated(
    hass: HomeAssistant,
    unique_id: str,
    entity_description: TPLinkFeatureEntityDescription,
) -> bool:
    """Return true if the entity should be created based on the deprecated_info.

    If deprecated_info is not defined will return true.
    If entity not yet created will return false.
    If entity disabled will delete it and return false.
    Otherwise will return true and create issues for scripts or automations.
    """
    if not entity_description.deprecated_info:
        return True

    deprecated_info = entity_description.deprecated_info
    platform = deprecated_info.platform

    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id(
        platform,
        DOMAIN,
        unique_id,
    )
    if not entity_id:
        return False

    entity_entry = ent_reg.async_get(entity_id)
    assert entity_entry
    if entity_entry.disabled:
        # If the entity exists and is disabled then we want to remove
        # the entity so that the user is just using the new entity.
        ent_reg.async_remove(entity_id)
        return False

    # Check for issues that need to be created
    entity_automations = automations_with_entity(hass, entity_id)
    entity_scripts = scripts_with_entity(hass, entity_id)

    for item in entity_automations + entity_scripts:
        async_create_issue(
            hass,
            DOMAIN,
            f"deprecated_entity_{entity_id}_{item}",
            breaks_in_ha_version=deprecated_info.breaks_in_ha_version,
            is_fixable=False,
            is_persistent=False,
            severity=IssueSeverity.WARNING,
            translation_key="deprecated_entity",
            translation_placeholders={
                "entity": entity_id,
                "info": item,
                "platform": platform,
                "new_platform": deprecated_info.new_platform,
            },
        )
    return True
