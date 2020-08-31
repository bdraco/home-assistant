"""Class to reload platforms."""

import asyncio
import logging
from typing import Any, Dict, Iterable, Optional

from homeassistant import config as conf_util
from homeassistant.const import SERVICE_RELOAD
from homeassistant.core import Event, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_per_platform
from homeassistant.helpers.entity_platform import DATA_ENTITY_PLATFORM, EntityPlatform
from homeassistant.helpers.typing import HomeAssistantType
from homeassistant.loader import async_get_integration

_LOGGER = logging.getLogger(__name__)


async def async_reload_integration_platforms(
    hass: HomeAssistantType, integration_name: str, integration_platforms: Iterable
) -> None:
    """Reload an integration's platforms.

    The platform must support being re-setup.

    This functionality is only intended to be used for integrations that process
    Home Assistant data and make this available to other integrations.

    Examples are template, stats, derivative, utility meter.
    """
    try:
        unprocessed_conf = await conf_util.async_hass_config_yaml(hass)
    except HomeAssistantError as err:
        _LOGGER.error(err)
        return

    tasks = [
        _resetup_platform(
            hass, integration_name, integration_platform, unprocessed_conf
        )
        for integration_platform in integration_platforms
    ]

    await asyncio.gather(*tasks)


async def _resetup_platform(
    hass: HomeAssistantType,
    integration_name: str,
    integration_platform: str,
    unprocessed_conf: Dict,
) -> None:
    """Resetup a non-entity platform."""
    integration = await async_get_integration(hass, integration_platform)

    conf = await conf_util.async_process_component_config(
        hass, unprocessed_conf, integration
    )

    if not conf:
        return

    component = integration.get_component()

    if hasattr(component, "async_reset_platform"):
        await component.async_reset_platform(hass, integration_name)  # type: ignore
    else:
        platform = async_get_platform(hass, integration_name, integration_platform)
        if not platform:
            return
        await platform.async_reset()

    root_config: Dict = {integration_platform: []}
    # Extract only the config for template, ignore the rest.
    for p_type, p_config in config_per_platform(conf, integration_platform):
        if p_type != integration_name:
            continue

        root_config[integration_platform].append(p_config)

    assert await component.async_setup(hass, root_config)  # type: ignore


async def async_integration_yaml_config(
    hass: HomeAssistantType, integration_name: str
) -> Optional[Dict[Any, Any]]:
    """Fetch the latest yaml configuration for an integration."""
    integration = await async_get_integration(hass, integration_name)

    return await conf_util.async_process_component_config(
        hass, await conf_util.async_hass_config_yaml(hass), integration
    )


@callback
def async_get_platform(
    hass: HomeAssistantType, integration_name: str, integration_platform_name: str
) -> Optional[EntityPlatform]:
    """Find an existing platform."""
    for integration_platform in hass.data[DATA_ENTITY_PLATFORM][integration_name]:
        if integration_platform.domain == integration_platform_name:
            platform: EntityPlatform = integration_platform
            return platform

    return None


async def async_setup_reload_service(
    hass: HomeAssistantType, domain: str, platforms: Iterable
) -> None:
    """Create the reload service for the domain."""

    if hass.services.has_service(domain, SERVICE_RELOAD):
        return

    async def _reload_config(call: Event) -> None:
        """Reload the platforms."""

        await async_reload_integration_platforms(hass, domain, platforms)
        hass.bus.async_fire(f"event_{domain}_reloaded", context=call.context)

    hass.helpers.service.async_register_admin_service(
        domain, SERVICE_RELOAD, _reload_config
    )


def setup_reload_service(
    hass: HomeAssistantType, domain: str, platforms: Iterable
) -> None:
    """Sync version of async_setup_reload_service."""

    asyncio.run_coroutine_threadsafe(
        async_setup_reload_service(hass, domain, platforms),
        hass.loop,
    ).result()
