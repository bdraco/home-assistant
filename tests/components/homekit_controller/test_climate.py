"""Basic checks for HomeKitclimate."""
from aiohomekit.model.characteristics import (
    ActivationStateValues,
    CharacteristicsTypes,
    CurrentHeaterCoolerStateValues,
    SwingModeValues,
    TargetHeaterCoolerStateValues,
)
from aiohomekit.model.services import ServicesTypes

from homeassistant.components.climate.const import (
    DOMAIN,
    SERVICE_SET_HUMIDITY,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_SWING_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACMode,
)

from tests.components.homekit_controller.common import setup_test_component

# Test thermostat devices


def create_thermostat_service(accessory):
    """Define thermostat characteristics."""
    service = accessory.add_service(ServicesTypes.THERMOSTAT)

    char = service.add_char(CharacteristicsTypes.HEATING_COOLING_TARGET)
    char.value = 0

    char = service.add_char(CharacteristicsTypes.HEATING_COOLING_CURRENT)
    char.value = 0

    char = service.add_char(CharacteristicsTypes.FAN_STATE_TARGET)
    char.value = 0

    char = service.add_char(CharacteristicsTypes.TEMPERATURE_COOLING_THRESHOLD)
    char.minValue = 15
    char.maxValue = 40
    char.value = 0

    char = service.add_char(CharacteristicsTypes.TEMPERATURE_HEATING_THRESHOLD)
    char.minValue = 4
    char.maxValue = 30
    char.value = 0

    char = service.add_char(CharacteristicsTypes.TEMPERATURE_TARGET)
    char.minValue = 7
    char.maxValue = 35
    char.value = 0

    char = service.add_char(CharacteristicsTypes.TEMPERATURE_CURRENT)
    char.value = 0

    char = service.add_char(CharacteristicsTypes.RELATIVE_HUMIDITY_TARGET)
    char.value = 0

    char = service.add_char(CharacteristicsTypes.RELATIVE_HUMIDITY_CURRENT)
    char.value = 0


def create_thermostat_service_min_max(accessory):
    """Define thermostat characteristics."""
    service = accessory.add_service(ServicesTypes.THERMOSTAT)
    char = service.add_char(CharacteristicsTypes.HEATING_COOLING_TARGET)
    char.value = 0
    char.minValue = 0
    char.maxValue = 1


async def test_climate_respect_supported_op_modes_1(hass, utcnow):
    """Test that climate respects minValue/maxValue hints."""
    helper = await setup_test_component(hass, create_thermostat_service_min_max)
    state = await helper.poll_and_get_state()
    assert state.attributes["hvac_modes"] == ["off", "heat"]


def create_thermostat_service_valid_vals(accessory):
    """Define thermostat characteristics."""
    service = accessory.add_service(ServicesTypes.THERMOSTAT)
    char = service.add_char(CharacteristicsTypes.HEATING_COOLING_TARGET)
    char.value = 0
    char.valid_values = [0, 1, 2]


async def test_climate_respect_supported_op_modes_2(hass, utcnow):
    """Test that climate respects validValue hints."""
    helper = await setup_test_component(hass, create_thermostat_service_valid_vals)
    state = await helper.poll_and_get_state()
    assert state.attributes["hvac_modes"] == ["off", "heat", "cool"]


async def test_climate_change_thermostat_state(hass, utcnow):
    """Test that we can turn a HomeKit thermostat on and off again."""
    helper = await setup_test_component(hass, create_thermostat_service)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {"entity_id": "climate.testdevice", "hvac_mode": HVACMode.HEAT},
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.THERMOSTAT,
        {
            CharacteristicsTypes.HEATING_COOLING_TARGET: 1,
        },
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {"entity_id": "climate.testdevice", "hvac_mode": HVACMode.COOL},
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.THERMOSTAT,
        {
            CharacteristicsTypes.HEATING_COOLING_TARGET: 2,
        },
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {"entity_id": "climate.testdevice", "hvac_mode": HVACMode.HEAT_COOL},
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.THERMOSTAT,
        {
            CharacteristicsTypes.HEATING_COOLING_TARGET: 3,
        },
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {"entity_id": "climate.testdevice", "hvac_mode": HVACMode.OFF},
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.THERMOSTAT,
        {
            CharacteristicsTypes.HEATING_COOLING_TARGET: 0,
        },
    )


