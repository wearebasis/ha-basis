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
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import BasisApiError
from .coordinator import BasisConfigEntry, SwitchboardDataCoordinator
from .const import LABEL_ICON_MAP
from .entity import BasisSubcircuitEntity, async_add_basis_entities, panel_entity_id
from .models import Subcircuit


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BasisConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Basis switches."""
    async_add_basis_entities(
        config_entry,
        async_add_entities,
        [
            BasisCircuitSwitch(board.live, subcircuit)
            for board in config_entry.runtime_data.boards.values()
            if board.live.data is not None
            for subcircuit in board.live.data.subcircuits
            if not subcircuit.is_spare and not subcircuit.standby_locked
        ],
    )


class BasisCircuitSwitch(BasisSubcircuitEntity, SwitchEntity):
    """Switch for controlling subcircuit standby state."""

    _attr_name = None

    def __init__(
        self, coordinator: SwitchboardDataCoordinator, subcircuit: Subcircuit
    ) -> None:
        """Initialize the circuit switch."""
        super().__init__(coordinator, subcircuit, "switch")
        self.entity_id = panel_entity_id(
            Platform.SWITCH, coordinator.serial, f"{subcircuit.number:02d}"
        )

    @property
    def icon(self) -> str:
        """Return the icon for this switch."""
        return LABEL_ICON_MAP.get(self.label or "", "mdi:power-socket")

    @property
    def is_on(self) -> bool | None:
        """Return True if the circuit is live, False if it is in standby."""
        subcircuit = self.subcircuit
        if subcircuit is None or subcircuit.live is None:
            return None
        return {"LIVE": True, "STANDBY": False}.get(subcircuit.live.state)

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on the circuit (deactivate standby)."""
        await self._async_set_standby(False)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off the circuit (activate standby)."""
        await self._async_set_standby(True)

    @property
    def _circuit_name(self) -> str:
        device = self.device_entry
        if device is None:
            return self.entity_id
        return device.name_by_user or device.name or self.entity_id

    async def _async_set_standby(self, activate: bool) -> None:
        subcircuit = self.subcircuit
        if subcircuit is None:
            raise HomeAssistantError(f"{self._circuit_name} is not in the switchboard data")
        try:
            await self.coordinator.api.set_subcircuit_standby(
                self.coordinator.serial,
                subcircuit.serial,
                activate,
            )
        except BasisApiError as err:
            raise HomeAssistantError(
                f"Could not change the standby state of {self._circuit_name}: {err}"
            ) from err
        await self.coordinator.async_request_refresh()
