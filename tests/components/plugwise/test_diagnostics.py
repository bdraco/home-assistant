"""Tests for the diagnostics data provided by the Plugwise integration."""
from unittest.mock import MagicMock

from aiohttp import ClientSession

from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry
from tests.components.diagnostics import get_diagnostics_for_config_entry


async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSession,
    mock_smile_adam: MagicMock,
    init_integration: MockConfigEntry,
) -> None:
    """Test diagnostics."""
    assert await get_diagnostics_for_config_entry(
        hass, hass_client, init_integration
    ) == {
        "gateway": {
            "smile_name": "Adam",
            "gateway_id": "fe799307f1624099878210aa0b9f1475",
            "heater_id": "90986d591dcd426cae3ec3e8111ff730",
            "cooling_present": False,
            "notifications": {
                "af82e4ccf9c548528166d38e560662a4": {
                    "warning": "Node Plug (with MAC address 000D6F000D13CB01, in room 'n.a.') has been unreachable since 23:03 2020-01-18. Please check the connection and restart the device."
                }
            },
        },
        "devices": {
            "df4a4a8169904cdb9c03d61a21f42140": {
                "dev_class": "zone_thermostat",
                "firmware": "2016-10-27T02:00:00+02:00",
                "hardware": "255",
                "location": "12493538af164a409c6a1c79e38afe1c",
                "model": "Lisa",
                "name": "Zone Lisa Bios",
                "zigbee_mac_address": "ABCD012345670A06",
                "vendor": "Plugwise",
                "lower_bound": 0.0,
                "upper_bound": 99.9,
                "resolution": 0.01,
                "preset_modes": ["home", "asleep", "away", "no_frost"],
                "active_preset": "away",
                "available_schedules": [
                    "CV Roan",
                    "Bios Schema met Film Avond",
                    "GF7  Woonkamer",
                    "Badkamer Schema",
                    "CV Jessie",
                ],
                "selected_schedule": "None",
                "last_used": "Badkamer Schema",
                "mode": "heat",
                "sensors": {"temperature": 16.5, "setpoint": 13.0, "battery": 67},
            },
            "b310b72a0e354bfab43089919b9a88bf": {
                "dev_class": "thermo_sensor",
                "firmware": "2019-03-27T01:00:00+01:00",
                "hardware": "1",
                "location": "c50f167537524366a5af7aa3942feb1e",
                "model": "Tom/Floor",
                "name": "Floor kraan",
                "zigbee_mac_address": "ABCD012345670A02",
                "vendor": "Plugwise",
                "lower_bound": 0.0,
                "upper_bound": 100.0,
                "resolution": 0.01,
                "sensors": {
                    "temperature": 26.0,
                    "setpoint": 21.5,
                    "temperature_difference": 3.5,
                    "valve_position": 100,
                },
            },
            "a2c3583e0a6349358998b760cea82d2a": {
                "dev_class": "thermo_sensor",
                "firmware": "2019-03-27T01:00:00+01:00",
                "hardware": "1",
                "location": "12493538af164a409c6a1c79e38afe1c",
                "model": "Tom/Floor",
                "name": "Bios Cv Thermostatic Radiator ",
                "zigbee_mac_address": "ABCD012345670A09",
                "vendor": "Plugwise",
                "lower_bound": 0.0,
                "upper_bound": 100.0,
                "resolution": 0.01,
                "sensors": {
                    "temperature": 17.2,
                    "setpoint": 13.0,
                    "battery": 62,
                    "temperature_difference": -0.2,
                    "valve_position": 0.0,
                },
            },
            "b59bcebaf94b499ea7d46e4a66fb62d8": {
                "dev_class": "zone_thermostat",
                "firmware": "2016-08-02T02:00:00+02:00",
                "hardware": "255",
                "location": "c50f167537524366a5af7aa3942feb1e",
                "model": "Lisa",
                "name": "Zone Lisa WK",
                "zigbee_mac_address": "ABCD012345670A07",
                "vendor": "Plugwise",
                "lower_bound": 0.0,
                "upper_bound": 99.9,
                "resolution": 0.01,
                "preset_modes": ["home", "asleep", "away", "no_frost"],
                "active_preset": "home",
                "available_schedules": [
                    "CV Roan",
                    "Bios Schema met Film Avond",
                    "GF7  Woonkamer",
                    "Badkamer Schema",
                    "CV Jessie",
                ],
                "selected_schedule": "GF7  Woonkamer",
                "last_used": "GF7  Woonkamer",
                "mode": "auto",
                "sensors": {"temperature": 20.9, "setpoint": 21.5, "battery": 34},
            },
            "fe799307f1624099878210aa0b9f1475": {
                "dev_class": "gateway",
                "firmware": "3.0.15",
                "hardware": "AME Smile 2.0 board",
                "location": "1f9dcf83fd4e4b66b72ff787957bfe5d",
                "mac_address": "012345670001",
                "model": "Adam",
                "name": "Adam",
                "zigbee_mac_address": "ABCD012345670101",
                "vendor": "Plugwise B.V.",
                "regulation_mode": "heating",
                "regulation_modes": [],
                "binary_sensors": {"plugwise_notification": True},
                "sensors": {"outdoor_temperature": 7.81},
            },
            "d3da73bde12a47d5a6b8f9dad971f2ec": {
                "dev_class": "thermo_sensor",
                "firmware": "2019-03-27T01:00:00+01:00",
                "hardware": "1",
                "location": "82fa13f017d240daa0d0ea1775420f24",
                "model": "Tom/Floor",
                "name": "Thermostatic Radiator Jessie",
                "zigbee_mac_address": "ABCD012345670A10",
                "vendor": "Plugwise",
                "lower_bound": 0.0,
                "upper_bound": 100.0,
                "resolution": 0.01,
                "sensors": {
                    "temperature": 17.1,
                    "setpoint": 15.0,
                    "battery": 62,
                    "temperature_difference": 0.1,
                    "valve_position": 0.0,
                },
            },
            "21f2b542c49845e6bb416884c55778d6": {
                "dev_class": "game_console",
                "firmware": "2019-06-21T02:00:00+02:00",
                "location": "cd143c07248f491493cea0533bc3d669",
                "model": "Plug",
                "name": "Playstation Smart Plug",
                "zigbee_mac_address": "ABCD012345670A12",
                "vendor": "Plugwise",
                "sensors": {
                    "electricity_consumed": 82.6,
                    "electricity_consumed_interval": 8.6,
                    "electricity_produced": 0.0,
                    "electricity_produced_interval": 0.0,
                },
                "switches": {"relay": True, "lock": False},
            },
            "78d1126fc4c743db81b61c20e88342a7": {
                "dev_class": "central_heating_pump",
                "firmware": "2019-06-21T02:00:00+02:00",
                "location": "c50f167537524366a5af7aa3942feb1e",
                "model": "Plug",
                "name": "CV Pomp",
                "zigbee_mac_address": "ABCD012345670A05",
                "vendor": "Plugwise",
                "sensors": {
                    "electricity_consumed": 35.6,
                    "electricity_consumed_interval": 7.37,
                    "electricity_produced": 0.0,
                    "electricity_produced_interval": 0.0,
                },
                "switches": {"relay": True},
            },
            "90986d591dcd426cae3ec3e8111ff730": {
                "dev_class": "heater_central",
                "location": "1f9dcf83fd4e4b66b72ff787957bfe5d",
                "model": "Unknown",
                "name": "OnOff",
                "binary_sensors": {"heating_state": True},
                "sensors": {
                    "water_temperature": 70.0,
                    "intended_boiler_temperature": 70.0,
                    "modulation_level": 1,
                },
            },
            "cd0ddb54ef694e11ac18ed1cbce5dbbd": {
                "dev_class": "vcr",
                "firmware": "2019-06-21T02:00:00+02:00",
                "location": "cd143c07248f491493cea0533bc3d669",
                "model": "Plug",
                "name": "NAS",
                "zigbee_mac_address": "ABCD012345670A14",
                "vendor": "Plugwise",
                "sensors": {
                    "electricity_consumed": 16.5,
                    "electricity_consumed_interval": 0.5,
                    "electricity_produced": 0.0,
                    "electricity_produced_interval": 0.0,
                },
                "switches": {"relay": True, "lock": True},
            },
            "4a810418d5394b3f82727340b91ba740": {
                "dev_class": "router",
                "firmware": "2019-06-21T02:00:00+02:00",
                "location": "cd143c07248f491493cea0533bc3d669",
                "model": "Plug",
                "name": "USG Smart Plug",
                "zigbee_mac_address": "ABCD012345670A16",
                "vendor": "Plugwise",
                "sensors": {
                    "electricity_consumed": 8.5,
                    "electricity_consumed_interval": 0.0,
                    "electricity_produced": 0.0,
                    "electricity_produced_interval": 0.0,
                },
                "switches": {"relay": True, "lock": True},
            },
            "02cf28bfec924855854c544690a609ef": {
                "dev_class": "vcr",
                "firmware": "2019-06-21T02:00:00+02:00",
                "location": "cd143c07248f491493cea0533bc3d669",
                "model": "Plug",
                "name": "NVR",
                "zigbee_mac_address": "ABCD012345670A15",
                "vendor": "Plugwise",
                "sensors": {
                    "electricity_consumed": 34.0,
                    "electricity_consumed_interval": 9.15,
                    "electricity_produced": 0.0,
                    "electricity_produced_interval": 0.0,
                },
                "switches": {"relay": True, "lock": True},
            },
            "a28f588dc4a049a483fd03a30361ad3a": {
                "dev_class": "settop",
                "firmware": "2019-06-21T02:00:00+02:00",
                "location": "cd143c07248f491493cea0533bc3d669",
                "model": "Plug",
                "name": "Fibaro HC2",
                "zigbee_mac_address": "ABCD012345670A13",
                "vendor": "Plugwise",
                "sensors": {
                    "electricity_consumed": 12.5,
                    "electricity_consumed_interval": 3.8,
                    "electricity_produced": 0.0,
                    "electricity_produced_interval": 0.0,
                },
                "switches": {"relay": True, "lock": True},
            },
            "6a3bf693d05e48e0b460c815a4fdd09d": {
                "dev_class": "zone_thermostat",
                "firmware": "2016-10-27T02:00:00+02:00",
                "hardware": "255",
                "location": "82fa13f017d240daa0d0ea1775420f24",
                "model": "Lisa",
                "name": "Zone Thermostat Jessie",
                "zigbee_mac_address": "ABCD012345670A03",
                "vendor": "Plugwise",
                "lower_bound": 0.0,
                "upper_bound": 99.9,
                "resolution": 0.01,
                "preset_modes": ["home", "asleep", "away", "no_frost"],
                "active_preset": "asleep",
                "available_schedules": [
                    "CV Roan",
                    "Bios Schema met Film Avond",
                    "GF7  Woonkamer",
                    "Badkamer Schema",
                    "CV Jessie",
                ],
                "selected_schedule": "CV Jessie",
                "last_used": "CV Jessie",
                "mode": "auto",
                "sensors": {"temperature": 17.2, "setpoint": 15.0, "battery": 37},
            },
            "680423ff840043738f42cc7f1ff97a36": {
                "dev_class": "thermo_sensor",
                "firmware": "2019-03-27T01:00:00+01:00",
                "hardware": "1",
                "location": "08963fec7c53423ca5680aa4cb502c63",
                "model": "Tom/Floor",
                "name": "Thermostatic Radiator Badkamer",
                "zigbee_mac_address": "ABCD012345670A17",
                "vendor": "Plugwise",
                "lower_bound": 0.0,
                "upper_bound": 100.0,
                "resolution": 0.01,
                "sensors": {
                    "temperature": 19.1,
                    "setpoint": 14.0,
                    "battery": 51,
                    "temperature_difference": -0.4,
                    "valve_position": 0.0,
                },
            },
            "f1fee6043d3642a9b0a65297455f008e": {
                "dev_class": "zone_thermostat",
                "firmware": "2016-10-27T02:00:00+02:00",
                "hardware": "255",
                "location": "08963fec7c53423ca5680aa4cb502c63",
                "model": "Lisa",
                "name": "Zone Thermostat Badkamer",
                "zigbee_mac_address": "ABCD012345670A08",
                "vendor": "Plugwise",
                "lower_bound": 0.0,
                "upper_bound": 99.9,
                "resolution": 0.01,
                "preset_modes": ["home", "asleep", "away", "no_frost"],
                "active_preset": "away",
                "available_schedules": [
                    "CV Roan",
                    "Bios Schema met Film Avond",
                    "GF7  Woonkamer",
                    "Badkamer Schema",
                    "CV Jessie",
                ],
                "selected_schedule": "Badkamer Schema",
                "last_used": "Badkamer Schema",
                "mode": "auto",
                "sensors": {"temperature": 18.9, "setpoint": 14.0, "battery": 92},
            },
            "675416a629f343c495449970e2ca37b5": {
                "dev_class": "router",
                "firmware": "2019-06-21T02:00:00+02:00",
                "location": "cd143c07248f491493cea0533bc3d669",
                "model": "Plug",
                "name": "Ziggo Modem",
                "zigbee_mac_address": "ABCD012345670A01",
                "vendor": "Plugwise",
                "sensors": {
                    "electricity_consumed": 12.2,
                    "electricity_consumed_interval": 2.97,
                    "electricity_produced": 0.0,
                    "electricity_produced_interval": 0.0,
                },
                "switches": {"relay": True, "lock": True},
            },
            "e7693eb9582644e5b865dba8d4447cf1": {
                "dev_class": "thermostatic_radiator_valve",
                "firmware": "2019-03-27T01:00:00+01:00",
                "hardware": "1",
                "location": "446ac08dd04d4eff8ac57489757b7314",
                "model": "Tom/Floor",
                "name": "CV Kraan Garage",
                "zigbee_mac_address": "ABCD012345670A11",
                "vendor": "Plugwise",
                "lower_bound": 0.0,
                "upper_bound": 100.0,
                "resolution": 0.01,
                "preset_modes": ["home", "asleep", "away", "no_frost"],
                "active_preset": "no_frost",
                "available_schedules": [
                    "CV Roan",
                    "Bios Schema met Film Avond",
                    "GF7  Woonkamer",
                    "Badkamer Schema",
                    "CV Jessie",
                ],
                "selected_schedule": "None",
                "last_used": "Badkamer Schema",
                "mode": "heat",
                "sensors": {
                    "temperature": 15.6,
                    "setpoint": 5.5,
                    "battery": 68,
                    "temperature_difference": 0.0,
                    "valve_position": 0.0,
                },
            },
        },
    }
