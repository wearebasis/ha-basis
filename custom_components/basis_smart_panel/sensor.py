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

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    Platform,
    UnitOfPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
)

from .coordinator import (
    BasisBoardCoordinator,
    BasisConfigEntry,
    BasisDeviceCoordinator,
    SubcircuitEnergyCoordinator,
    SwitchboardDataCoordinator,
    circuit_identifier,
)
from .const import LABEL_ICON_MAP
from .entity import (
    BasisEntity,
    BasisLiveEntity,
    BasisSubcircuitEntity,
    async_add_basis_entities,
    circuit_unique_id,
    panel_entity_id,
)
from .models import EnergyStats, Subcircuit, Switchboard


@dataclass(frozen=True, kw_only=True)
class BasisDeviceSensorDescription[_DataT](SensorEntityDescription):
    """Sensor that reads one value from the data of a device coordinator."""

    value_fn: Callable[[_DataT], float | None]


@dataclass(frozen=True, kw_only=True)
class BasisSubcircuitSensorDescription(SensorEntityDescription):
    """Sensor that reads one value from the live data of a subcircuit."""

    value_fn: Callable[[Subcircuit], float | None]
    label_icon_fallback: str | None = None


PANEL_SENSORS: tuple[BasisDeviceSensorDescription[Switchboard], ...] = (
    BasisDeviceSensorDescription(
        key="power_panel",
        name="Current Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        icon="mdi:home-lightning-bolt",
        value_fn=lambda board: board.live.power if board.live else None,
    ),
    BasisDeviceSensorDescription(
        key="import_power",
        name="House Consumption Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        icon="mdi:home-lightning-bolt",
        value_fn=lambda board: board.live.import_power if board.live else None,
    ),
    BasisDeviceSensorDescription(
        key="export_power",
        name="Generation Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        icon="mdi:solar-power",
        value_fn=lambda board: board.live.export_power if board.live else None,
    ),
    BasisDeviceSensorDescription(
        key="current",
        name="Primary Current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        icon="mdi:current-ac",
        value_fn=lambda board: board.live.primary_current if board.live else None,
    ),
)

ENERGY_SENSORS: tuple[BasisDeviceSensorDescription[EnergyStats], ...] = (
    BasisDeviceSensorDescription(
        key="energy_today_import",
        name="Consumption Energy Today",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:lightning-bolt",
        value_fn=lambda energy: energy.today.import_kwh,
    ),
    BasisDeviceSensorDescription(
        key="energy_today_export",
        name="Generation Energy Today",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        value_fn=lambda energy: energy.today.export_kwh,
    ),
    BasisDeviceSensorDescription(
        key="energy_month_import",
        name="Consumption Energy This Month",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:lightning-bolt",
        value_fn=lambda energy: energy.month.import_kwh,
    ),
    BasisDeviceSensorDescription(
        key="energy_month_export",
        name="Generation Energy This Month",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        value_fn=lambda energy: energy.month.export_kwh,
    ),
)

