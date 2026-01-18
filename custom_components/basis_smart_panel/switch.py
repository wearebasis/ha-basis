from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import SwitchboardDataCoordinator
from .api import BasisAPI
from .const import (
    DOMAIN,
    LOGGER,
    LABEL_ICON_MAP,
    LABEL_NAME_MAP,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Basis switches."""
    api: BasisAPI = hass.data[DOMAIN][config_entry.entry_id]["api"]
    switchboard_coordinators: dict[str, SwitchboardDataCoordinator] = (
        hass.data[DOMAIN][config_entry.entry_id]["switchboard_coordinators"]
    )

    entities = []

    for serial, coordinator in switchboard_coordinators.items():
        switchboard_data = coordinator.data
        if not switchboard_data:
            LOGGER.warning(f"No data for switchboard {serial}, skipping switches")
            continue

        # Add switches (skip spare circuits and those with standby locked)
        for subcircuit in switchboard_data.get("subcircuits", []):
            config = subcircuit.get("config", {})
            label = config.get("label", "")
            standby_locked = config.get("standbyLocked", False)

            if label == "spare" or standby_locked:
                continue
            entities.append(BasisCircuitSwitch(coordinator, api, subcircuit))

    async_add_entities(entities)


class BasisCircuitSwitch(CoordinatorEntity[SwitchboardDataCoordinator], SwitchEntity):
    """Switch for controlling subcircuit standby state."""

    def __init__(
        self,
        coordinator: SwitchboardDataCoordinator,
        api: BasisAPI,
        subcircuit: dict,
    ) -> None:
        """Initialize the circuit switch."""
        super().__init__(coordinator)
        self._api = api
        self._switchboard_serial = coordinator.serial
        self._subcircuit_serial = subcircuit["serial"]
        self._subcircuit_number = subcircuit["number"]

    @property
    def unique_id(self) -> str:
        """Return unique ID for this entity."""
        return f"basis_switch_{self._switchboard_serial}_{self._subcircuit_serial}"

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        subcircuit = self._get_subcircuit()
        if subcircuit:
            label_key = subcircuit["config"].get("label", "spare")
            friendly_name = LABEL_NAME_MAP.get(label_key, subcircuit["config"]["label"])
            return f"[{self._subcircuit_number:02d}] {friendly_name}"
        return f"[{self._subcircuit_number:02d}] Circuit"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info to link this entity to its device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._switchboard_serial)},
        )

    @property
    def icon(self) -> str:
        """Return the icon for this switch."""
        subcircuit = self._get_subcircuit()
        if subcircuit:
            label_key = subcircuit["config"].get("label", "spare")
            return LABEL_ICON_MAP.get(label_key, "mdi:power-socket")
        return "mdi:power-socket"

    @property
    def is_on(self) -> bool | None:
        """Return True if the circuit is live."""
        subcircuit = self._get_subcircuit()
        if subcircuit:
            return subcircuit.get("liveState", {}).get("state") == "LIVE"
        return None

    @property
    def available(self) -> bool:
        """Return True if the switch is available (board is connected)."""
        if not self.coordinator.last_update_success:
            return False
        if not self.coordinator.data:
            return False
        connectivity = self.coordinator.data.get("connectivity", {})
        return connectivity.get("connected", False)

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on the circuit (deactivate standby)."""
        await self._api.set_subcircuit_standby(
            self._switchboard_serial,
            self._subcircuit_serial,
            False,
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off the circuit (activate standby)."""
        await self._api.set_subcircuit_standby(
            self._switchboard_serial,
            self._subcircuit_serial,
            True,
        )
        await self.coordinator.async_request_refresh()

    def _get_subcircuit(self) -> dict | None:
        """Get the current subcircuit data from coordinator."""
        if not self.coordinator.data:
            return None
        for subcircuit in self.coordinator.data.get("subcircuits", []):
            if subcircuit["serial"] == self._subcircuit_serial:
                return subcircuit
        return None