async def test_climate_check_min_max_values_per_mode(hass, utcnow):
    """Test that we we get the appropriate min/max values for each mode."""
    helper = await setup_test_component(hass, create_thermostat_service)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {"entity_id": "climate.testdevice", "hvac_mode": HVACMode.HEAT},
        blocking=True,
    )
    climate_state = await helper.poll_and_get_state()
    assert climate_state.attributes["min_temp"] == 7
    assert climate_state.attributes["max_temp"] == 35

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {"entity_id": "climate.testdevice", "hvac_mode": HVACMode.COOL},
        blocking=True,
    )
    climate_state = await helper.poll_and_get_state()
    assert climate_state.attributes["min_temp"] == 7
    assert climate_state.attributes["max_temp"] == 35

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {"entity_id": "climate.testdevice", "hvac_mode": HVACMode.HEAT_COOL},
        blocking=True,
    )
    climate_state = await helper.poll_and_get_state()
    assert climate_state.attributes["min_temp"] == 4
    assert climate_state.attributes["max_temp"] == 40


async def test_climate_change_thermostat_temperature(hass, utcnow):
    """Test that we can turn a HomeKit thermostat on and off again."""
    helper = await setup_test_component(hass, create_thermostat_service)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {"entity_id": "climate.testdevice", "temperature": 21},
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.THERMOSTAT,
        {
            CharacteristicsTypes.TEMPERATURE_TARGET: 21,
        },
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {"entity_id": "climate.testdevice", "temperature": 25},
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.THERMOSTAT,
        {
            CharacteristicsTypes.TEMPERATURE_TARGET: 25,
        },
    )


async def test_climate_change_thermostat_temperature_range(hass, utcnow):
    """Test that we can set separate heat and cool setpoints in heat_cool mode."""
    helper = await setup_test_component(hass, create_thermostat_service)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {"entity_id": "climate.testdevice", "hvac_mode": HVACMode.HEAT_COOL},
        blocking=True,
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {
            "entity_id": "climate.testdevice",
            "hvac_mode": HVACMode.HEAT_COOL,
            "target_temp_high": 25,
            "target_temp_low": 20,
        },
        blocking=True,
    )

    helper.async_assert_service_values(
        ServicesTypes.THERMOSTAT,
        {
            CharacteristicsTypes.TEMPERATURE_TARGET: 22.5,
            CharacteristicsTypes.TEMPERATURE_HEATING_THRESHOLD: 20,
            CharacteristicsTypes.TEMPERATURE_COOLING_THRESHOLD: 25,
        },
    )


async def test_climate_change_thermostat_temperature_range_iphone(hass, utcnow):
    """Test that we can set all three set points at once (iPhone heat_cool mode support)."""
    helper = await setup_test_component(hass, create_thermostat_service)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {"entity_id": "climate.testdevice", "hvac_mode": HVACMode.HEAT_COOL},
        blocking=True,
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {
            "entity_id": "climate.testdevice",
            "hvac_mode": HVACMode.HEAT_COOL,
            "temperature": 22,
            "target_temp_low": 20,
            "target_temp_high": 24,
        },
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.THERMOSTAT,
        {
            CharacteristicsTypes.TEMPERATURE_TARGET: 22,
            CharacteristicsTypes.TEMPERATURE_HEATING_THRESHOLD: 20,
            CharacteristicsTypes.TEMPERATURE_COOLING_THRESHOLD: 24,
        },
    )


