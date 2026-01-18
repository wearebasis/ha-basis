from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    UnitOfPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
)

from .coordinator import SwitchboardDataCoordinator, EnergyStatsCoordinator
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
    """Set up the Basis sensors."""
    switchboard_coordinators: dict[str, SwitchboardDataCoordinator] = (
        hass.data[DOMAIN][config_entry.entry_id]["switchboard_coordinators"]
    )
    energy_coordinators: dict[str, EnergyStatsCoordinator] = (
        hass.data[DOMAIN][config_entry.entry_id]["energy_coordinators"]
    )

    entities = []

    for serial, coordinator in switchboard_coordinators.items():
        switchboard_data = coordinator.data
        if not switchboard_data:
            LOGGER.warning(f"No data for switchboard {serial}, skipping sensors")
            continue

        # Switchboard-level sensors
        entities.append(BasisPanelPowerSensor(coordinator))
        entities.append(BasisPanelImportPowerSensor(coordinator))
        entities.append(BasisPanelExportPowerSensor(coordinator))
        entities.append(BasisPanelCurrentSensor(coordinator))

        # Energy stats sensors
        energy_coordinator = energy_coordinators.get(serial)
        if energy_coordinator:
            entities.append(BasisEnergyTodayImportSensor(energy_coordinator))
            entities.append(BasisEnergyTodayExportSensor(energy_coordinator))
            entities.append(BasisEnergyMonthImportSensor(energy_coordinator))
            entities.append(BasisEnergyMonthExportSensor(energy_coordinator))

        # Subcircuit sensors (skip spare circuits)
        for subcircuit in switchboard_data.get("subcircuits", []):
            label = subcircuit.get("config", {}).get("label", "")
            if label == "spare":
                continue
            entities.append(BasisSubcircuitPowerSensor(coordinator, subcircuit))
            entities.append(BasisSubcircuitCurrentSensor(coordinator, subcircuit))
            entities.append(BasisSubcircuitVoltageSensor(coordinator, subcircuit))

    async_add_entities(entities)


# =============================================================================
# Switchboard-level sensors
# =============================================================================


class BasisPanelPowerSensor(CoordinatorEntity[SwitchboardDataCoordinator], SensorEntity):
    """Sensor for total panel power (net)."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:home-lightning-bolt"

    def __init__(self, coordinator: SwitchboardDataCoordinator) -> None:
        """Initialize the panel power sensor."""
        super().__init__(coordinator)
        self._serial = coordinator.serial

    @property
    def unique_id(self) -> str:
        return f"basis_power_panel_{self._serial}"

    @property
    def name(self) -> str:
        return "Current Power"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._serial)})

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        live_state = self.coordinator.data.get("liveState")
        if live_state:
            return live_state.get("power")
        return None


class BasisPanelImportPowerSensor(CoordinatorEntity[SwitchboardDataCoordinator], SensorEntity):
    """Sensor for panel import power."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:transmission-tower-import"

    def __init__(self, coordinator: SwitchboardDataCoordinator) -> None:
        super().__init__(coordinator)
        self._serial = coordinator.serial

    @property
    def unique_id(self) -> str:
        return f"basis_import_power_{self._serial}"

    @property
    def name(self) -> str:
        return "Import Power"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._serial)})

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        live_state = self.coordinator.data.get("liveState")
        if live_state:
            power_usage = live_state.get("powerUsage", {})
            return power_usage.get("importPower")
        return None


