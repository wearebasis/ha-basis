from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER
from .coordinator import SwitchboardDataCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Basis binary sensors."""
    switchboard_coordinators: dict[str, SwitchboardDataCoordinator] = (
        hass.data[DOMAIN][config_entry.entry_id]["switchboard_coordinators"]
    )

    entities = []

    for serial, coordinator in switchboard_coordinators.items():
        switchboard_data = coordinator.data
        if not switchboard_data:
            LOGGER.warning(f"No data for switchboard {serial}, skipping binary sensors")
            continue

        # Add connectivity sensor
        entities.append(BasisConnectivitySensor(coordinator))

    async_add_entities(entities)


class BasisConnectivitySensor(CoordinatorEntity[SwitchboardDataCoordinator], BinarySensorEntity):
    """Binary sensor for switchboard connectivity status."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: SwitchboardDataCoordinator) -> None:
        """Initialize the connectivity sensor."""
        super().__init__(coordinator)
        self._serial = coordinator.serial

    @property
    def unique_id(self) -> str:
        """Return unique ID for this entity."""
        return f"basis_connectivity_{self._serial}"

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return "Connectivity"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info to link this entity to its device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if connected."""
        if not self.coordinator.data:
            return None
        connectivity = self.coordinator.data.get("connectivity", {})
        return connectivity.get("connected", False)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # Always available - even if disconnected, the sensor shows that state
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional state attributes."""
        if not self.coordinator.data:
            return {}
        connectivity = self.coordinator.data.get("connectivity", {})
        attrs = {}
        if connectivity.get("updatedTimestamp"):
            attrs["last_seen"] = connectivity["updatedTimestamp"]
        if connectivity.get("disconnectReason"):
            attrs["disconnect_reason"] = connectivity["disconnectReason"]
        return attrs
