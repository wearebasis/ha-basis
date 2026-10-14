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
from homeassistant.util import slugify

from .const import DOMAIN
from .coordinator import (
    BasisConfigEntry,
    BasisDeviceCoordinator,
    SwitchboardDataCoordinator,
    circuit_identifier,
)
from .models import Subcircuit


def circuit_unique_id(key: str, serial: str, number: int) -> str:
    """Return the unique ID of a circuit entity, which follows the circuit position."""
    return f"basis_{key}_{serial}_circuit_{number}"


def panel_entity_id(domain: str, serial: str, *parts: str) -> str:
    """Return an entity ID from the panel serial, so that a rename does not make it stale."""
    return f"{domain}.{slugify(' '.join(('basis_panel', serial, *parts)))}"


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
    """Entity on the device of a switchboard, a site or a circuit."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: _CoordinatorT,
        unique_id: str,
        device_identifier: str | None = None,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = unique_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_identifier or coordinator.identifier)}
        )


class BasisLiveEntity(BasisEntity[SwitchboardDataCoordinator]):
    """Entity that reads the live data of a switchboard."""

    @property
    def available(self) -> bool:
        """Return False while the switchboard is disconnected, because its live data is stale."""
        data = self.coordinator.data
        return super().available and data is not None and data.connectivity.connected


class BasisSubcircuitEntity(BasisLiveEntity):
    """Entity on the device of one subcircuit, read from the live switchboard data."""

    def __init__(
        self, coordinator: SwitchboardDataCoordinator, subcircuit: Subcircuit, key: str
    ) -> None:
        """Initialize the entity."""
        super().__init__(
            coordinator,
            circuit_unique_id(key, coordinator.serial, subcircuit.number),
            circuit_identifier(coordinator.serial, subcircuit.number),
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
