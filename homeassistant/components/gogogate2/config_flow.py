"""Config flow for Gogogate2."""
import dataclasses
import logging
import re

from gogogate2_api.common import AbstractInfoResponse, ApiError
from gogogate2_api.const import GogoGate2ApiErrorCode, ISmartGateApiErrorCode
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import SOURCE_IMPORT, ConfigFlow
from homeassistant.const import (
    CONF_DEVICE,
    CONF_IP_ADDRESS,
    CONF_PASSWORD,
    CONF_USERNAME,
)

from .common import get_api
from .const import (  # pylint: disable=unused-import
    DEVICE_TYPE_GOGOGATE2,
    DEVICE_TYPE_ISMARTGATE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class Gogogate2FlowHandler(ConfigFlow, domain=DOMAIN):
    """Gogogate2 config flow."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def async_step_import(self, config_data: dict = None):
        """Handle importing of configuration."""
        result = await self.async_step_user(config_data)
        self._abort_if_unique_id_configured()
        return result

    async def async_step_user(self, user_input: dict = None):
        """Handle user initiated flow."""
        user_input = user_input or {}
        errors = {}

        if user_input:
            api = get_api(user_input)
            try:
                data: AbstractInfoResponse = await self.hass.async_add_executor_job(
                    api.info
                )
                data_dict = dataclasses.asdict(data)
                title = data_dict.get(
                    "gogogatename", data_dict.get("ismartgatename", "Cover")
                )
                await self.async_set_unique_id(re.sub("\\..*$", "", data.remoteaccess))
                return self.async_create_entry(title=title, data=user_input)

            except ApiError as api_error:
                device_type = user_input[CONF_DEVICE]
                is_invalid_auth = (
                    device_type == DEVICE_TYPE_GOGOGATE2
                    and api_error.code
                    in (
                        GogoGate2ApiErrorCode.CREDENTIALS_NOT_SET,
                        GogoGate2ApiErrorCode.CREDENTIALS_INCORRECT,
                    )
                ) or (
                    device_type == DEVICE_TYPE_ISMARTGATE
                    and api_error.code
                    in (
                        ISmartGateApiErrorCode.CREDENTIALS_NOT_SET,
                        ISmartGateApiErrorCode.CREDENTIALS_INCORRECT,
                    )
                )

                if is_invalid_auth:
                    errors["base"] = "invalid_auth"
                else:
                    errors["base"] = "cannot_connect"

            except Exception:  # pylint: disable=broad-except
                errors["base"] = "cannot_connect"

        if errors and self.source == SOURCE_IMPORT:
            return self.async_abort(reason="cannot_connect")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DEVICE,
                        default=user_input.get(CONF_DEVICE, DEVICE_TYPE_GOGOGATE2),
                    ): vol.In((DEVICE_TYPE_GOGOGATE2, DEVICE_TYPE_ISMARTGATE)),
                    vol.Required(
                        CONF_IP_ADDRESS, default=user_input.get(CONF_IP_ADDRESS, "")
                    ): str,
                    vol.Required(
                        CONF_USERNAME, default=user_input.get(CONF_USERNAME, "")
                    ): str,
                    vol.Required(
                        CONF_PASSWORD, default=user_input.get(CONF_PASSWORD, "")
                    ): str,
                }
            ),
            errors=errors,
        )