async def test_climate_cannot_set_thermostat_temp_range_in_wrong_mode(hass, utcnow):
    """Test that we cannot set range values when not in heat_cool mode."""
    helper = await setup_test_component(hass, create_thermostat_service)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {"entity_id": "climate.testdevice", "hvac_mode": HVACMode.HEAT},
        blocking=True,
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {
            "entity_id": "climate.testdevice",
            "temperature": 22,
            "target_temp_low": 20,
            "target_temp_high": 24,
        },
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.THERMOSTAT,
        {
            CharacteristicsTypes.TEMPERATURE_TARGET: 22,
            CharacteristicsTypes.TEMPERATURE_HEATING_THRESHOLD: 0,
            CharacteristicsTypes.TEMPERATURE_COOLING_THRESHOLD: 0,
        },
    )


def create_thermostat_single_set_point_auto(accessory):
    """Define thermostat characteristics with a single set point in auto."""
    service = accessory.add_service(ServicesTypes.THERMOSTAT)

    char = service.add_char(CharacteristicsTypes.HEATING_COOLING_TARGET)
    char.value = 0

    char = service.add_char(CharacteristicsTypes.HEATING_COOLING_CURRENT)
    char.value = 0

    char = service.add_char(CharacteristicsTypes.TEMPERATURE_TARGET)
    char.minValue = 7
    char.maxValue = 35
    char.value = 0

    char = service.add_char(CharacteristicsTypes.TEMPERATURE_CURRENT)
    char.value = 0

    char = service.add_char(CharacteristicsTypes.RELATIVE_HUMIDITY_TARGET)
    char.value = 0

    char = service.add_char(CharacteristicsTypes.RELATIVE_HUMIDITY_CURRENT)
    char.value = 0


async def test_climate_check_min_max_values_per_mode_sspa_device(hass, utcnow):
    """Test appropriate min/max values for each mode on sspa devices."""
    helper = await setup_test_component(hass, create_thermostat_single_set_point_auto)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {"entity_id": "climate.testdevice", "hvac_mode": HVACMode.HEAT},
        blocking=True,
    )
    climate_state = await helper.poll_and_get_state()
    assert climate_state.attributes["min_temp"] == 7
    assert climate_state.attributes["max_temp"] == 35

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {"entity_id": "climate.testdevice", "hvac_mode": HVACMode.COOL},
        blocking=True,
    )
    climate_state = await helper.poll_and_get_state()
    assert climate_state.attributes["min_temp"] == 7
    assert climate_state.attributes["max_temp"] == 35

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {"entity_id": "climate.testdevice", "hvac_mode": HVACMode.HEAT_COOL},
        blocking=True,
    )
    climate_state = await helper.poll_and_get_state()
    assert climate_state.attributes["min_temp"] == 7
    assert climate_state.attributes["max_temp"] == 35


async def test_climate_set_thermostat_temp_on_sspa_device(hass, utcnow):
    """Test setting temperature in different modes on device with single set point in auto."""
    helper = await setup_test_component(hass, create_thermostat_single_set_point_auto)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {"entity_id": "climate.testdevice", "hvac_mode": HVACMode.HEAT},
        blocking=True,
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {"entity_id": "climate.testdevice", "temperature": 21},
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.THERMOSTAT,
        {
            CharacteristicsTypes.TEMPERATURE_TARGET: 21,
        },
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {"entity_id": "climate.testdevice", "hvac_mode": HVACMode.HEAT_COOL},
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.THERMOSTAT,
        {
            CharacteristicsTypes.TEMPERATURE_TARGET: 21,
        },
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {
            "entity_id": "climate.testdevice",
            "temperature": 22,
        },
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.THERMOSTAT,
        {
            CharacteristicsTypes.TEMPERATURE_TARGET: 22,
        },
    )


