"""Class to hold all thermostat accessories."""
import logging

from pyhap.const import CATEGORY_HUMIDIFIER

from homeassistant.components.humidifier.const import (
    ATTR_HUMIDITY,
    ATTR_MAX_HUMIDITY,
    ATTR_MIN_HUMIDITY,
    DEFAULT_MAX_HUMIDITY,
    DEFAULT_MIN_HUMIDITY,
    DEVICE_CLASS_DEHUMIDIFIER,
    DEVICE_CLASS_HUMIDIFIER,
    DOMAIN,
    SERVICE_SET_HUMIDITY,
)
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    UNIT_PERCENTAGE,
)
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event

from .accessories import TYPES, HomeAccessory
from .const import (
    CHAR_ACTIVE,
    CHAR_CURRENT_HUMIDIFIER_DEHUMIDIFIER,
    CHAR_CURRENT_HUMIDITY,
    CHAR_DEHUMIDIFIER_THRESHOLD_HUMIDITY,
    CHAR_HUMIDIFIER_THRESHOLD_HUMIDITY,
    CHAR_TARGET_HUMIDIFIER_DEHUMIDIFIER,
    CONF_LINKED_HUMIDITY_SENSOR,
    PROP_MAX_VALUE,
    PROP_MIN_STEP,
    PROP_MIN_VALUE,
    SERV_HUMIDIFIER_DEHUMIDIFIER,
)

_LOGGER = logging.getLogger(__name__)

HC_HUMIDIFIER = 1
HC_DEHUMIDIFIER = 2

HC_HASS_TO_HOMEKIT_DEVICE_CLASS = {
    DEVICE_CLASS_HUMIDIFIER: HC_HUMIDIFIER,
    DEVICE_CLASS_DEHUMIDIFIER: HC_DEHUMIDIFIER,
}

HC_DEVICE_CLASS_TO_TARGET_CHAR = {
    HC_HUMIDIFIER: CHAR_HUMIDIFIER_THRESHOLD_HUMIDITY,
    HC_DEHUMIDIFIER: CHAR_DEHUMIDIFIER_THRESHOLD_HUMIDITY,
}

HC_STATE_INACTIVE = 0
HC_STATE_IDLE = 1
HC_STATE_HUMIDIFYING = 2
HC_STATE_DEHUMIDIFYING = 3


