from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_entry_oauth2_flow, device_registry as dr

from .const import (
    DOMAIN,
    BRAND,
    DEFAULT_MODEL,
    PLATFORMS,
    LOGGER,
)

from .coordinator import BoardsDiscoveryCoordinator, SwitchboardDataCoordinator, EnergyStatsCoordinator
from .api import BasisAPI, AsyncConfigEntryAuth


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Basis Panel from a config entry."""
    implementation = (
        await config_entry_oauth2_flow.async_get_config_entry_implementation(
            hass, entry
        )
    )

    # Create auth
    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)
    auth = AsyncConfigEntryAuth(session)

    # Get integration version from manifest
    integration = await hass.helpers.integration.async_get_integration(DOMAIN)
    integration_version = integration.version

    # Initialize API
    api = BasisAPI(auth, integration_version)

    # Set up data structure
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "boards_coordinator": None,
        "switchboard_coordinators": {},
        "energy_coordinators": {},
    }

    # Create boards discovery coordinator
    boards_coordinator = BoardsDiscoveryCoordinator(hass, entry, api)
    await boards_coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id]["boards_coordinator"] = boards_coordinator

    # Create a coordinator for each discovered switchboard
    await _async_setup_switchboard_coordinators(hass, entry, api, boards_coordinator)

    # Register devices for each switchboard
    await _async_register_switchboard_devices(hass, entry, boards_coordinator)

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for boards being added or removed
    @callback
    def _async_on_boards_update() -> None:
        """Handle boards discovery updates."""
        hass.async_create_task(
            _async_handle_boards_change(hass, entry, api, boards_coordinator)
        )

    entry.async_on_unload(
        boards_coordinator.async_add_listener(_async_on_boards_update)
    )

    return True


async def _async_setup_switchboard_coordinators(
    hass: HomeAssistant,
    entry: ConfigEntry,
    api: BasisAPI,
    boards_coordinator: BoardsDiscoveryCoordinator,
) -> None:
    """Set up data coordinators for each switchboard."""
    switchboard_coordinators = hass.data[DOMAIN][entry.entry_id]["switchboard_coordinators"]
    energy_coordinators = hass.data[DOMAIN][entry.entry_id]["energy_coordinators"]

    for serial in boards_coordinator.switchboard_serials:
        if serial not in switchboard_coordinators:
            # Create switchboard data coordinator
            coordinator = SwitchboardDataCoordinator(hass, api, serial)
            await coordinator.async_config_entry_first_refresh()
            switchboard_coordinators[serial] = coordinator
            LOGGER.debug(f"Created coordinator for switchboard {serial}")

            # Create energy stats coordinator
            energy_coordinator = EnergyStatsCoordinator(hass, api, serial)
            await energy_coordinator.async_config_entry_first_refresh()
            energy_coordinators[serial] = energy_coordinator
            LOGGER.debug(f"Created energy coordinator for switchboard {serial}")


async def _async_register_switchboard_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
    boards_coordinator: BoardsDiscoveryCoordinator,
) -> None:
    """Register each switchboard as a device."""
    device_registry = dr.async_get(hass)
    switchboard_coordinators = hass.data[DOMAIN][entry.entry_id]["switchboard_coordinators"]

    for board_info in boards_coordinator.data or []:
        serial = board_info["serial"]
        coordinator = switchboard_coordinators.get(serial)

        if coordinator and coordinator.data:
            switchboard_data = coordinator.data
            model = switchboard_data.get("model", DEFAULT_MODEL)
            subcircuits_version = switchboard_data.get("subcircuits", [{}])[0].get("config", {}).get("version", "Unknown")

            if (model == "unknown"):
                model = DEFAULT_MODEL

            device_registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, serial)},
                manufacturer=BRAND,
                name=f"Basis Panel {serial}",
                model=model,
                sw_version=switchboard_data.get("version"),
                hw_version=subcircuits_version,
            )
            LOGGER.debug(f"Registered device for switchboard {serial}")


async def _async_handle_boards_change(
    hass: HomeAssistant,
    entry: ConfigEntry,
    api: BasisAPI,
    boards_coordinator: BoardsDiscoveryCoordinator,
) -> None:
    """Handle added or removed switchboards."""
    switchboard_coordinators = hass.data[DOMAIN][entry.entry_id]["switchboard_coordinators"]
    energy_coordinators = hass.data[DOMAIN][entry.entry_id]["energy_coordinators"]

    current_serials = set(boards_coordinator.switchboard_serials)
    coordinator_serials = set(switchboard_coordinators.keys())

    # Also check device registry for any orphaned devices
    device_registry = dr.async_get(hass)
    registry_serials: set[str] = set()
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        for identifier in device.identifiers:
            if identifier[0] == DOMAIN:
                registry_serials.add(identifier[1])

    # Devices to remove: in registry but not in current API response
    removed_serials = registry_serials - current_serials
    # New boards: in API but not in our coordinators
    new_serials = current_serials - coordinator_serials

    if not new_serials and not removed_serials:
        return

    # Unload platforms first (removes entities)
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Handle removed boards
    if removed_serials:
        LOGGER.info(f"Removing switchboards: {removed_serials}")

        for serial in removed_serials:
            # Clean up coordinators
            switchboard_coordinators.pop(serial, None)
            energy_coordinators.pop(serial, None)

            # Remove device from registry
            device = device_registry.async_get_device(identifiers={(DOMAIN, serial)})
            if device:
                device_registry.async_remove_device(device.id)
                LOGGER.info(f"Removed device for switchboard {serial}")
            else:
                LOGGER.warning(f"Device not found for switchboard {serial}")

    # Handle new boards
    if new_serials:
        LOGGER.info(f"Setting up new switchboards: {new_serials}")

        for serial in new_serials:
            # Switchboard data coordinator
            coordinator = SwitchboardDataCoordinator(hass, api, serial)
            await coordinator.async_config_entry_first_refresh()
            switchboard_coordinators[serial] = coordinator

            # Energy stats coordinator
            energy_coordinator = EnergyStatsCoordinator(hass, api, serial)
            await energy_coordinator.async_config_entry_first_refresh()
            energy_coordinators[serial] = energy_coordinator

        # Register new devices
        await _async_register_switchboard_devices(hass, entry, boards_coordinator)

    # Reload platforms with updated coordinators
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