async def test_climate_set_mode_via_temp(hass, utcnow):
    """Test setting temperature and mode at same tims."""
    helper = await setup_test_component(hass, create_thermostat_single_set_point_auto)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {
            "entity_id": "climate.testdevice",
            "temperature": 21,
            "hvac_mode": HVACMode.HEAT,
        },
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.THERMOSTAT,
        {
            CharacteristicsTypes.TEMPERATURE_TARGET: 21,
            CharacteristicsTypes.HEATING_COOLING_TARGET: 1,
        },
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {
            "entity_id": "climate.testdevice",
            "hvac_mode": HVACMode.HEAT_COOL,
            "temperature": 22,
        },
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.THERMOSTAT,
        {
            CharacteristicsTypes.TEMPERATURE_TARGET: 22,
            CharacteristicsTypes.HEATING_COOLING_TARGET: 3,
        },
    )


async def test_climate_change_thermostat_humidity(hass, utcnow):
    """Test that we can turn a HomeKit thermostat on and off again."""
    helper = await setup_test_component(hass, create_thermostat_service)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HUMIDITY,
        {"entity_id": "climate.testdevice", "humidity": 50},
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.THERMOSTAT,
        {
            CharacteristicsTypes.RELATIVE_HUMIDITY_TARGET: 50,
        },
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HUMIDITY,
        {"entity_id": "climate.testdevice", "humidity": 45},
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.THERMOSTAT,
        {
            CharacteristicsTypes.RELATIVE_HUMIDITY_TARGET: 45,
        },
    )


async def test_climate_read_thermostat_state(hass, utcnow):
    """Test that we can read the state of a HomeKit thermostat accessory."""
    helper = await setup_test_component(hass, create_thermostat_service)

    # Simulate that heating is on
    await helper.async_update(
        ServicesTypes.THERMOSTAT,
        {
            CharacteristicsTypes.TEMPERATURE_CURRENT: 19,
            CharacteristicsTypes.TEMPERATURE_TARGET: 21,
            CharacteristicsTypes.HEATING_COOLING_CURRENT: 1,
            CharacteristicsTypes.HEATING_COOLING_TARGET: 1,
            CharacteristicsTypes.RELATIVE_HUMIDITY_CURRENT: 50,
            CharacteristicsTypes.RELATIVE_HUMIDITY_TARGET: 45,
        },
    )

    state = await helper.poll_and_get_state()
    assert state.state == HVACMode.HEAT
    assert state.attributes["current_temperature"] == 19
    assert state.attributes["current_humidity"] == 50
    assert state.attributes["min_temp"] == 7
    assert state.attributes["max_temp"] == 35

    # Simulate that cooling is on
    await helper.async_update(
        ServicesTypes.THERMOSTAT,
        {
            CharacteristicsTypes.TEMPERATURE_CURRENT: 21,
            CharacteristicsTypes.TEMPERATURE_TARGET: 19,
            CharacteristicsTypes.HEATING_COOLING_CURRENT: 2,
            CharacteristicsTypes.HEATING_COOLING_TARGET: 2,
            CharacteristicsTypes.RELATIVE_HUMIDITY_CURRENT: 45,
            CharacteristicsTypes.RELATIVE_HUMIDITY_TARGET: 45,
        },
    )

    state = await helper.poll_and_get_state()
    assert state.state == HVACMode.COOL
    assert state.attributes["current_temperature"] == 21
    assert state.attributes["current_humidity"] == 45

    # Simulate that we are in heat/cool mode
    await helper.async_update(
        ServicesTypes.THERMOSTAT,
        {
            CharacteristicsTypes.TEMPERATURE_CURRENT: 21,
            CharacteristicsTypes.TEMPERATURE_TARGET: 21,
            CharacteristicsTypes.HEATING_COOLING_CURRENT: 0,
            CharacteristicsTypes.HEATING_COOLING_TARGET: 3,
        },
    )

    state = await helper.poll_and_get_state()
    assert state.state == HVACMode.HEAT_COOL


