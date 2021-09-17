import loggingimport logging
import math
from typing import Optional

import voluptuous as vol

from homeassistant import util
from homeassistant.components.sensor import (
    DEVICE_CLASSES_SCHEMA,
    ENTITY_ID_FORMAT,
    PLATFORM_SCHEMA,
)
from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    ATTR_TEMPERATURE,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_ENTITY_PICTURE_TEMPLATE,
    CONF_ICON_TEMPLATE,
    CONF_SENSORS,
    DEVICE_CLASS_HUMIDITY,
    DEVICE_CLASS_TEMPERATURE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    TEMP_CELSIUS,
    TEMP_FAHRENHEIT,
)
from homeassistant.core import callback
from homeassistant.exceptions import TemplateError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity, async_generate_entity_id
from homeassistant.helpers.event import async_track_state_change

_LOGGER = logging.getLogger(__name__)

CONF_TEMPERATURE_SENSOR = "temperature_sensor"
CONF_HUMIDITY_SENSOR = "humidity_sensor"
CONF_SENSOR_TYPES = "sensor_types"
ATTR_HUMIDITY = "humidity"
CONCENTRATION_GRAMS_PER_CUBIC_METER = "g/m³"

DEFAULT_SENSOR_TYPES = [
    "absolutehumidity",
    "heatindex",
    "dewpoint",
    "perception",
    "simmerindex",
    "simmerzone",
]

SENSOR_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TEMPERATURE_SENSOR): cv.entity_id,
        vol.Required(CONF_HUMIDITY_SENSOR): cv.entity_id,
        vol.Optional(CONF_SENSOR_TYPES, default=DEFAULT_SENSOR_TYPES): cv.ensure_list,
        vol.Optional(CONF_ICON_TEMPLATE): cv.template,
        vol.Optional(CONF_ENTITY_PICTURE_TEMPLATE): cv.template,
        vol.Optional(ATTR_FRIENDLY_NAME): cv.string,
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_SENSORS): cv.schema_with_slug_keys(SENSOR_SCHEMA),
    }
)