class BasisPanelExportPowerSensor(CoordinatorEntity[SwitchboardDataCoordinator], SensorEntity):
    """Sensor for panel export power (solar)."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:transmission-tower-export"

    def __init__(self, coordinator: SwitchboardDataCoordinator) -> None:
        super().__init__(coordinator)
        self._serial = coordinator.serial

    @property
    def unique_id(self) -> str:
        return f"basis_export_power_{self._serial}"

    @property
    def name(self) -> str:
        return "Export Power"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._serial)})

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        live_state = self.coordinator.data.get("liveState")
        if live_state:
            power_usage = live_state.get("powerUsage", {})
            return power_usage.get("exportPower")
        return None


class BasisPanelCurrentSensor(CoordinatorEntity[SwitchboardDataCoordinator], SensorEntity):
    """Sensor for panel primary current."""

    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_icon = "mdi:current-ac"

    def __init__(self, coordinator: SwitchboardDataCoordinator) -> None:
        super().__init__(coordinator)
        self._serial = coordinator.serial

    @property
    def unique_id(self) -> str:
        return f"basis_current_{self._serial}"

    @property
    def name(self) -> str:
        return "Primary Current"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._serial)})

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        live_state = self.coordinator.data.get("liveState")
        if live_state:
            return live_state.get("primaryCurrent")
        return None


# =============================================================================
# Energy statistics sensors
# =============================================================================


class BasisEnergyTodayImportSensor(CoordinatorEntity[EnergyStatsCoordinator], SensorEntity):
    """Sensor for energy imported today."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:lightning-bolt"

    def __init__(self, coordinator: EnergyStatsCoordinator) -> None:
        super().__init__(coordinator)
        self._serial = coordinator.serial

    @property
    def unique_id(self) -> str:
        return f"basis_energy_today_import_{self._serial}"

    @property
    def name(self) -> str:
        return "Energy Today Import"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._serial)})

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("today", {}).get("import_kwh")


class BasisEnergyTodayExportSensor(CoordinatorEntity[EnergyStatsCoordinator], SensorEntity):
    """Sensor for energy exported today (solar)."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:solar-power"

    def __init__(self, coordinator: EnergyStatsCoordinator) -> None:
        super().__init__(coordinator)
        self._serial = coordinator.serial

    @property
    def unique_id(self) -> str:
        return f"basis_energy_today_export_{self._serial}"

    @property
    def name(self) -> str:
        return "Energy Today Export"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._serial)})

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("today", {}).get("export_kwh")


class BasisEnergyMonthImportSensor(CoordinatorEntity[EnergyStatsCoordinator], SensorEntity):
    """Sensor for energy imported this month."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:lightning-bolt"

    def __init__(self, coordinator: EnergyStatsCoordinator) -> None:
        super().__init__(coordinator)
        self._serial = coordinator.serial

    @property
    def unique_id(self) -> str:
        return f"basis_energy_month_import_{self._serial}"

    @property
    def name(self) -> str:
        return "Energy This Month Import"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._serial)})

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("month", {}).get("import_kwh")


class BasisEnergyMonthExportSensor(CoordinatorEntity[EnergyStatsCoordinator], SensorEntity):
    """Sensor for energy exported this month (solar)."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:solar-power"

    def __init__(self, coordinator: EnergyStatsCoordinator) -> None:
        super().__init__(coordinator)
        self._serial = coordinator.serial

    @property
    def unique_id(self) -> str:
        return f"basis_energy_month_export_{self._serial}"

    @property
    def name(self) -> str:
        return "Energy This Month Export"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._serial)})

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("month", {}).get("export_kwh")


# =============================================================================
# Subcircuit sensors
# =============================================================================


class BasisSubcircuitPowerSensor(CoordinatorEntity[SwitchboardDataCoordinator], SensorEntity):
    """Sensor for subcircuit power."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(
        self, coordinator: SwitchboardDataCoordinator, subcircuit: dict
    ) -> None:
        super().__init__(coordinator)
        self._switchboard_serial = coordinator.serial
        self._subcircuit_serial = subcircuit["serial"]
        self._subcircuit_number = subcircuit["number"]

    @property
    def unique_id(self) -> str:
        return f"basis_power_{self._switchboard_serial}_{self._subcircuit_serial}"

    @property
    def name(self) -> str:
        subcircuit = self._get_subcircuit()
        if subcircuit:
            label_key = subcircuit["config"].get("label", "spare")
            friendly_name = LABEL_NAME_MAP.get(label_key, subcircuit["config"]["label"])
            return f"[{self._subcircuit_number:02d}] {friendly_name} Power"
        return f"[{self._subcircuit_number:02d}] Power"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._switchboard_serial)})

    @property
    def icon(self) -> str:
        subcircuit = self._get_subcircuit()
        if subcircuit:
            label_key = subcircuit["config"].get("label", "spare")
            return LABEL_ICON_MAP.get(label_key, "mdi:flash")
        return "mdi:flash"

    @property
    def native_value(self) -> float | None:
        subcircuit = self._get_subcircuit()
        if subcircuit:
            return subcircuit.get("liveState", {}).get("power")
        return None

    def _get_subcircuit(self) -> dict | None:
        if not self.coordinator.data:
            return None
        for subcircuit in self.coordinator.data.get("subcircuits", []):
            if subcircuit["serial"] == self._subcircuit_serial:
                return subcircuit
        return None