async def test_hvac_mode_vs_hvac_action(hass, utcnow):
    """Check that we haven't conflated hvac_mode and hvac_action."""
    helper = await setup_test_component(hass, create_thermostat_service)

    # Simulate that current temperature is above target temp
    # Heating might be on, but hvac_action currently 'off'
    await helper.async_update(
        ServicesTypes.THERMOSTAT,
        {
            CharacteristicsTypes.TEMPERATURE_CURRENT: 22,
            CharacteristicsTypes.TEMPERATURE_TARGET: 21,
            CharacteristicsTypes.HEATING_COOLING_CURRENT: 0,
            CharacteristicsTypes.HEATING_COOLING_TARGET: 1,
            CharacteristicsTypes.RELATIVE_HUMIDITY_CURRENT: 50,
            CharacteristicsTypes.RELATIVE_HUMIDITY_TARGET: 45,
        },
    )

    state = await helper.poll_and_get_state()
    assert state.state == "heat"
    assert state.attributes["hvac_action"] == "idle"

    # Simulate that current temperature is below target temp
    # Heating might be on and hvac_action currently 'heat'
    await helper.async_update(
        ServicesTypes.THERMOSTAT,
        {
            CharacteristicsTypes.TEMPERATURE_CURRENT: 19,
            CharacteristicsTypes.HEATING_COOLING_CURRENT: 1,
        },
    )

    state = await helper.poll_and_get_state()
    assert state.state == "heat"
    assert state.attributes["hvac_action"] == "heating"


def create_heater_cooler_service(accessory):
    """Define thermostat characteristics."""
    service = accessory.add_service(ServicesTypes.HEATER_COOLER)

    char = service.add_char(CharacteristicsTypes.TARGET_HEATER_COOLER_STATE)
    char.value = 0

    char = service.add_char(CharacteristicsTypes.CURRENT_HEATER_COOLER_STATE)
    char.value = 0

    char = service.add_char(CharacteristicsTypes.ACTIVE)
    char.value = 1

    char = service.add_char(CharacteristicsTypes.TEMPERATURE_COOLING_THRESHOLD)
    char.minValue = 7
    char.maxValue = 35
    char.value = 0

    char = service.add_char(CharacteristicsTypes.TEMPERATURE_HEATING_THRESHOLD)
    char.minValue = 7
    char.maxValue = 35
    char.value = 0

    char = service.add_char(CharacteristicsTypes.TEMPERATURE_CURRENT)
    char.value = 0

    char = service.add_char(CharacteristicsTypes.SWING_MODE)
    char.value = 0


# Test heater-cooler devices
def create_heater_cooler_service_min_max(accessory):
    """Define thermostat characteristics."""
    service = accessory.add_service(ServicesTypes.HEATER_COOLER)
    char = service.add_char(CharacteristicsTypes.TARGET_HEATER_COOLER_STATE)
    char.value = 1
    char.minValue = 1
    char.maxValue = 2


async def test_heater_cooler_respect_supported_op_modes_1(hass, utcnow):
    """Test that climate respects minValue/maxValue hints."""
    helper = await setup_test_component(hass, create_heater_cooler_service_min_max)
    state = await helper.poll_and_get_state()
    assert state.attributes["hvac_modes"] == ["heat", "cool", "off"]


def create_theater_cooler_service_valid_vals(accessory):
    """Define heater-cooler characteristics."""
    service = accessory.add_service(ServicesTypes.HEATER_COOLER)
    char = service.add_char(CharacteristicsTypes.TARGET_HEATER_COOLER_STATE)
    char.value = 1
    char.valid_values = [1, 2]


async def test_heater_cooler_respect_supported_op_modes_2(hass, utcnow):
    """Test that climate respects validValue hints."""
    helper = await setup_test_component(hass, create_theater_cooler_service_valid_vals)
    state = await helper.poll_and_get_state()
    assert state.attributes["hvac_modes"] == ["heat", "cool", "off"]


