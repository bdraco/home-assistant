"""Support for SNMP enabled switch."""

from __future__ import annotations

import logging
from typing import Any

from pysnmp.hlapi.asyncio import UdpTransportTarget, getCmd, setCmd
from pysnmp.proto.rfc1902 import (
    Counter32,
    Counter64,
    Gauge32,
    Integer,
    Integer32,
    IpAddress,
    Null,
    ObjectIdentifier,
    OctetString,
    Opaque,
    TimeTicks,
    Unsigned32,
)
import voluptuous as vol

from homeassistant.components.switch import PLATFORM_SCHEMA, SwitchEntity
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PAYLOAD_OFF,
    CONF_PAYLOAD_ON,
    CONF_PORT,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    CONF_AUTH_KEY,
    CONF_AUTH_PROTOCOL,
    CONF_BASEOID,
    CONF_COMMUNITY,
    CONF_PRIV_KEY,
    CONF_PRIV_PROTOCOL,
    CONF_VARTYPE,
    CONF_VERSION,
    DEFAULT_AUTH_PROTOCOL,
    DEFAULT_HOST,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_PRIV_PROTOCOL,
    DEFAULT_VARTYPE,
    DEFAULT_VERSION,
    MAP_AUTH_PROTOCOLS,
    MAP_PRIV_PROTOCOLS,
    SNMP_VERSIONS,
)
from .util import RequestArgsType, async_create_request_cmd_args, make_auth_data

_LOGGER = logging.getLogger(__name__)

CONF_COMMAND_OID = "command_oid"
CONF_COMMAND_PAYLOAD_OFF = "command_payload_off"
CONF_COMMAND_PAYLOAD_ON = "command_payload_on"

DEFAULT_COMMUNITY = "private"
DEFAULT_PAYLOAD_OFF = 0
DEFAULT_PAYLOAD_ON = 1

