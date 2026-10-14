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

from collections.abc import Sequence
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_current_platform,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LABEL_NAME_MAP
from .coordinator import BasisConfigEntry, BasisDeviceCoordinator, SwitchboardDataCoordinator
from .models import Subcircuit


def circuit_name(number: int, subcircuit: Subcircuit | None, suffix: str = "") -> str:
    """Return "[NN] <name> · <suffix>", or "[NN] <suffix>" without circuit data."""
    prefix = f"[{number:02d}]"
    if subcircuit is None:
        return f"{prefix} {suffix or 'Circuit'}"
    # The display label is a label key unless the user named the circuit in the app.
    name = LABEL_NAME_MAP.get(subcircuit.display_label, subcircuit.display_label)
    return f"{prefix} {name} · {suffix}" if suffix else f"{prefix} {name}"


def circuit_unique_id(key: str, serial: str, number: int) -> str:
    """Return the unique ID of a circuit entity, which follows the circuit position."""
    return f"basis_{key}_{serial}_circuit_{number}"


@callback
def async_add_basis_entities(
    entry: BasisConfigEntry,
    async_add_entities: AddEntitiesCallback,
    entities: Sequence[Entity],
) -> None:
    """Add the entities and record them and their platform for the stale entity cleanup."""
    entry.runtime_data.unique_ids.update(
        entity.unique_id for entity in entities if entity.unique_id
    )
    entry.runtime_data.set_up_platforms.add(async_get_current_platform().domain)
    async_add_entities(entities)


class BasisEntity[_CoordinatorT: BasisDeviceCoordinator[Any]](
    CoordinatorEntity[_CoordinatorT]
):
    """Entity on the device of one switchboard or one site."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: _CoordinatorT, unique_id: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = unique_id
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, coordinator.identifier)})


class BasisSubcircuitEntity(BasisEntity[SwitchboardDataCoordinator]):
    """Entity of one subcircuit, read from the live switchboard data."""

    def __init__(
        self, coordinator: SwitchboardDataCoordinator, subcircuit: Subcircuit, key: str
    ) -> None:
        """Initialize the entity."""
        super().__init__(
            coordinator, circuit_unique_id(key, coordinator.serial, subcircuit.number)
        )
        self._subcircuit_number = subcircuit.number

    @property
    def subcircuit(self) -> Subcircuit | None:
        """Return the latest data of the subcircuit."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.subcircuit(self._subcircuit_number)

    @property
    def label(self) -> str | None:
        """Return the label of the subcircuit."""
        subcircuit = self.subcircuit
        return subcircuit.label if subcircuit else None

    def circuit_name(self, suffix: str = "") -> str:
        """Return the name of the entity for its circuit."""
        return circuit_name(self._subcircuit_number, self.subcircuit, suffix)