SUBCIRCUIT_SENSORS: tuple[BasisSubcircuitSensorDescription, ...] = (
    BasisSubcircuitSensorDescription(
        key="power",
        name="Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        label_icon_fallback="mdi:flash",
        value_fn=lambda sub: sub.live.power if sub.live else None,
    ),
    BasisSubcircuitSensorDescription(
        key="current",
        name="Current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        icon="mdi:current-ac",
        value_fn=lambda sub: sub.live.primary_current if sub.live else None,
    ),
    BasisSubcircuitSensorDescription(
        key="voltage",
        name="Voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        icon="mdi:sine-wave",
        value_fn=lambda sub: sub.live.phase_voltage if sub.live else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BasisConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Basis sensors."""
    entities: list[SensorEntity] = []

    for board in config_entry.runtime_data.boards.values():
        entities.extend(BasisPanelSensor(board.live, d) for d in PANEL_SENSORS)
        entities.extend(BasisDeviceSensor(board.energy, d) for d in ENERGY_SENSORS)

        if board.live.data is None:
            continue
        for subcircuit in board.live.data.subcircuits:
            if subcircuit.is_spare:
                continue
            entities.extend(
                BasisSubcircuitSensor(board.live, subcircuit, d)
                for d in SUBCIRCUIT_SENSORS
            )
            entities.append(
                BasisSubcircuitImportEnergySensor(
                    board.subcircuit_energy, board.live, subcircuit
                )
            )
            entities.append(BasisCircuitStateSensor(board.live, subcircuit))

    for site_energy in config_entry.runtime_data.site_energy.values():
        entities.extend(BasisDeviceSensor(site_energy, d) for d in ENERGY_SENSORS)

    async_add_basis_entities(config_entry, async_add_entities, entities)


class BasisDeviceSensor(BasisEntity[BasisDeviceCoordinator[Any]], SensorEntity):
    """Sensor of one switchboard or one site."""

    entity_description: BasisDeviceSensorDescription[Any]

    def __init__(
        self,
        coordinator: BasisDeviceCoordinator[Any],
        description: BasisDeviceSensorDescription[Any],
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, f"basis_{description.key}_{coordinator.identifier}")
        self.entity_description = description
        # A site has no serial, so its sensors keep the ID that HA derives from the name.
        if isinstance(coordinator, BasisBoardCoordinator):
            self.entity_id = panel_entity_id(Platform.SENSOR, coordinator.serial, description.name)

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)


class BasisPanelSensor(BasisLiveEntity, BasisDeviceSensor):
    """Sensor of the live data of one switchboard."""


class BasisSubcircuitSensor(BasisSubcircuitEntity, SensorEntity):
    """Sensor of one subcircuit."""

    entity_description: BasisSubcircuitSensorDescription

    def __init__(
        self,
        coordinator: SwitchboardDataCoordinator,
        subcircuit: Subcircuit,
        description: BasisSubcircuitSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, subcircuit, description.key)
        self.entity_description = description
        self.entity_id = panel_entity_id(
            Platform.SENSOR, coordinator.serial, f"{subcircuit.number:02d}", description.name
        )

    @property
    def icon(self) -> str | None:
        fallback = self.entity_description.label_icon_fallback
        if fallback is None:
            return super().icon
        return LABEL_ICON_MAP.get(self.label or "", fallback)

    @property
    def native_value(self) -> float | None:
        subcircuit = self.subcircuit
        if subcircuit:
            return self.entity_description.value_fn(subcircuit)
        return None


class BasisSubcircuitImportEnergySensor(
    BasisEntity[SubcircuitEnergyCoordinator], SensorEntity
):
    """Sensor for subcircuit import energy (consumption)."""

    _attr_name = "Import Energy Today"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(
        self,
        coordinator: SubcircuitEnergyCoordinator,
        live: SwitchboardDataCoordinator,
        subcircuit: Subcircuit,
    ) -> None:
        super().__init__(
            coordinator,
            circuit_unique_id("energy_import", coordinator.serial, subcircuit.number),
            circuit_identifier(coordinator.serial, subcircuit.number),
        )
        self.entity_id = panel_entity_id(
            Platform.SENSOR, coordinator.serial, f"{subcircuit.number:02d}", self._attr_name
        )
        self._live = live
        self._subcircuit_number = subcircuit.number
        self._written: tuple[str, str] | None = None

    async def async_added_to_hass(self) -> None:
        """Also follow the live data, which gives the name and the icon."""
        await super().async_added_to_hass()
        self.async_on_remove(self._live.async_add_listener(self._handle_live_update))

    @callback
    def _handle_live_update(self) -> None:
        if (self.name, self.icon) != self._written:
            self.async_write_ha_state()

    @callback
    def async_write_ha_state(self) -> None:
        """Write the state and remember the name and the icon that it has."""
        self._written = (self.name, self.icon)
        super().async_write_ha_state()

    @property
    def _subcircuit(self) -> Subcircuit | None:
        if self._live.data is None:
            return None
        return self._live.data.subcircuit(self._subcircuit_number)

    @property
    def icon(self) -> str:
        subcircuit = self._subcircuit
        return LABEL_ICON_MAP.get(subcircuit.label if subcircuit else "", "mdi:lightning-bolt")

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._subcircuit_number)


CIRCUIT_STATES = ("LIVE", "SAFE", "STANDBY", "ELECTRICAL_FAULT", "SYSTEM_FAULT", "LOCKOUT")


class BasisCircuitStateSensor(BasisSubcircuitEntity, SensorEntity):
    """Diagnostic sensor that shows the state that the circuit reports."""

    _attr_name = "State"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_options = [state.lower() for state in CIRCUIT_STATES]
    _attr_translation_key = "circuit_state"

    def __init__(self, coordinator: SwitchboardDataCoordinator, subcircuit: Subcircuit) -> None:
        """Initialize the state sensor."""
        super().__init__(coordinator, subcircuit, "state")
        self.entity_id = panel_entity_id(
            Platform.SENSOR, coordinator.serial, f"{subcircuit.number:02d}", "state"
        )

    @property
    def native_value(self) -> str | None:
        subcircuit = self.subcircuit
        if subcircuit is None or subcircuit.live is None:
            return None
        state = subcircuit.live.known_state
        # HA rejects a value outside the options, and the API can add a state later.
        return state.lower() if state in CIRCUIT_STATES else None