async def test_heater_cooler_change_thermostat_state(hass, utcnow):
    """Test that we can change the operational mode."""
    helper = await setup_test_component(hass, create_heater_cooler_service)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {"entity_id": "climate.testdevice", "hvac_mode": HVACMode.HEAT},
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.HEATER_COOLER,
        {
            CharacteristicsTypes.TARGET_HEATER_COOLER_STATE: TargetHeaterCoolerStateValues.HEAT,
        },
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {"entity_id": "climate.testdevice", "hvac_mode": HVACMode.COOL},
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.HEATER_COOLER,
        {
            CharacteristicsTypes.TARGET_HEATER_COOLER_STATE: TargetHeaterCoolerStateValues.COOL,
        },
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {"entity_id": "climate.testdevice", "hvac_mode": HVACMode.HEAT_COOL},
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.HEATER_COOLER,
        {
            CharacteristicsTypes.TARGET_HEATER_COOLER_STATE: TargetHeaterCoolerStateValues.AUTOMATIC,
        },
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {"entity_id": "climate.testdevice", "hvac_mode": HVACMode.OFF},
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.HEATER_COOLER,
        {
            CharacteristicsTypes.ACTIVE: ActivationStateValues.INACTIVE,
        },
    )


async def test_heater_cooler_change_thermostat_temperature(hass, utcnow):
    """Test that we can change the target temperature."""
    helper = await setup_test_component(hass, create_heater_cooler_service)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {"entity_id": "climate.testdevice", "hvac_mode": HVACMode.HEAT},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {"entity_id": "climate.testdevice", "temperature": 20},
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.HEATER_COOLER,
        {
            CharacteristicsTypes.TEMPERATURE_HEATING_THRESHOLD: 20,
        },
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {"entity_id": "climate.testdevice", "hvac_mode": HVACMode.COOL},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {"entity_id": "climate.testdevice", "temperature": 26},
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.HEATER_COOLER,
        {
            CharacteristicsTypes.TEMPERATURE_COOLING_THRESHOLD: 26,
        },
    )


async def test_heater_cooler_read_thermostat_state(hass, utcnow):
    """Test that we can read the state of a HomeKit thermostat accessory."""
    helper = await setup_test_component(hass, create_heater_cooler_service)

    # Simulate that heating is on
    await helper.async_update(
        ServicesTypes.HEATER_COOLER,
        {
            CharacteristicsTypes.TEMPERATURE_CURRENT: 19,
            CharacteristicsTypes.TEMPERATURE_COOLING_THRESHOLD: 21,
            CharacteristicsTypes.CURRENT_HEATER_COOLER_STATE: CurrentHeaterCoolerStateValues.HEATING,
            CharacteristicsTypes.TARGET_HEATER_COOLER_STATE: TargetHeaterCoolerStateValues.HEAT,
            CharacteristicsTypes.SWING_MODE: SwingModeValues.DISABLED,
        },
    )

    state = await helper.poll_and_get_state()
    assert state.state == HVACMode.HEAT
    assert state.attributes["current_temperature"] == 19
    assert state.attributes["min_temp"] == 7
    assert state.attributes["max_temp"] == 35

    # Simulate that cooling is on
    await helper.async_update(
        ServicesTypes.HEATER_COOLER,
        {
            CharacteristicsTypes.TEMPERATURE_CURRENT: 21,
            CharacteristicsTypes.TEMPERATURE_COOLING_THRESHOLD: 19,
            CharacteristicsTypes.CURRENT_HEATER_COOLER_STATE: CurrentHeaterCoolerStateValues.COOLING,
            CharacteristicsTypes.TARGET_HEATER_COOLER_STATE: TargetHeaterCoolerStateValues.COOL,
            CharacteristicsTypes.SWING_MODE: SwingModeValues.DISABLED,
        },
    )

    state = await helper.poll_and_get_state()
    assert state.state == HVACMode.COOL
    assert state.attributes["current_temperature"] == 21

    # Simulate that we are in auto mode
    await helper.async_update(
        ServicesTypes.HEATER_COOLER,
        {
            CharacteristicsTypes.TEMPERATURE_CURRENT: 21,
            CharacteristicsTypes.TEMPERATURE_COOLING_THRESHOLD: 21,
            CharacteristicsTypes.CURRENT_HEATER_COOLER_STATE: CurrentHeaterCoolerStateValues.COOLING,
            CharacteristicsTypes.TARGET_HEATER_COOLER_STATE: TargetHeaterCoolerStateValues.AUTOMATIC,
            CharacteristicsTypes.SWING_MODE: SwingModeValues.DISABLED,
        },
    )

    state = await helper.poll_and_get_state()
    assert state.state == HVACMode.HEAT_COOL


