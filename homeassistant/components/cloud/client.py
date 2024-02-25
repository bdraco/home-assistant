"""Interface implementation for cloud client."""
from __future__ import annotations

import asyncio
from http import HTTPStatus
import logging
from pathlib import Path
from typing import Any, Literal

import aiohttp
from hass_nabucasa.client import CloudClient as Interface, RemoteActivationNotAllowed

from homeassistant.components import persistent_notification, webhook
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import SERVER_SOFTWARE
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue
from homeassistant.util.aiohttp import MockRequest, serialize_response

from .const import DISPATCHER_REMOTE_UPDATE, DOMAIN
from .prefs import CloudPreferences

_LOGGER = logging.getLogger(__name__)

VALID_REPAIR_TRANSLATION_KEYS = {
    "warn_bad_custom_domain_configuration",
    "reset_bad_custom_domain_configuration",
}


class CloudClient(Interface):
    """Interface class for Home Assistant Cloud."""

    def __init__(
        self,
        hass: HomeAssistant,
        prefs: CloudPreferences,
        websession: aiohttp.ClientSession,
        alexa_user_config: dict[str, Any],
        google_user_config: dict[str, Any],
    ) -> None:
        """Initialize client interface to Cloud."""
        self._hass = hass
        self._prefs = prefs
        self._websession = websession
        self.google_user_config = google_user_config
        self.alexa_user_config = alexa_user_config
        self._alexa_config: None = None
        self._google_config: None = None
        self._alexa_config_init_lock = asyncio.Lock()
        self._google_config_init_lock = asyncio.Lock()
        self._relayer_region: str | None = None

    @property
    def base_path(self) -> Path:
        """Return path to base dir."""
        return Path(self._hass.config.config_dir)

    @property
    def prefs(self) -> CloudPreferences:
        """Return Cloud preferences."""
        return self._prefs

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """Return client loop."""
        return self._hass.loop

    @property
    def websession(self) -> aiohttp.ClientSession:
        """Return client session for aiohttp."""
        return self._websession

    @property
    def aiohttp_runner(self) -> aiohttp.web.AppRunner | None:
        """Return client webinterface aiohttp application."""
        return self._hass.http.runner

    @property
    def cloudhooks(self) -> dict[str, dict[str, str | bool]]:
        """Return list of cloudhooks."""
        return self._prefs.cloudhooks

    @property
    def remote_autostart(self) -> bool:
        """Return true if we want start a remote connection."""
        return self._prefs.remote_enabled

    @property
    def client_name(self) -> str:
        """Return the client name that will be used for API calls."""
        return SERVER_SOFTWARE

    @property
    def relayer_region(self) -> str | None:
        """Return the connected relayer region."""
        return self._relayer_region

    async def cloud_connected(self) -> None:
        """When cloud is connected."""
        _LOGGER.debug("cloud_connected")

    async def cloud_disconnected(self) -> None:
        """When cloud disconnected."""
        _LOGGER.debug("cloud_disconnected")
        if self._google_config:
            self._google_config.async_disable_local_sdk()

    async def cloud_started(self) -> None:
        """When cloud is started."""

    async def cloud_stopped(self) -> None:
        """When the cloud is stopped."""

    async def logout_cleanups(self) -> None:
        """Cleanup some stuff after logout."""
        await self.prefs.async_set_username(None)

    @callback
    def user_message(self, identifier: str, title: str, message: str) -> None:
        """Create a message for user to UI."""
        persistent_notification.async_create(self._hass, message, title, identifier)

    @callback
    def dispatcher_message(self, identifier: str, data: Any = None) -> None:
        """Match cloud notification to dispatcher."""
        if identifier.startswith("remote_"):
            async_dispatcher_send(self._hass, DISPATCHER_REMOTE_UPDATE, data)

    async def async_cloud_connect_update(self, connect: bool) -> None:
        """Process cloud remote message to client."""
        if not self._prefs.remote_allow_remote_enable:
            raise RemoteActivationNotAllowed
        await self._prefs.async_update(remote_enabled=connect)

    async def async_cloud_connection_info(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Process cloud connection info message to client."""
        return {
            "remote": {
                "can_enable": self._prefs.remote_allow_remote_enable,
                "connected": self.cloud.remote.is_connected,
                "enabled": self._prefs.remote_enabled,
                "instance_domain": self.cloud.remote.instance_domain,
                "alias": self.cloud.remote.alias,
            },
            "version": HA_VERSION,
            "instance_id": self.prefs.instance_id,
        }

    async def async_alexa_message(self, payload: dict[Any, Any]) -> dict[Any, Any]:
        """Process cloud alexa message to client."""
        cloud_user = await self._prefs.get_cloud_user()
        aconfig = await self.get_alexa_config()
        return await alexa_smart_home.async_handle_message(
            self._hass,
            aconfig,
            payload,
            context=Context(user_id=cloud_user),
            enabled=self._prefs.alexa_enabled,
        )

    async def async_google_message(self, payload: dict[Any, Any]) -> dict[Any, Any]:
        """Process cloud google message to client."""
        gconf = await self.get_google_config()

        if not self._prefs.google_enabled:
            return ga.api_disabled_response(  # type: ignore[no-any-return, no-untyped-call]
                payload, gconf.agent_user_id
            )

        return await ga.async_handle_message(  # type: ignore[no-any-return, no-untyped-call]
            self._hass, gconf, gconf.cloud_user, payload, google_assistant.SOURCE_CLOUD
        )

    async def async_webhook_message(self, payload: dict[Any, Any]) -> dict[Any, Any]:
        """Process cloud webhook message to client."""
        cloudhook_id = payload["cloudhook_id"]

        found = None
        for cloudhook in self._prefs.cloudhooks.values():
            if cloudhook["cloudhook_id"] == cloudhook_id:
                found = cloudhook
                break

        if found is None:
            return {"status": HTTPStatus.OK}

        request = MockRequest(
            content=payload["body"].encode("utf-8"),
            headers=payload["headers"],
            method=payload["method"],
            query_string=payload["query"],
            mock_source=DOMAIN,
        )

        response = await webhook.async_handle_webhook(
            self._hass, found["webhook_id"], request
        )

        response_dict = serialize_response(response)
        body = response_dict.get("body")

        return {
            "body": body,
            "status": response_dict["status"],
            "headers": {"Content-Type": response.content_type},
        }

    async def async_system_message(self, payload: dict[Any, Any] | None) -> None:
        """Handle system messages."""
        if payload and (region := payload.get("region")):
            self._relayer_region = region

    async def async_cloudhooks_update(
        self, data: dict[str, dict[str, str | bool]]
    ) -> None:
        """Update local list of cloudhooks."""
        await self._prefs.async_update(cloudhooks=data)

    async def async_create_repair_issue(
        self,
        identifier: str,
        translation_key: str,
        *,
        placeholders: dict[str, str] | None = None,
        severity: Literal["error", "warning"] = "warning",
    ) -> None:
        """Create a repair issue."""
        if translation_key not in VALID_REPAIR_TRANSLATION_KEYS:
            raise ValueError(f"Invalid translation key {translation_key}")
        async_create_issue(
            hass=self._hass,
            domain=DOMAIN,
            issue_id=identifier,
            translation_key=translation_key,
            translation_placeholders=placeholders,
            severity=IssueSeverity(severity),
            is_fixable=False,
        )
