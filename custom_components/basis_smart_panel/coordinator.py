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

from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, ClassVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    LOGGER,
    LOGGERFORHA,
    BOARDS_DISCOVERY_INTERVAL,
    SWITCHBOARD_UPDATE_INTERVAL,
    ENERGY_STATS_UPDATE_INTERVAL,
)

from .models import BoardEnergy, Switchboard

if TYPE_CHECKING:
    from .api import BasisAPI

type BasisConfigEntry = ConfigEntry[BasisData]


@dataclass
class BoardCoordinators:
    """The coordinators of one switchboard."""

    live: SwitchboardDataCoordinator
    energy: EnergyStatsCoordinator
    subcircuit_energy: SubcircuitEnergyCoordinator


@dataclass
class BasisData:
    """Runtime data of one Basis account."""

    api: BasisAPI
    discovery: BoardsDiscoveryCoordinator
    boards: dict[str, BoardCoordinators] = field(default_factory=dict)


class BoardsDiscoveryCoordinator(DataUpdateCoordinator[list[str]]):
    """Coordinator to discover available switchboards periodically."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: BasisConfigEntry,
        api: BasisAPI,
    ) -> None:
        """Initialize the boards discovery coordinator."""
        super().__init__(
            hass,
            LOGGERFORHA,
            config_entry=entry,
            name=f"{DOMAIN}_boards_discovery",
            update_interval=BOARDS_DISCOVERY_INTERVAL,
        )
        self._api = api
        self._known_serials: set[str] = set()

    async def _async_update_data(self) -> list[str]:
        """Fetch available switchboards from the API."""
        serials = await self._api.get_available_switchboards()

        current_serials = set(serials)
        new_serials = current_serials - self._known_serials

        if new_serials:
            LOGGER.info(f"Discovered new switchboards: {new_serials}")

        self._known_serials = current_serials
        return serials

    @property
    def switchboard_serials(self) -> list[str]:
        """Return list of discovered switchboard serials."""
        return self.data or []


class BasisBoardCoordinator[_DataT](DataUpdateCoordinator[_DataT]):
    """Base for the coordinators of one switchboard."""

    NAME_SUFFIX: ClassVar[str]
    UPDATE_INTERVAL: ClassVar[timedelta]

    def __init__(
        self,
        hass: HomeAssistant,
        entry: BasisConfigEntry,
        api: BasisAPI,
        serial: str,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGERFORHA,
            config_entry=entry,
            name=f"{DOMAIN}_{serial}{self.NAME_SUFFIX}",
            update_interval=self.UPDATE_INTERVAL,
        )
        self.api = api
        self.serial = serial


class SwitchboardDataCoordinator(BasisBoardCoordinator[Switchboard]):
    """Coordinator for a single switchboard's data updates."""

    NAME_SUFFIX = ""
    UPDATE_INTERVAL = SWITCHBOARD_UPDATE_INTERVAL

    async def _async_update_data(self) -> Switchboard:
        """Fetch switchboard data from the API."""
        return await self.api.get_switchboard_data(self.serial)


class EnergyStatsCoordinator(BasisBoardCoordinator[BoardEnergy]):
    """Coordinator for energy statistics (today and this month)."""

    NAME_SUFFIX = "_energy"
    UPDATE_INTERVAL = ENERGY_STATS_UPDATE_INTERVAL

    async def _async_update_data(self) -> BoardEnergy:
        """Fetch energy statistics from the API."""
        now = dt_util.now()
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        today = await self.api.get_switchboard_energy_usage(
            self.serial,
            start_of_today.isoformat(),
        )
        month = await self.api.get_switchboard_energy_usage(
            self.serial,
            start_of_month.isoformat(),
        )
        return BoardEnergy(today=today, month=month)


class SubcircuitEnergyCoordinator(BasisBoardCoordinator[dict[str, float | None]]):
    """Coordinator for per-subcircuit energy statistics."""

    NAME_SUFFIX = "_subcircuit_energy"
    UPDATE_INTERVAL = ENERGY_STATS_UPDATE_INTERVAL

    async def _async_update_data(self) -> dict[str, float | None]:
        """Fetch today's import energy of each subcircuit."""
        now = dt_util.now()
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        return await self.api.get_subcircuit_energy_usage(
            self.serial,
            start_of_today.isoformat(),
        )
