"""Support for Harmony Hub devices."""
import asyncio
import json
import logging

import aioharmony.exceptions as aioexc
from aioharmony.harmonyapi import (
    ClientCallbackType,
    HarmonyAPI as HarmonyClient,
    SendCommandDevice,
)
import voluptuous as vol

from homeassistant.components import remote
from homeassistant.components.remote import (
    ATTR_ACTIVITY,
    ATTR_DELAY_SECS,
    ATTR_DEVICE,
    ATTR_HOLD_SECS,
    ATTR_NUM_REPEATS,
    DEFAULT_DELAY_SECS,
    PLATFORM_SCHEMA,
)
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, SERVICE_CHANGE_CHANNEL, SERVICE_SYNC

_LOGGER = logging.getLogger(__name__)

ATTR_CHANNEL = "channel"
ATTR_CURRENT_ACTIVITY = "current_activity"

DEFAULT_PORT = 8088
DEVICES = []

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(ATTR_ACTIVITY): cv.string,
        vol.Required(CONF_NAME): cv.string,
        vol.Optional(ATTR_DELAY_SECS, default=DEFAULT_DELAY_SECS): vol.Coerce(float),
        vol.Optional(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
    }
)

HARMONY_SYNC_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTITY_ID): cv.entity_ids})

HARMONY_CHANGE_CHANNEL_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Required(ATTR_CHANNEL): cv.positive_int,
    }
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the Harmony platform."""

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data={CONF_HOST: config[CONF_HOST], CONF_NAME: config[CONF_NAME]},
        )
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Set up the Harmony config entry."""

    device = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([device])
    register_services(hass)


def register_services(hass):
    """Register all services for harmony devices."""
    hass.services.async_register(
        DOMAIN, SERVICE_SYNC, _sync_service, schema=HARMONY_SYNC_SCHEMA
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CHANGE_CHANNEL,
        _change_channel_service,
        schema=HARMONY_CHANGE_CHANNEL_SCHEMA,
    )


async def _apply_service(service, service_func, *service_func_args):
    """Handle services to apply."""
    entity_ids = service.data.get("entity_id")

    if entity_ids:
        _devices = [device for device in DEVICES if device.entity_id in entity_ids]
    else:
        _devices = DEVICES

    for device in _devices:
        await service_func(device, *service_func_args)


async def _sync_service(service):
    await _apply_service(service, HarmonyRemote.sync)


async def _change_channel_service(service):
    channel = service.data.get(ATTR_CHANNEL)
    await _apply_service(service, HarmonyRemote.change_channel, channel)