MAP_SNMP_VARTYPES = {
    "Counter32": Counter32,
    "Counter64": Counter64,
    "Gauge32": Gauge32,
    "Integer32": Integer32,
    "Integer": Integer,
    "IpAddress": IpAddress,
    "Null": Null,
    # some work todo to support tuple ObjectIdentifier, this just supports str
    "ObjectIdentifier": ObjectIdentifier,
    "OctetString": OctetString,
    "Opaque": Opaque,
    "TimeTicks": TimeTicks,
    "Unsigned32": Unsigned32,
}

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_BASEOID): cv.string,
        vol.Optional(CONF_COMMAND_OID): cv.string,
        vol.Optional(CONF_COMMAND_PAYLOAD_ON): cv.string,
        vol.Optional(CONF_COMMAND_PAYLOAD_OFF): cv.string,
        vol.Optional(CONF_COMMUNITY, default=DEFAULT_COMMUNITY): cv.string,
        vol.Optional(CONF_HOST, default=DEFAULT_HOST): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_PAYLOAD_OFF, default=DEFAULT_PAYLOAD_OFF): cv.string,
        vol.Optional(CONF_PAYLOAD_ON, default=DEFAULT_PAYLOAD_ON): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Optional(CONF_VERSION, default=DEFAULT_VERSION): vol.In(SNMP_VERSIONS),
        vol.Optional(CONF_USERNAME): cv.string,
        vol.Optional(CONF_AUTH_KEY): cv.string,
        vol.Optional(CONF_AUTH_PROTOCOL, default=DEFAULT_AUTH_PROTOCOL): vol.In(
            MAP_AUTH_PROTOCOLS
        ),
        vol.Optional(CONF_PRIV_KEY): cv.string,
        vol.Optional(CONF_PRIV_PROTOCOL, default=DEFAULT_PRIV_PROTOCOL): vol.In(
            MAP_PRIV_PROTOCOLS
        ),
        vol.Optional(CONF_VARTYPE, default=DEFAULT_VARTYPE): cv.string,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the SNMP switch."""
    name = config.get(CONF_NAME)
    host = config.get(CONF_HOST)
    port = config.get(CONF_PORT)
    community = config.get(CONF_COMMUNITY)
    baseoid: str = config[CONF_BASEOID]
    command_oid = config.get(CONF_COMMAND_OID)
    command_payload_on = config.get(CONF_COMMAND_PAYLOAD_ON)
    command_payload_off = config.get(CONF_COMMAND_PAYLOAD_OFF)
    version: str = config[CONF_VERSION]
    username = config.get(CONF_USERNAME)
    authkey = config.get(CONF_AUTH_KEY)
    authproto: str = config[CONF_AUTH_PROTOCOL]
    privkey = config.get(CONF_PRIV_KEY)
    privproto: str = config[CONF_PRIV_PROTOCOL]
    payload_on = config.get(CONF_PAYLOAD_ON)
    payload_off = config.get(CONF_PAYLOAD_OFF)
    vartype = config.get(CONF_VARTYPE)
    auth_data = make_auth_data(
        version, community, authproto, authkey, privproto, privkey, username
    )

    request_args = await async_create_request_cmd_args(
        hass, auth_data, UdpTransportTarget((host, port)), baseoid
    )

    async_add_entities(
        [
            SnmpSwitch(
                name,
                host,
                port,
                baseoid,
                command_oid,
                payload_on,
                payload_off,
                command_payload_on,
                command_payload_off,
                vartype,
                request_args,
            )
        ],
        True,
    )


class SnmpSwitch(SwitchEntity):
    """Representation of a SNMP switch."""

    def __init__(
        self,
        name,
        host,
        port,
        baseoid,
        commandoid,
        payload_on,
        payload_off,
        command_payload_on,
        command_payload_off,
        vartype,
        request_args,
    ) -> None:
        """Initialize the switch."""

        self._name = name
        self._baseoid = baseoid
        self._vartype = vartype

        # Set the command OID to the base OID if command OID is unset
        self._commandoid = commandoid or baseoid
        self._command_payload_on = command_payload_on or payload_on
        self._command_payload_off = command_payload_off or payload_off

        self._state: bool | None = None
        self._payload_on = payload_on
        self._payload_off = payload_off
        self._target = UdpTransportTarget((host, port))
        self._request_args: RequestArgsType = request_args

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch."""
        # If vartype set, use it - https://www.pysnmp.com/pysnmp/docs/api-reference.html#pysnmp.smi.rfc1902.ObjectType
        await self._execute_command(self._command_payload_on)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch."""
        await self._execute_command(self._command_payload_off)

    async def _execute_command(self, command):
        # User did not set vartype and command is not a digit
        if self._vartype == "none" and not self._command_payload_on.isdigit():
            await self._set(command)
        # User set vartype Null, command must be an empty string
        elif self._vartype == "Null":
            await self._set("")
        # user did not set vartype but command is digit: defaulting to Integer
        # or user did set vartype
        else:
            await self._set(MAP_SNMP_VARTYPES.get(self._vartype, Integer)(command))

    async def async_update(self) -> None:
        """Update the state."""
        get_result = await getCmd(*self._request_args)
        errindication, errstatus, errindex, restable = get_result

        if errindication:
            _LOGGER.error("SNMP error: %s", errindication)
        elif errstatus:
            _LOGGER.error(
                "SNMP error: %s at %s",
                errstatus.prettyPrint(),
                errindex and restable[-1][int(errindex) - 1] or "?",
            )
        else:
            for resrow in restable:
                if resrow[-1] == self._payload_on or resrow[-1] == Integer(
                    self._payload_on
                ):
                    self._state = True
                elif resrow[-1] == self._payload_off or resrow[-1] == Integer(
                    self._payload_off
                ):
                    self._state = False
                else:
                    self._state = None

    @property
    def name(self):
        """Return the switch's name."""
        return self._name

    @property
    def is_on(self):
        """Return true if switch is on; False if off. None if unknown."""
        return self._state

    async def _set(self, value):
        await setCmd(*self._request_args, value)
