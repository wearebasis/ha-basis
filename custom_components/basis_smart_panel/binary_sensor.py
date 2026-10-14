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

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BasisConfigEntry, SwitchboardDataCoordinator
from .entity import BasisEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BasisConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Basis binary sensors."""
    async_add_entities(
        BasisConnectivitySensor(board.live)
        for board in config_entry.runtime_data.boards.values()
    )


class BasisConnectivitySensor(BasisEntity[SwitchboardDataCoordinator], BinarySensorEntity):
    """Binary sensor for switchboard connectivity status."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_name = "Connectivity"

    def __init__(self, coordinator: SwitchboardDataCoordinator) -> None:
        """Initialize the connectivity sensor."""
        super().__init__(coordinator, f"basis_connectivity_{coordinator.serial}")

    @property
    def is_on(self) -> bool | None:
        """Return True if connected."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.connectivity.connected

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional state attributes."""
        if self.coordinator.data is None:
            return {}
        connectivity = self.coordinator.data.connectivity
        attrs = {}
        if connectivity.last_seen:
            attrs["last_seen"] = connectivity.last_seen
        if connectivity.disconnect_reason:
            attrs["disconnect_reason"] = connectivity.disconnect_reason
        return attrs