class BasisSubcircuitCurrentSensor(CoordinatorEntity[SwitchboardDataCoordinator], SensorEntity):
    """Sensor for subcircuit current."""

    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_icon = "mdi:current-ac"

    def __init__(
        self, coordinator: SwitchboardDataCoordinator, subcircuit: dict
    ) -> None:
        super().__init__(coordinator)
        self._switchboard_serial = coordinator.serial
        self._subcircuit_serial = subcircuit["serial"]
        self._subcircuit_number = subcircuit["number"]

    @property
    def unique_id(self) -> str:
        return f"basis_current_{self._switchboard_serial}_{self._subcircuit_serial}"

    @property
    def name(self) -> str:
        subcircuit = self._get_subcircuit()
        if subcircuit:
            label_key = subcircuit["config"].get("label", "spare")
            friendly_name = LABEL_NAME_MAP.get(label_key, subcircuit["config"]["label"])
            return f"[{self._subcircuit_number:02d}] {friendly_name} Current"
        return f"[{self._subcircuit_number:02d}] Current"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._switchboard_serial)})

    @property
    def native_value(self) -> float | None:
        subcircuit = self._get_subcircuit()
        if subcircuit:
            return subcircuit.get("liveState", {}).get("primaryCurrent")
        return None

    def _get_subcircuit(self) -> dict | None:
        if not self.coordinator.data:
            return None
        for subcircuit in self.coordinator.data.get("subcircuits", []):
            if subcircuit["serial"] == self._subcircuit_serial:
                return subcircuit
        return None


class BasisSubcircuitVoltageSensor(CoordinatorEntity[SwitchboardDataCoordinator], SensorEntity):
    """Sensor for subcircuit voltage."""

    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_icon = "mdi:sine-wave"

    def __init__(
        self, coordinator: SwitchboardDataCoordinator, subcircuit: dict
    ) -> None:
        super().__init__(coordinator)
        self._switchboard_serial = coordinator.serial
        self._subcircuit_serial = subcircuit["serial"]
        self._subcircuit_number = subcircuit["number"]

    @property
    def unique_id(self) -> str:
        return f"basis_voltage_{self._switchboard_serial}_{self._subcircuit_serial}"

    @property
    def name(self) -> str:
        subcircuit = self._get_subcircuit()
        if subcircuit:
            label_key = subcircuit["config"].get("label", "spare")
            friendly_name = LABEL_NAME_MAP.get(label_key, subcircuit["config"]["label"])
            return f"[{self._subcircuit_number:02d}] {friendly_name} Voltage"
        return f"[{self._subcircuit_number:02d}] Voltage"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._switchboard_serial)})

    @property
    def native_value(self) -> float | None:
        subcircuit = self._get_subcircuit()
        if subcircuit:
            return subcircuit.get("liveState", {}).get("phaseVoltage")
        return None

    def _get_subcircuit(self) -> dict | None:
        if not self.coordinator.data:
            return None
        for subcircuit in self.coordinator.data.get("subcircuits", []):
            if subcircuit["serial"] == self._subcircuit_serial:
                return subcircuit
        return None
