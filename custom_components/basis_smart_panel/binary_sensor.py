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
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BasisConfigEntry, SwitchboardDataCoordinator
from .entity import (
    BasisEntity,
    BasisSubcircuitEntity,
    async_add_basis_entities,
    panel_entity_id,
)
from .models import Subcircuit


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BasisConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Basis binary sensors."""
    boards = config_entry.runtime_data.boards.values()
    async_add_basis_entities(
        config_entry,
        async_add_entities,
        [
            *(BasisConnectivitySensor(board.live) for board in boards),
            *(
                BasisCircuitFaultSensor(board.live, subcircuit)
                for board in boards
                if board.live.data is not None
                for subcircuit in board.live.data.subcircuits
                if not subcircuit.is_spare
            ),
        ],
    )


class BasisConnectivitySensor(BasisEntity[SwitchboardDataCoordinator], BinarySensorEntity):
    """Binary sensor for switchboard connectivity status."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Connectivity"

    def __init__(self, coordinator: SwitchboardDataCoordinator) -> None:
        """Initialize the connectivity sensor."""
        super().__init__(coordinator, f"basis_connectivity_{coordinator.serial}")
        self.entity_id = panel_entity_id(Platform.BINARY_SENSOR, coordinator.serial, "connectivity")

    @property
    def is_on(self) -> bool | None:
        """Return True if connected."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.connectivity.connected

    @property
    def extra_state_attributes(self) -> dict:
        """Return the last contact and the reason while the panel is disconnected."""
        if self.coordinator.data is None:
            return {}
        connectivity = self.coordinator.data.connectivity
        # While connected, last_seen changes on every poll and would write a new state.
        if connectivity.connected:
            return {}
        attrs = {}
        if connectivity.last_seen:
            attrs["last_seen"] = connectivity.last_seen
        if connectivity.disconnect_reason:
            attrs["disconnect_reason"] = connectivity.disconnect_reason
        return attrs


class BasisCircuitFaultSensor(BasisSubcircuitEntity, BinarySensorEntity):
    """Problem sensor that is on while the circuit reports an electrical fault."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_name = "Fault"

    def __init__(self, coordinator: SwitchboardDataCoordinator, subcircuit: Subcircuit) -> None:
        """Initialize the fault sensor."""
        super().__init__(coordinator, subcircuit, "fault")
        self.entity_id = panel_entity_id(
            Platform.BINARY_SENSOR, coordinator.serial, f"{subcircuit.number:02d}", "fault"
        )

    @property
    def is_on(self) -> bool | None:
        """Return True while the circuit reports an electrical fault."""
        subcircuit = self.subcircuit
        if subcircuit is None or subcircuit.live is None:
            return None
        state = subcircuit.live.known_state
        return None if state is None else state == "ELECTRICAL_FAULT"