SENSOR_TYPES = {
    "absolutehumidity": [
        DEVICE_CLASS_HUMIDITY,
        "Absolute Humidity",
        CONCENTRATION_GRAMS_PER_CUBIC_METER,
    ],
    "heatindex": [DEVICE_CLASS_TEMPERATURE, "Heat Index", TEMP_CELSIUS],
    "dewpoint": [DEVICE_CLASS_TEMPERATURE, "Dew Point", TEMP_CELSIUS],
    "perception": [None, "Thermal Perception", None],
    "simmerindex": [DEVICE_CLASS_TEMPERATURE, "Simmer Index", TEMP_CELSIUS],
    "simmerzone": [None, "Simmer Zone", None],
}


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the Thermal Comfort sensors."""
    sensors = []

    for device, device_config in config[CONF_SENSORS].items():
        temperature_entity = device_config.get(CONF_TEMPERATURE_SENSOR)
        humidity_entity = device_config.get(CONF_HUMIDITY_SENSOR)
        config_sensor_types = device_config.get(CONF_SENSOR_TYPES)
        icon_template = device_config.get(CONF_ICON_TEMPLATE)
        entity_picture_template = device_config.get(CONF_ENTITY_PICTURE_TEMPLATE)
        friendly_name = device_config.get(ATTR_FRIENDLY_NAME, device)

        for sensor_type in SENSOR_TYPES:
            if sensor_type in config_sensor_types:
                sensors.append(
                    SensorThermalComfort(
                        hass,
                        device,
                        temperature_entity,
                        humidity_entity,
                        friendly_name,
                        icon_template,
                        entity_picture_template,
                        sensor_type,
                    )
                )
    if not sensors:
        _LOGGER.error("No sensors added")
        return False

    async_add_entities(sensors)
    return True


class SensorThermalComfort(Entity):
    """Representation of a Thermal Comfort Sensor."""

    def __init__(
        self,
        hass,
        device_id,
        temperature_entity,
        humidity_entity,
        friendly_name,
        icon_template,
        entity_picture_template,
        sensor_type,
    ):
        """Initialize the sensor."""
        self.hass = hass
        self.entity_id = async_generate_entity_id(
            ENTITY_ID_FORMAT, f"{device_id}_{sensor_type}", hass=hass
        )
        self._name = f"{friendly_name} {SENSOR_TYPES[sensor_type][1]}"
        self._unit_of_measurement = SENSOR_TYPES[sensor_type][2]
        self._state = None
        self._device_state_attributes = {}
        self._icon_template = icon_template
        self._entity_picture_template = entity_picture_template
        self._icon = None
        self._entity_picture = None
        self._temperature_entity = temperature_entity
        self._humidity_entity = humidity_entity
        self._device_class = SENSOR_TYPES[sensor_type][0]
        self._sensor_type = sensor_type
        self._temperature = None
        self._humidity = None

        async_track_state_change(
            self.hass, self._temperature_entity, self.temperature_state_listener
        )

        async_track_state_change(
            self.hass, self._humidity_entity, self.humidity_state_listener
        )

        temperature_state = hass.states.get(temperature_entity)
        if temperature_state and temperature_state.state not in (
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        ):
            self._temperature = self.temperature_state_as_celcius(temperature_state)

        humidity_state = hass.states.get(humidity_entity)
        if humidity_state and humidity_state.state not in (
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        ):
            self._humidity = float(humidity_state.state)

    def temperature_state_listener(self, entity, old_state, new_state):
        """Handle temperature device state changes."""
        if new_state and new_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            self._temperature = self.temperature_state_as_celcius(new_state)

        self.async_schedule_update_ha_state(True)

    def humidity_state_listener(self, entity, old_state, new_state):
        """Handle humidity device state changes."""
        if new_state and new_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            self._humidity = float(new_state.state)

        self.async_schedule_update_ha_state(True)

    def temperature_state_as_celcius(self, temperature_state):
        unit = temperature_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        temp = util.convert(temperature_state.state, float)
        if unit == TEMP_FAHRENHEIT:
            temp = util.temperature.fahrenheit_to_celsius(temp)
        return temp

    def computeDewPoint(self, temperature, humidity):
        """http://wahiduddin.net/calc/density_algorithms.htm"""
        A0 = 373.15 / (273.15 + temperature)
        SUM = -7.90298 * (A0 - 1)
        SUM += 5.02808 * math.log(A0, 10)
        SUM += -1.3816e-7 * (pow(10, (11.344 * (1 - 1 / A0))) - 1)
        SUM += 8.1328e-3 * (pow(10, (-3.49149 * (A0 - 1))) - 1)
        SUM += math.log(1013.246, 10)
        VP = pow(10, SUM - 3) * humidity
        Td = math.log(VP / 0.61078)
        Td = (241.88 * Td) / (17.558 - Td)
        return round(Td, 2)

    def computeHeatIndex(self, temperature, humidity):
        """http://www.wpc.ncep.noaa.gov/html/heatindex_equation.shtml"""
        fahrenheit = util.temperature.celsius_to_fahrenheit(temperature)
        hi = 0.5 * (
            fahrenheit + 61.0 + ((fahrenheit - 68.0) * 1.2) + (humidity * 0.094)
        )

        if hi > 79:
            hi = -42.379 + 2.04901523 * fahrenheit
            hi = hi + 10.14333127 * humidity
            hi = hi + -0.22475541 * fahrenheit * humidity
            hi = hi + -0.00683783 * pow(fahrenheit, 2)
            hi = hi + -0.05481717 * pow(humidity, 2)
            hi = hi + 0.00122874 * pow(fahrenheit, 2) * humidity
            hi = hi + 0.00085282 * fahrenheit * pow(humidity, 2)
            hi = hi + -0.00000199 * pow(fahrenheit, 2) * pow(humidity, 2)

        if humidity < 13 and fahrenheit >= 80 and fahrenheit <= 112:
            hi = hi - ((13 - humidity) * 0.25) * math.sqrt(
                (17 - abs(fahrenheit - 95)) * 0.05882
            )
        elif humidity > 85 and fahrenheit >= 80 and fahrenheit <= 87:
            hi = hi + ((humidity - 85) * 0.1) * ((87 - fahrenheit) * 0.2)

        return round(util.temperature.fahrenheit_to_celsius(hi), 2)

    def computePerception(self, temperature, humidity):
        """https://en.wikipedia.org/wiki/Dew_point"""
        dewPoint = self.computeDewPoint(temperature, humidity)
        if dewPoint < 10:
            return "A bit dry for some"
        elif dewPoint < 13:
            return "Very comfortable"
        elif dewPoint < 16:
            return "Comfortable"
        elif dewPoint < 18:
            return "OK for most"
        elif dewPoint < 21:
            return "Somewhat uncomfortable"
        elif dewPoint < 24:
            return "Very humid, quite uncomfortable"
        elif dewPoint < 26:
            return "Extremely uncomfortable"
        return "Severely high"

    def computeAbsoluteHumidity(self, temperature, humidity):
        """https://carnotcycle.wordpress.com/2012/08/04/how-to-convert-relative-humidity-to-absolute-humidity/"""
        absTemperature = temperature + 273.15
        absHumidity = 6.112
        absHumidity *= math.exp((17.67 * temperature) / (243.5 + temperature))
        absHumidity *= humidity
        absHumidity *= 2.1674
        absHumidity /= absTemperature
        return round(absHumidity, 2)

    def computeSimmerIndex(self, temperature, humidity):
        """https://www.vcalc.com/wiki/rklarsen/Summer+Simmer+Index"""
        fahrenheit = util.temperature.celsius_to_fahrenheit(temperature)

        if fahrenheit < 70:
            ssi = fahrenheit
        else:
            ssi = (
                1.98 * (fahrenheit - (0.55 - (0.0055 * humidity)) * (fahrenheit - 58.0))
                - 56.83
            )

        return round(util.temperature.fahrenheit_to_celsius(ssi), 2)

    def computeSimmerZone(self, temperature, humidity):
        """https://www.vcalc.com/wiki/rklarsen/Summer+Simmer+Index"""
        ssi = self.computeSimmerIndex(temperature, humidity)
        if ssi < 21.1:
            return ""
        if ssi < 25.0:
            return "Slightly cool"
        if ssi < 28.3:
            return "Comfortable"
        if ssi < 32.8:
            return "Slightly warm"
        if ssi < 37.8:
            return "Increasing discomfort"
        if ssi < 44.4:
            return "Extremely warm"
        if ssi < 51.7:
            return "Danger of heatstroke"
        if ssi < 65.6:
            return "Extreme danger of heatstroke"
        return "Circulatory collapse imminent"

    """Sensor Properties"""

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return self._device_state_attributes

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        return self._icon

    @property
    def device_class(self) -> Optional[str]:
        """Return the device class of the sensor."""
        return self._device_class

    @property
    def entity_picture(self):
        """Return the entity_picture to use in the frontend, if any."""
        return self._entity_picture

    @property
    def unit_of_measurement(self):
        """Return the unit_of_measurement of the device."""
        return self._unit_of_measurement

    @property
    def should_poll(self):
        """No polling needed."""
        return False

    async def async_update(self):
        """Update the state."""
        value = None
        if self._temperature and self._humidity:
            if self._sensor_type == "dewpoint":
                value = self.computeDewPoint(self._temperature, self._humidity)
            elif self._sensor_type == "heatindex":
                value = self.computeHeatIndex(self._temperature, self._humidity)
            elif self._sensor_type == "perception":
                value = self.computePerception(self._temperature, self._humidity)
            elif self._sensor_type == "absolutehumidity":
                value = self.computeAbsoluteHumidity(self._temperature, self._humidity)
            elif self._sensor_type == "simmerindex":
                value = self.computeSimmerIndex(self._temperature, self._humidity)
            elif self._sensor_type == "simmerzone":
                value = self.computeSimmerZone(self._temperature, self._humidity)
            elif self._sensor_type == "comfortratio":
                value = "comfortratio"

        self._state = value
        self._device_state_attributes[ATTR_TEMPERATURE] = self._temperature
        self._device_state_attributes[ATTR_HUMIDITY] = self._humidity

        for property_name, template in (
            ("_icon", self._icon_template),
            ("_entity_picture", self._entity_picture_template),
        ):
            if template is None:
                continue

            try:
                setattr(self, property_name, template.async_render())
            except TemplateError as ex:
                friendly_property_name = property_name[1:].replace("_", " ")
                if ex.args and ex.args[0].startswith(
                    "UndefinedError: 'None' has no attribute"
                ):
                    # Common during HA startup - so just a warning
                    _LOGGER.warning(
                        "Could not render %s template %s," " the state is unknown.",
                        friendly_property_name,
                        self._name,
                    )
                    continue

                try:
                    setattr(self, property_name, getattr(super(), property_name))
                except AttributeError:
                    _LOGGER.error(
                        "Could not render %s template %s: %s",
                        friendly_property_name,
                        self._name,
                        ex,
                    )
