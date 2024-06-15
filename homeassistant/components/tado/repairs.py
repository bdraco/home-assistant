"""Repair implementations."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import (
    CONST_OVERLAY_MANUAL,
    CONST_OVERLAY_TADO_DEFAULT,
    DOMAIN,
    WATER_HEATER_FALLBACK_REPAIR,
)


def manage_water_heater_fallback_issue(
    hass: HomeAssistant,
    water_heater_entities: list,
    integration_overlay_fallback: str | None,
) -> None:
    """Notify users about water heater respecting fallback setting."""
    if (
        integration_overlay_fallback
        in [CONST_OVERLAY_TADO_DEFAULT, CONST_OVERLAY_MANUAL]
        and len(water_heater_entities) > 0
    ):
        for water_heater_entity in water_heater_entities:
            ir.async_create_issue(
                hass=hass,
                domain=DOMAIN,
                issue_id=f"{WATER_HEATER_FALLBACK_REPAIR}_{water_heater_entity.zone_name}",
                is_fixable=False,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=WATER_HEATER_FALLBACK_REPAIR,
            )
