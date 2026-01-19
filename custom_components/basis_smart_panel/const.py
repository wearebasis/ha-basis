import logging

from datetime import timedelta
from homeassistant.const import Platform

DOMAIN = "basis_smart_panel"
BRAND = "Basis NZ Ltd."
DEFAULT_MODEL = "GEN1"

API_BASE_URL = "https://api.wearebasis.io"

# oauth
OAUTH2_AUTHORIZE = "https://auth.wearebasis.com/authorize"
OAUTH2_TOKEN = "https://auth.wearebasis.com/oauth/token"
OAUTH2_SCOPE = "home openid profile email offline_access"
OAUTH2_AUDIENCE = "https://api.wearebasis.io"

# Interval for discovering new boards
BOARDS_DISCOVERY_INTERVAL = timedelta(minutes=5)

# Interval for polling switchboard data
SWITCHBOARD_UPDATE_INTERVAL = timedelta(seconds=5)

# Interval for polling energy statistics (less frequent)
ENERGY_STATS_UPDATE_INTERVAL = timedelta(minutes=5)

LOGGER = logging.getLogger(__package__)
LOGGERFORHA = logging.getLogger(f"{__package__}_HA")

PLATFORMS = (
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SWITCH,
)

# Label to icon mapping based on subcircuit labels
LABEL_ICON_MAP = {
    "spare": "mdi:help-circle",
    "power": "mdi:flash",
    "lights": "mdi:lightbulb",
    "range": "mdi:stove",
    "oven": "mdi:stove",
    "hob": "mdi:pot-steam",
    "airCon": "mdi:snowflake",
    "hvac": "mdi:air-conditioner",
    "hwc": "mdi:water-boiler",
    "ufh": "mdi:radiator",
    "evCharger": "mdi:ev-station",
    "pool": "mdi:pool",
    "spa": "mdi:hot-tub",
    "waterPump": "mdi:water-pump",
    "septicPump": "mdi:pump",
    "alarm": "mdi:alarm-light",
    "solar": "mdi:solar-power",
}

# Label to human-readable name mapping
LABEL_NAME_MAP = {
    "spare": "Spare",
    "power": "Power",
    "lights": "Lights",
    "range": "Range",
    "oven": "Oven",
    "hob": "Hob",
    "airCon": "Air Conditioning",
    "hvac": "HVAC",
    "hwc": "Hot Water Cylinder",
    "ufh": "Underfloor Heating",
    "evCharger": "EV Charger",
    "pool": "Pool",
    "spa": "Spa",
    "waterPump": "Water Pump",
    "septicPump": "Septic Pump",
    "alarm": "Alarm",
    "solar": "Solar",
}
