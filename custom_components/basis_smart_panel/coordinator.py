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
from datetime import timedelta, tzinfo
from typing import ClassVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    LOGGER,
    LOGGERFORHA,
    BOARDS_DISCOVERY_INTERVAL,
    SWITCHBOARD_UPDATE_INTERVAL,
    ENERGY_STATS_UPDATE_INTERVAL,
)

from .api import BasisAPI, BasisApiError, BasisAuthError, BasisRateLimitError
from .models import EnergyStats, Site, Switchboard

type BasisConfigEntry = ConfigEntry[BasisData]


def site_identifier(site_id: str) -> str:
    """Return the device identifier of a site."""
    return f"site_{site_id}"


@dataclass
class BoardCoordinators:
    """The coordinators of one switchboard."""

    live: SwitchboardDataCoordinator
    energy: EnergyStatsCoordinator
    subcircuit_energy: SubcircuitEnergyCoordinator
    site_id: str
    layout: frozenset[tuple[int, bool, bool]] = frozenset()


@dataclass
class BasisData:
    """Runtime data of one Basis account."""

    api: BasisAPI
    discovery: BoardsDiscoveryCoordinator
    boards: dict[str, BoardCoordinators] = field(default_factory=dict)
    site_energy: dict[str, SiteEnergyCoordinator] = field(default_factory=dict)
    missing_polls: dict[str, int] = field(default_factory=dict)
    unique_ids: set[str] = field(default_factory=set)
    set_up_platforms: set[str] = field(default_factory=set)


class BasisCoordinator[_DataT](DataUpdateCoordinator[_DataT]):
    """Coordinator that turns API errors into the errors that HA expects."""

    async def _async_update_data(self) -> _DataT:
        try:
            return await self._async_fetch()
        except BasisAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except BasisRateLimitError as err:
            raise UpdateFailed(str(err), retry_after=err.retry_after) from err
        except BasisApiError as err:
            raise UpdateFailed(str(err)) from err

    async def _async_fetch(self) -> _DataT:
        raise NotImplementedError


class BoardsDiscoveryCoordinator(BasisCoordinator[list[Site]]):
    """Coordinator to discover available sites and switchboards periodically."""

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

    async def _async_fetch(self) -> list[Site]:
        """Fetch available sites from the API."""
        sites = await self._api.get_sites()

        current_serials = {serial for site in sites for serial in site.serials}
        new_serials = current_serials - self._known_serials

        if new_serials:
            LOGGER.info(f"Discovered new switchboards: {new_serials}")

        self._known_serials = current_serials
        return sites

    @property
    def sites(self) -> list[Site]:
        """Return the discovered sites."""
        return self.data or []

    @property
    def switchboard_serials(self) -> list[str]:
        """Return list of discovered switchboard serials."""
        return [serial for site in self.sites for serial in site.serials]


class BasisDeviceCoordinator[_DataT](BasisCoordinator[_DataT]):
    """Base for the coordinators of one device."""

    NAME_SUFFIX: ClassVar[str]
    UPDATE_INTERVAL: ClassVar[timedelta]

    def __init__(
        self,
        hass: HomeAssistant,
        entry: BasisConfigEntry,
        api: BasisAPI,
        identifier: str,
        time_zone: tzinfo | None = None,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGERFORHA,
            config_entry=entry,
            name=f"{DOMAIN}_{identifier}{self.NAME_SUFFIX}",
            update_interval=self.UPDATE_INTERVAL,
        )
        self.api = api
        self.identifier = identifier
        self.time_zone = time_zone


class BasisBoardCoordinator[_DataT](BasisDeviceCoordinator[_DataT]):
    """Base for the coordinators of one switchboard."""

    @property
    def serial(self) -> str:
        """Return the serial of the switchboard."""
        return self.identifier


class SwitchboardDataCoordinator(BasisBoardCoordinator[Switchboard]):
    """Coordinator for a single switchboard's data updates."""

    NAME_SUFFIX = ""
    UPDATE_INTERVAL = SWITCHBOARD_UPDATE_INTERVAL

    async def _async_fetch(self) -> Switchboard:
        """Fetch switchboard data from the API."""
        return await self.api.get_switchboard_data(self.serial)


class EnergyStatsCoordinator(BasisBoardCoordinator[EnergyStats]):
    """Coordinator for energy statistics (today and this month)."""

    NAME_SUFFIX = "_energy"
    UPDATE_INTERVAL = ENERGY_STATS_UPDATE_INTERVAL

    async def _async_fetch(self) -> EnergyStats:
        """Fetch energy statistics from the API."""
        start_of_today, start_of_month = _period_starts(self.time_zone)
        today = await self.api.get_switchboard_energy_usage(self.serial, start_of_today)
        month = await self.api.get_switchboard_energy_usage(self.serial, start_of_month)
        return EnergyStats(today=today, month=month)


class SubcircuitEnergyCoordinator(BasisBoardCoordinator[dict[int, float | None]]):
    """Coordinator for per-subcircuit energy statistics."""

    NAME_SUFFIX = "_subcircuit_energy"
    UPDATE_INTERVAL = ENERGY_STATS_UPDATE_INTERVAL

    async def _async_fetch(self) -> dict[int, float | None]:
        """Fetch today's import energy of each subcircuit."""
        start_of_today, _ = _period_starts(self.time_zone)
        return await self.api.get_subcircuit_energy_usage(self.serial, start_of_today)


class SiteEnergyCoordinator(BasisDeviceCoordinator[EnergyStats]):
    """Coordinator for the energy statistics of all switchboards of a site."""

    NAME_SUFFIX = "_energy"
    UPDATE_INTERVAL = ENERGY_STATS_UPDATE_INTERVAL

    def __init__(
        self,
        hass: HomeAssistant,
        entry: BasisConfigEntry,
        api: BasisAPI,
        site: Site,
        time_zone: tzinfo | None,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(hass, entry, api, site_identifier(site.id), time_zone)
        self.site_id = site.id

    async def _async_fetch(self) -> EnergyStats:
        """Fetch energy statistics from the API."""
        start_of_today, start_of_month = _period_starts(self.time_zone)
        today = await self.api.get_site_energy_usage(self.site_id, start_of_today)
        month = await self.api.get_site_energy_usage(self.site_id, start_of_month)
        return EnergyStats(today=today, month=month)


def _period_starts(time_zone: tzinfo | None) -> tuple[str, str]:
    """Return the start of today and of this month in the time zone, as ISO 8601.

    Without a time zone, use the time zone of HA.
    """
    now = dt_util.now(time_zone)
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_month = start_of_today.replace(day=1)
    return start_of_today.isoformat(), start_of_month.isoformat()
