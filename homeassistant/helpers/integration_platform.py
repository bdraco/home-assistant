"""Helpers to help with integration platforms."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
import logging
from typing import Any

from homeassistant.const import EVENT_COMPONENT_LOADED
from homeassistant.core import HassJob, HomeAssistant, callback
from homeassistant.loader import (
    Integration,
    async_get_integration,
    async_get_integrations,
    async_register_preload_platform,
    bind_hass,
)
from homeassistant.setup import ATTR_COMPONENT, EventComponentLoaded
from homeassistant.util.logging import catch_log_exception

from .typing import EventType

_LOGGER = logging.getLogger(__name__)
DATA_INTEGRATION_PLATFORMS = "integration_platforms"


@dataclass(slots=True, frozen=True)
class IntegrationPlatform:
    """An integration platform."""

    platform_name: str
    process_job: HassJob[[HomeAssistant, str, Any], Awaitable[None] | None]
    seen_components: set[str]


@callback
def _async_integration_platform_component_loaded(
    hass: HomeAssistant,
    integration_platforms: list[IntegrationPlatform],
    event: EventType[EventComponentLoaded],
) -> None:
    """Process integration platforms for a component."""
    component_name = event.data[ATTR_COMPONENT]
    if "." in component_name:
        return

    to_process: list[IntegrationPlatform] = []
    for integration_platform in integration_platforms:
        if component_name not in integration_platform.seen_components:
            to_process.append(integration_platform)
        integration_platform.seen_components.add(component_name)

    if to_process:
        hass.async_create_task(
            _async_process_integration_platforms_for_component(
                hass, component_name, to_process
            ),
            eager_start=True,
        )


def _filter_possible_platforms(
    integration: Integration,
    integration_platforms: list[IntegrationPlatform],
) -> list[IntegrationPlatform]:
    """Filter out platforms that have already been processed.

    This function is executed in an executor.
    """
    return [
        integration_platform
        for integration_platform in integration_platforms
        if integration.platform_exists(integration_platform.platform_name)
    ]


async def _async_process_integration_platforms_for_component(
    hass: HomeAssistant,
    component_name: str,
    integration_platforms: list[IntegrationPlatform],
) -> None:
    """Process integration platforms for a component."""
    integration = await async_get_integration(hass, component_name)
    # First filter out platforms that the integration already
    # knows are missing
    non_missing_integration_platforms = [
        integration_platform
        for integration_platform in integration_platforms
        if not integration.platform_missing(integration_platform.platform_name)
    ]
    if not non_missing_integration_platforms:
        return

    # Next create an executor job to filter out platforms that we don't know
    # if they are missing or not.
    #
    # We use the normal executor and not the import executor as we
    # we are not importing anything and only going to stat()
    # files.
    if not (
        integration_platforms_to_load := await hass.async_add_executor_job(
            _filter_possible_platforms, integration, non_missing_integration_platforms
        )
    ):
        return

    # Now we know which platforms to load, let's load them.
    platform_names = [
        integration_platform.platform_name
        for integration_platform in integration_platforms_to_load
    ]

    try:
        platforms = await integration.async_get_platforms(platform_names)
    except Exception:  # pylint: disable=broad-except
        _LOGGER.exception(
            "Unexpected error importing %s for %s",
            platform_names,
            integration.domain,
        )
        return

    # Finally, process the platforms.
    futures: list[asyncio.Future[Awaitable[None] | None]] = []
    for integration_platform in integration_platforms_to_load:
        if future := hass.async_run_hass_job(
            integration_platform.process_job,
            hass,
            component_name,
            platforms[integration_platform.platform_name],
        ):
            futures.append(future)

    if futures:
        await asyncio.gather(*futures)


def _format_err(name: str, platform_name: str, *args: Any) -> str:
    """Format error message."""
    return f"Exception in {name} when processing platform '{platform_name}': {args}"


def _get_integrations_with_platform(
    platform_name: str,
    integrations: list[Integration],
) -> list[Integration]:
    """Filter out integrations that have a platform.

    This function is executed in an executor.
    """
    return [
        integration
        for integration in integrations
        if integration.platform_exists(platform_name)
    ]


@bind_hass
async def async_process_integration_platforms(
    hass: HomeAssistant,
    platform_name: str,
    # Any = platform.
    process_platform: Callable[[HomeAssistant, str, Any], Awaitable[None] | None],
) -> None:
    """Process a specific platform for all current and future loaded integrations."""
    if DATA_INTEGRATION_PLATFORMS not in hass.data:
        integration_platforms: list[IntegrationPlatform] = []
        hass.data[DATA_INTEGRATION_PLATFORMS] = integration_platforms
        hass.bus.async_listen(
            EVENT_COMPONENT_LOADED,
            partial(
                _async_integration_platform_component_loaded,
                hass,
                integration_platforms,
            ),
        )
    else:
        integration_platforms = hass.data[DATA_INTEGRATION_PLATFORMS]

    top_level_components = {comp for comp in hass.config.components if "." not in comp}
    process_job = HassJob(
        catch_log_exception(
            process_platform,
            partial(_format_err, str(process_platform), platform_name),
        ),
        f"process_platform {platform_name}",
    )
    integration_platform = IntegrationPlatform(
        platform_name, process_job, top_level_components
    )
    # Tell the loader that it should try to pre-load the integration
    # for any future components that are loaded so we can reduce the
    # amount of import executor usage.
    async_register_preload_platform(hass, platform_name)
    integration_platforms.append(integration_platform)
    if not top_level_components:
        return

    integrations = await async_get_integrations(hass, top_level_components)
    loaded_integrations: list[Integration] = []
    for domain, integration in integrations.items():
        if isinstance(integration, Exception):
            _LOGGER.exception(
                "Error importing integration %s for %s",
                domain,
                platform_name,
                exc_info=integration,
            )
            continue
        loaded_integrations.append(integration)

    if not loaded_integrations:
        return

    # If the platform is known to be missing exclude it right
    # away from the list of integrations to process.
    integrations_not_missing_platform = [
        integration
        for integration in loaded_integrations
        if not integration.platform_missing(platform_name)
    ]
    if not integrations_not_missing_platform:
        return

    # Now we create an executor job to filter out integrations that we
    # don't know if they have the platform or not already.
    #
    # We use the normal executor and not the import executor as we
    # we are not importing anything and only going to stat()
    # files.
    integrations_with_platforms = await hass.async_add_executor_job(
        _get_integrations_with_platform,
        platform_name,
        integrations_not_missing_platform,
    )
    futures: list[asyncio.Future[None]] = []

    # Finally, fetch the platforms for each integration and process them.
    # This uses the import executor in a loop. If there are a lot
    # of integration with the integration platform to process,
    # this could be a bottleneck.
    for integration_with_platform in integrations_with_platforms:
        try:
            platform = await integration_with_platform.async_get_platform(platform_name)
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception(
                "Unexpected error importing %s for %s",
                platform_name,
                integration_with_platform.domain,
            )
            continue

        if future := hass.async_run_hass_job(
            process_job, hass, integration_with_platform.domain, platform
        ):
            futures.append(future)

    if futures:
        await asyncio.gather(*futures)
