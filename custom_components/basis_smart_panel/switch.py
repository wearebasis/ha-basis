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

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BasisConfigEntry, SwitchboardDataCoordinator
from .const import LABEL_ICON_MAP
from .entity import BasisSubcircuitEntity
from .models import Subcircuit


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BasisConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Basis switches."""
    async_add_entities(
        BasisCircuitSwitch(board.live, subcircuit)
        for board in config_entry.runtime_data.boards.values()
        for subcircuit in board.live.data.subcircuits
        if not subcircuit.is_spare and not subcircuit.standby_locked
    )


class BasisCircuitSwitch(BasisSubcircuitEntity, SwitchEntity):
    """Switch for controlling subcircuit standby state."""

    def __init__(
        self, coordinator: SwitchboardDataCoordinator, subcircuit: Subcircuit
    ) -> None:
        """Initialize the circuit switch."""
        super().__init__(coordinator, subcircuit, "switch")

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        return self.circuit_name()

    @property
    def icon(self) -> str:
        """Return the icon for this switch."""
        return LABEL_ICON_MAP.get(self.label or "", "mdi:power-socket")

    @property
    def is_on(self) -> bool | None:
        """Return True if the circuit is live."""
        subcircuit = self.subcircuit
        if subcircuit and subcircuit.live:
            return subcircuit.live.state == "LIVE"
        return None

    @property
    def available(self) -> bool:
        """Return True if the switch is available (board is connected)."""
        if not self.coordinator.last_update_success:
            return False
        if self.coordinator.data is None:
            return False
        return self.coordinator.data.connectivity.connected

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on the circuit (deactivate standby)."""
        await self.coordinator.api.set_subcircuit_standby(
            self.coordinator.serial,
            self._subcircuit_serial,
            False,
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off the circuit (activate standby)."""
        await self.coordinator.api.set_subcircuit_standby(
            self.coordinator.serial,
            self._subcircuit_serial,
            True,
        )
        await self.coordinator.async_request_refresh()