async def test_heater_cooler_hvac_mode_vs_hvac_action(hass, utcnow):
    """Check that we haven't conflated hvac_mode and hvac_action."""
    helper = await setup_test_component(hass, create_heater_cooler_service)

    # Simulate that current temperature is above target temp
    # Heating might be on, but hvac_action currently 'off'
    await helper.async_update(
        ServicesTypes.HEATER_COOLER,
        {
            CharacteristicsTypes.TEMPERATURE_CURRENT: 22,
            CharacteristicsTypes.TEMPERATURE_HEATING_THRESHOLD: 21,
            CharacteristicsTypes.CURRENT_HEATER_COOLER_STATE: CurrentHeaterCoolerStateValues.IDLE,
            CharacteristicsTypes.TARGET_HEATER_COOLER_STATE: TargetHeaterCoolerStateValues.HEAT,
            CharacteristicsTypes.SWING_MODE: SwingModeValues.DISABLED,
        },
    )

    state = await helper.poll_and_get_state()
    assert state.state == "heat"
    assert state.attributes["hvac_action"] == "idle"

    # Simulate that current temperature is below target temp
    # Heating might be on and hvac_action currently 'heat'
    await helper.async_update(
        ServicesTypes.HEATER_COOLER,
        {
            CharacteristicsTypes.TEMPERATURE_CURRENT: 19,
            CharacteristicsTypes.TEMPERATURE_HEATING_THRESHOLD: 21,
            CharacteristicsTypes.CURRENT_HEATER_COOLER_STATE: CurrentHeaterCoolerStateValues.HEATING,
            CharacteristicsTypes.TARGET_HEATER_COOLER_STATE: TargetHeaterCoolerStateValues.HEAT,
            CharacteristicsTypes.SWING_MODE: SwingModeValues.DISABLED,
        },
    )

    state = await helper.poll_and_get_state()
    assert state.state == "heat"
    assert state.attributes["hvac_action"] == "heating"


async def test_heater_cooler_change_swing_mode(hass, utcnow):
    """Test that we can change the swing mode."""
    helper = await setup_test_component(hass, create_heater_cooler_service)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_SWING_MODE,
        {"entity_id": "climate.testdevice", "swing_mode": "vertical"},
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.HEATER_COOLER,
        {
            CharacteristicsTypes.SWING_MODE: SwingModeValues.ENABLED,
        },
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_SWING_MODE,
        {"entity_id": "climate.testdevice", "swing_mode": "off"},
        blocking=True,
    )
    helper.async_assert_service_values(
        ServicesTypes.HEATER_COOLER,
        {
            CharacteristicsTypes.SWING_MODE: SwingModeValues.DISABLED,
        },
    )


async def test_heater_cooler_turn_off(hass, utcnow):
    """Test that both hvac_action and hvac_mode return "off" when turned off."""
    helper = await setup_test_component(hass, create_heater_cooler_service)

    # Simulate that the device is turned off but CURRENT_HEATER_COOLER_STATE still returns HEATING/COOLING
    await helper.async_update(
        ServicesTypes.HEATER_COOLER,
        {
            CharacteristicsTypes.ACTIVE: ActivationStateValues.INACTIVE,
            CharacteristicsTypes.CURRENT_HEATER_COOLER_STATE: CurrentHeaterCoolerStateValues.HEATING,
            CharacteristicsTypes.TARGET_HEATER_COOLER_STATE: TargetHeaterCoolerStateValues.HEAT,
        },
    )

    state = await helper.poll_and_get_state()
    assert state.state == "off"
    assert state.attributes["hvac_action"] == "off"