class HarmonyRemote(remote.RemoteDevice):
    """Remote representation used to control a Harmony device."""

    def __init__(self, name, host, port, activity, out_path, delay_secs):
        """Initialize HarmonyRemote class."""
        self._name = name
        self.host = host
        self.port = port
        self._state = None
        self._current_activity = None
        self._default_activity = activity
        self._client = HarmonyClient(ip_address=host)
        self._config_path = out_path
        self._delay_secs = delay_secs
        self._available = False

    @property
    def delay_secs(self):
        """Delay seconds between sending commands."""
        return self._delay_secs

    @delay_secs.setter
    def delay_secs(self, delay_secs):
        """Update the delay seconds (from options flow)."""
        self._delay_secs = delay_secs

    @property
    def default_activity(self):
        """Activity used when non specified."""
        return self._default_activity

    @default_activity.setter
    def default_activity(self, activity):
        """Update the default activity (from options flow)."""
        self._default_activity = activity

    async def async_added_to_hass(self):
        """Complete the initialization."""
        _LOGGER.debug("%s: Harmony Hub added", self._name)
        # Register the callbacks
        self._client.callbacks = ClientCallbackType(
            new_activity=self.new_activity,
            config_updated=self.new_config,
            connect=self.got_connected,
            disconnect=self.got_disconnected,
        )

        # Store Harmony HUB config, this will also update our current
        # activity
        await self.new_config()

        async def shutdown(_):
            """Close connection on shutdown."""
            _LOGGER.debug("%s: Closing Harmony Hub", self._name)
            try:
                await self._client.close()
            except aioexc.TimeOut:
                _LOGGER.warning("%s: Disconnect timed-out", self._name)

        self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, shutdown)

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self.unique_id)},
            "manufacturer": "Logitech",
            "sw_version": self._client.fw_version,
            "name": self.name,
        }

    @property
    def unique_id(self):
        """Return the unique id."""
        return self._client.hub_config.info.get("activeRemoteId")

    @property
    def name(self):
        """Return the Harmony device's name."""
        return self._name

    @property
    def should_poll(self):
        """Return the fact that we should not be polled."""
        return False

    @property
    def device_state_attributes(self):
        """Add platform specific attributes."""
        return {ATTR_CURRENT_ACTIVITY: self._current_activity}

    @property
    def is_on(self):
        """Return False if PowerOff is the current activity, otherwise True."""
        return self._current_activity not in [None, "PowerOff"]

    @property
    def available(self):
        """Return True if connected to Hub, otherwise False."""
        return self._available

    async def connect(self):
        """Connect to the Harmony HUB."""
        _LOGGER.debug("%s: Connecting", self._name)
        try:
            if not await self._client.connect():
                _LOGGER.warning("%s: Unable to connect to HUB.", self._name)
                await self._client.close()
                return False
        except aioexc.TimeOut:
            _LOGGER.warning("%s: Connection timed-out", self._name)
            return False

        return True

    def new_activity(self, activity_info: tuple) -> None:
        """Call for updating the current activity."""
        activity_id, activity_name = activity_info
        _LOGGER.debug("%s: activity reported as: %s", self._name, activity_name)
        self._current_activity = activity_name
        self._state = bool(activity_id != -1)
        self._available = True
        self.async_schedule_update_ha_state()

    async def new_config(self, _=None):
        """Call for updating the current activity."""
        _LOGGER.debug("%s: configuration has been updated", self._name)
        self.new_activity(self._client.current_activity)
        await self.hass.async_add_executor_job(self.write_config_file)

    async def got_connected(self, _=None):
        """Notification that we're connected to the HUB."""
        _LOGGER.debug("%s: connected to the HUB.", self._name)
        if not self._available:
            # We were disconnected before.
            await self.new_config()

    async def got_disconnected(self, _=None):
        """Notification that we're disconnected from the HUB."""
        _LOGGER.debug("%s: disconnected from the HUB.", self._name)
        self._available = False
        # We're going to wait for 10 seconds before announcing we're
        # unavailable, this to allow a reconnection to happen.
        await asyncio.sleep(10)

        if not self._available:
            # Still disconnected. Let the state engine know.
            self.async_schedule_update_ha_state()

    async def async_turn_on(self, **kwargs):
        """Start an activity from the Harmony device."""
        _LOGGER.debug("%s: Turn On", self.name)

        activity = kwargs.get(ATTR_ACTIVITY, self._default_activity)

        if activity:
            activity_id = None
            if activity.isdigit() or activity == "-1":
                _LOGGER.debug("%s: Activity is numeric", self.name)
                if self._client.get_activity_name(int(activity)):
                    activity_id = activity

            if activity_id is None:
                _LOGGER.debug("%s: Find activity ID based on name", self.name)
                activity_id = self._client.get_activity_id(str(activity).strip())

            if activity_id is None:
                _LOGGER.error("%s: Activity %s is invalid", self.name, activity)
                return

            try:
                await self._client.start_activity(activity_id)
            except aioexc.TimeOut:
                _LOGGER.error("%s: Starting activity %s timed-out", self.name, activity)
        else:
            _LOGGER.error("%s: No activity specified with turn_on service", self.name)

    async def async_turn_off(self, **kwargs):
        """Start the PowerOff activity."""
        _LOGGER.debug("%s: Turn Off", self.name)
        try:
            await self._client.power_off()
        except aioexc.TimeOut:
            _LOGGER.error("%s: Powering off timed-out", self.name)

    async def async_send_command(self, command, **kwargs):
        """Send a list of commands to one device."""
        _LOGGER.debug("%s: Send Command", self.name)
        device = kwargs.get(ATTR_DEVICE)
        if device is None:
            _LOGGER.error("%s: Missing required argument: device", self.name)
            return

        device_id = None
        if device.isdigit():
            _LOGGER.debug("%s: Device %s is numeric", self.name, device)
            if self._client.get_device_name(int(device)):
                device_id = device

        if device_id is None:
            _LOGGER.debug(
                "%s: Find device ID %s based on device name", self.name, device
            )
            device_id = self._client.get_device_id(str(device).strip())

        if device_id is None:
            _LOGGER.error("%s: Device %s is invalid", self.name, device)
            return

        num_repeats = kwargs[ATTR_NUM_REPEATS]
        delay_secs = kwargs.get(ATTR_DELAY_SECS, self._delay_secs)
        hold_secs = kwargs[ATTR_HOLD_SECS]
        _LOGGER.debug(
            "Sending commands to device %s holding for %s seconds "
            "with a delay of %s seconds",
            device,
            hold_secs,
            delay_secs,
        )

        # Creating list of commands to send.
        snd_cmnd_list = []
        for _ in range(num_repeats):
            for single_command in command:
                send_command = SendCommandDevice(
                    device=device_id, command=single_command, delay=hold_secs
                )
                snd_cmnd_list.append(send_command)
                if delay_secs > 0:
                    snd_cmnd_list.append(float(delay_secs))

        _LOGGER.debug("%s: Sending commands", self.name)
        try:
            result_list = await self._client.send_commands(snd_cmnd_list)
        except aioexc.TimeOut:
            _LOGGER.error("%s: Sending commands timed-out", self.name)
            return

        for result in result_list:
            _LOGGER.error(
                "Sending command %s to device %s failed with code %s: %s",
                result.command.command,
                result.command.device,
                result.code,
                result.msg,
            )

    async def change_channel(self, channel):
        """Change the channel using Harmony remote."""
        _LOGGER.debug("%s: Changing channel to %s", self.name, channel)
        try:
            await self._client.change_channel(channel)
        except aioexc.TimeOut:
            _LOGGER.error("%s: Changing channel to %s timed-out", self.name, channel)

    async def sync(self):
        """Sync the Harmony device with the web service."""
        _LOGGER.debug("%s: Syncing hub with Harmony cloud", self.name)
        try:
            await self._client.sync()
        except aioexc.TimeOut:
            _LOGGER.error("%s: Syncing hub with Harmony cloud timed-out", self.name)
        else:
            await self.hass.async_add_executor_job(self.write_config_file)

    def write_config_file(self):
        """Write Harmony configuration file."""
        _LOGGER.debug(
            "%s: Writing hub configuration to file: %s", self.name, self._config_path
        )
        if self._client.config is None:
            _LOGGER.warning("%s: No configuration received from hub", self.name)
            return

        try:
            with open(self._config_path, "w+", encoding="utf-8") as file_out:
                json.dump(self._client.json_config, file_out, sort_keys=True, indent=4)
        except IOError as exc:
            _LOGGER.error(
                "%s: Unable to write HUB configuration to %s: %s",
                self.name,
                self._config_path,
                exc,
            )
