# Copyright Basis NZ Ltd 2026
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging

from datetime import timedelta
from homeassistant.const import Platform

DOMAIN = "basis_smart_panel"
BRAND = "Basis NZ Ltd."
DEFAULT_MODEL = "GEN1"

API_BASE_URL = "https://api.wearebasis.io"

# oauth
OAUTH2_CLIENT_ID = "BzlTBw4nMUPJ7dm229Roog9W76YW97bm"
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
