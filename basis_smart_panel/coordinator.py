from __future__ import annotations

from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from .api import BasisAPI


class BoardsDiscoveryCoordinator(DataUpdateCoordinator):
    """Coordinator to discover available switchboards periodically."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: BasisAPI,
    ) -> None:
        """Initialize the boards discovery coordinator."""
        super().__init__(
            hass,
            LOGGERFORHA,
            name=f"{DOMAIN}_boards_discovery",
            update_interval=BOARDS_DISCOVERY_INTERVAL,
        )
        self._api = api
        self._entry = entry
        self._known_serials: set[str] = set()

    async def _async_update_data(self) -> list[dict]:
        """Fetch available switchboards from the API."""
        switchboards = await self._api.get_available_switchboards()

        # Track newly discovered boards
        current_serials = {board["serial"] for board in switchboards}
        new_serials = current_serials - self._known_serials

        if new_serials:
            LOGGER.info(f"Discovered new switchboards: {new_serials}")

        self._known_serials = current_serials
        return switchboards

    @property
    def switchboard_serials(self) -> list[str]:
        """Return list of discovered switchboard serials."""
        if self.data is None:
            return []
        return [board["serial"] for board in self.data]


class SwitchboardDataCoordinator(DataUpdateCoordinator):
    """Coordinator for a single switchboard's data updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: BasisAPI,
        serial: str,
    ) -> None:
        """Initialize the switchboard data coordinator."""
        super().__init__(
            hass,
            LOGGERFORHA,
            name=f"{DOMAIN}_{serial}",
            update_interval=SWITCHBOARD_UPDATE_INTERVAL,
        )
        self._api = api
        self._serial = serial

    @property
    def serial(self) -> str:
        """Return the switchboard serial."""
        return self._serial

    async def _async_update_data(self) -> dict:
        """Fetch switchboard data from the API."""
        data = await self._api.get_switchboard_data(self._serial)
        return data.get("switchboard", {})


class EnergyStatsCoordinator(DataUpdateCoordinator):
    """Coordinator for energy statistics (today and this month)."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: BasisAPI,
        serial: str,
    ) -> None:
        """Initialize the energy stats coordinator."""
        super().__init__(
            hass,
            LOGGERFORHA,
            name=f"{DOMAIN}_{serial}_energy",
            update_interval=ENERGY_STATS_UPDATE_INTERVAL,
        )
        self._api = api
        self._serial = serial

    @property
    def serial(self) -> str:
        """Return the switchboard serial."""
        return self._serial

    async def _async_update_data(self) -> dict:
        """Fetch energy statistics from the API."""
        now = dt_util.now()

        # Start of today (midnight local time)
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Start of this month (first day at midnight local time)
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Fetch energy for today
        today_data = await self._api.get_switchboard_energy_usage(
            self._serial,
            start_of_today.isoformat(),
        )

        # Fetch energy for this month
        month_data = await self._api.get_switchboard_energy_usage(
            self._serial,
            start_of_month.isoformat(),
        )

        today_usage = today_data.get("switchboard", {}).get("totalSwitchboardEnergyUsage", {})
        month_usage = month_data.get("switchboard", {}).get("totalSwitchboardEnergyUsage", {})

        return {
            "today": {
                "import_kwh": today_usage.get("importKwh"),
                "export_kwh": today_usage.get("exportKwh"),
            },
            "month": {
                "import_kwh": month_usage.get("importKwh"),
                "export_kwh": month_usage.get("exportKwh"),
            },
        }