@TYPES.register("HumidifierDehumidifier")
class HumidifierDehumidifier(HomeAccessory):
    """Generate a HumidifierDehumidifier accessory for a humidifier."""

    def __init__(self, *args):
        """Initialize a HumidifierDehumidifier accessory object."""
        super().__init__(*args, category=CATEGORY_HUMIDIFIER)
        self.chars = []
        state = self.hass.states.get(self.entity_id)
        device_class = state.attributes.get(ATTR_DEVICE_CLASS, DEVICE_CLASS_HUMIDIFIER)
        self._hk_device_class = HC_HASS_TO_HOMEKIT_DEVICE_CLASS[device_class]

        self._target_humidity_char_name = HC_DEVICE_CLASS_TO_TARGET_CHAR[
            self._hk_device_class
        ]
        self.chars.append(self._target_humidity_char_name)

        serv_humidifier_dehumidifier = self.add_preload_service(
            SERV_HUMIDIFIER_DEHUMIDIFIER, self.chars
        )

        # Current and target mode characteristics
        self.char_current_humidifier_dehumidifier = serv_humidifier_dehumidifier.configure_char(
            CHAR_CURRENT_HUMIDIFIER_DEHUMIDIFIER, value=0
        )
        self.char_target_humidifier_dehumidifier = serv_humidifier_dehumidifier.configure_char(
            CHAR_TARGET_HUMIDIFIER_DEHUMIDIFIER, value=0,
        )

        # Current and target humidity characteristics
        self.char_current_humidity = serv_humidifier_dehumidifier.configure_char(
            CHAR_CURRENT_HUMIDITY, value=0
        )

        max_humidity = state.attributes.get(ATTR_MAX_HUMIDITY, DEFAULT_MAX_HUMIDITY)
        max_humidity = round(max_humidity)
        max_humidity = min(max_humidity, 100)

        min_humidity = state.attributes.get(ATTR_MIN_HUMIDITY, DEFAULT_MIN_HUMIDITY)
        min_humidity = round(min_humidity)
        min_humidity = max(min_humidity, 0)

        self.char_target_humidity = serv_humidifier_dehumidifier.configure_char(
            self._target_humidity_char_name,
            value=45,
            properties={
                PROP_MIN_VALUE: min_humidity,
                PROP_MAX_VALUE: max_humidity,
                PROP_MIN_STEP: 1,
            },
        )

        # Active/inactive characteristics
        self.char_active = serv_humidifier_dehumidifier.configure_char(
            CHAR_ACTIVE, value=False
        )

        self.async_update_state(state)

        serv_humidifier_dehumidifier.setter_callback = self._set_chars

        self.linked_humidity_sensor = self.config.get(CONF_LINKED_HUMIDITY_SENSOR)
        if self.linked_humidity_sensor:
            humidity_state = self.hass.states.get(self.linked_humidity_sensor)
            if humidity_state:
                self._async_update_current_humidity(humidity_state)

    async def run_handler(self):
        """Handle accessory driver started event.

        Run inside the Home Assistant event loop.
        """
        if self.linked_humidity_sensor:
            async_track_state_change_event(
                self.hass,
                [self.linked_humidity_sensor],
                self.async_update_current_humidity_event,
            )

        await super().run_handler()

    @callback
    def async_update_current_humidity_event(self, event):
        """Handle state change event listener callback."""
        self._async_update_current_humidity(event.data.get("new_state"))

    @callback
    def _async_update_current_humidity(self, new_state):
        """Handle linked humidity sensor state change to update HomeKit value."""
        if new_state is None:
            return
        try:
            current_humidity = float(new_state.state)
            if self.char_current_humidity.value != current_humidity:
                self.char_current_humidity.set_value(current_humidity)
                _LOGGER.debug(
                    "%s: Linked humidity sensor %s changed to %d",
                    self.entity_id,
                    self.linked_humidity_sensor,
                    current_humidity,
                )
        except ValueError as ex:
            _LOGGER.error(
                "%s: Unable to update from linked humidity sensor %s: %s",
                self.entity_id,
                self.linked_humidity_sensor,
                ex,
            )

    def _set_chars(self, char_values):
        _LOGGER.debug("HumidifierDehumidifier _set_chars: %s", char_values)
        events = []
        params = {}
        service = None

        if CHAR_ACTIVE in char_values:
            service = SERVICE_TURN_ON if char_values[CHAR_ACTIVE] else SERVICE_TURN_OFF
            events.append(f"{CHAR_ACTIVE} to {char_values[CHAR_ACTIVE]}")

        if CHAR_TARGET_HUMIDIFIER_DEHUMIDIFIER in char_values:
            # We support either humidifiers or dehumidifiers. If incompatible setting is requested
            # then we switch off the device to avoid humidifying when the user wants to dehumidify and vice versa
            hk_value = char_values[CHAR_TARGET_HUMIDIFIER_DEHUMIDIFIER]
            if (self._hk_device_class == HC_HUMIDIFIER and hk_value == 0) or (
                self._hk_device_class == HC_DEHUMIDIFIER and hk_value == 1
            ):
                service = SERVICE_TURN_OFF
                events.append(
                    f"{CHAR_TARGET_HUMIDIFIER_DEHUMIDIFIER} to {char_values[CHAR_TARGET_HUMIDIFIER_DEHUMIDIFIER]}"
                )

        if service:
            params[ATTR_ENTITY_ID] = self.entity_id
            self.call_service(
                DOMAIN, service, params, ", ".join(events),
            )

        if self._target_humidity_char_name in char_values:
            humidity = round(char_values[self._target_humidity_char_name])
            self.call_service(
                DOMAIN,
                SERVICE_SET_HUMIDITY,
                {ATTR_ENTITY_ID: self.entity_id, ATTR_HUMIDITY: humidity},
                f"{self._target_humidity_char_name} to {char_values[self._target_humidity_char_name]}{UNIT_PERCENTAGE}",
            )

    @callback
    def async_update_state(self, new_state):
        """Update state without rechecking the device features."""
        is_active = new_state.state == STATE_ON

        # Update active state
        if self.char_active.value != is_active:
            self.char_active.set_value(is_active)

        # Set correct value for TargetHumidifierDehumidifierState if the device is back on
        if is_active:
            if self.char_target_humidifier_dehumidifier.value != self._hk_device_class:
                self.char_target_humidifier_dehumidifier.set_value(
                    self._hk_device_class
                )

        # Set current state
        if is_active:
            if self._hk_device_class == HC_HUMIDIFIER:
                current_state = HC_STATE_HUMIDIFYING
            else:
                current_state = HC_STATE_DEHUMIDIFYING
        else:
            current_state = HC_STATE_INACTIVE
        if self.char_current_humidifier_dehumidifier.value != current_state:
            self.char_current_humidifier_dehumidifier.set_value(current_state)

        # Update target humidity
        target_humidity = new_state.attributes.get(ATTR_HUMIDITY)
        if isinstance(target_humidity, (int, float)):
            if self.char_target_humidity.value != target_humidity:
                self.char_target_humidity.set_value(target_humidity)
