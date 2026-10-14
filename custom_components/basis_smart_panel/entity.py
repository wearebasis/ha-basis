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

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LABEL_NAME_MAP
from .coordinator import BasisBoardCoordinator, SwitchboardDataCoordinator
from .models import Subcircuit


class BasisEntity[_CoordinatorT: BasisBoardCoordinator[Any]](
    CoordinatorEntity[_CoordinatorT]
):
    """Entity on the device of one switchboard."""

    def __init__(self, coordinator: _CoordinatorT, unique_id: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = unique_id
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, coordinator.serial)})


class BasisSubcircuitEntity(BasisEntity[SwitchboardDataCoordinator]):
    """Entity of one subcircuit, read from the live switchboard data."""

    def __init__(
        self, coordinator: SwitchboardDataCoordinator, subcircuit: Subcircuit, key: str
    ) -> None:
        """Initialize the entity."""
        super().__init__(
            coordinator, f"basis_{key}_{coordinator.serial}_{subcircuit.serial}"
        )
        self._subcircuit_serial = subcircuit.serial
        self._subcircuit_number = subcircuit.number

    @property
    def subcircuit(self) -> Subcircuit | None:
        """Return the latest data of the subcircuit."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.subcircuit(self._subcircuit_serial)

    @property
    def label(self) -> str | None:
        """Return the label of the subcircuit."""
        subcircuit = self.subcircuit
        return subcircuit.label if subcircuit else None

    def circuit_name(self, suffix: str | None = None) -> str:
        """Return "[NN] <label> <suffix>", or "[NN] <suffix>" without data."""
        number = f"[{self._subcircuit_number:02d}]"
        if (label := self.label) is None:
            return f"{number} {suffix or 'Circuit'}"
        name = LABEL_NAME_MAP.get(label, label)
        return f"{number} {name} {suffix}" if suffix else f"{number} {name}"
