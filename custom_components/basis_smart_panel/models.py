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

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SubcircuitLiveState:
    """Live readings of one subcircuit."""

    state: str
    power: float
    primary_current: float
    phase_voltage: float


@dataclass(frozen=True, slots=True)
class Subcircuit:
    """One subcircuit of a switchboard."""

    serial: str
    number: int
    label: str
    config_version: str
    standby_locked: bool
    live: SubcircuitLiveState | None

    @property
    def is_spare(self) -> bool:
        """Return True if the electrician marked the subcircuit as spare."""
        return self.label == "spare"


@dataclass(frozen=True, slots=True)
class SwitchboardLiveState:
    """Live readings of a whole switchboard."""

    power: float
    import_power: float
    export_power: float
    primary_current: float


@dataclass(frozen=True, slots=True)
class Connectivity:
    """Cloud connection state of a switchboard."""

    connected: bool
    last_seen: str | None
    disconnect_reason: str | None


@dataclass(frozen=True, slots=True)
class Switchboard:
    """Live data of one switchboard."""

    serial: str
    model: str | None
    version: str | None
    connectivity: Connectivity
    live: SwitchboardLiveState | None
    subcircuits: tuple[Subcircuit, ...]

    def subcircuit(self, serial: str) -> Subcircuit | None:
        """Return the subcircuit with the serial, if the switchboard has it."""
        return next((sub for sub in self.subcircuits if sub.serial == serial), None)


@dataclass(frozen=True, slots=True)
class EnergyTotals:
    """Imported and exported energy in kWh; None means no data."""

    import_kwh: float | None
    export_kwh: float | None


@dataclass(frozen=True, slots=True)
class BoardEnergy:
    """Energy totals of a switchboard for today and this month."""

    today: EnergyTotals
    month: EnergyTotals
