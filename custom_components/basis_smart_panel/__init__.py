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

import json
from functools import partial

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    config_entry_oauth2_flow,
    device_registry as dr,
    entity_registry as er,
)
from .config_flow import BasisOAuth2Implementation, _decode_jwt_payload
from .const import (
    DOMAIN,
    BRAND,
    DEFAULT_MODEL,
    OAUTH2_CLIENT_ID,
    OAUTH2_AUTHORIZE,
    OAUTH2_TOKEN,
    PLATFORMS,
    LOGGER,
)

from .coordinator import (
    BasisConfigEntry,
    BasisData,
    BoardCoordinators,
    BoardsDiscoveryCoordinator,
    EnergyStatsCoordinator,
    SubcircuitEnergyCoordinator,
    SwitchboardDataCoordinator,
)
from .api import BasisAPI, AsyncConfigEntryAuth
from .entity import circuit_unique_id

BOARD_REMOVAL_POLLS = 3
MODULE_KEYS = ("power", "current", "voltage", "switch", "energy_import")


async def async_setup(hass: HomeAssistant, config) -> bool:
    """Set up the Basis Smart Panel component."""
    config_entry_oauth2_flow.async_register_implementation(
        hass,
        DOMAIN,
        BasisOAuth2Implementation(
            hass,
            DOMAIN,
            OAUTH2_CLIENT_ID,
            authorize_url=OAUTH2_AUTHORIZE,
            token_url=OAUTH2_TOKEN,
            client_secret="",
            code_verifier_length=128,
        ),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: BasisConfigEntry) -> bool:
    """Set up Basis Panel from a config entry."""
    # Migrate legacy unique_id from static DOMAIN to Auth0 user sub
    if entry.unique_id == DOMAIN:
        token_data = entry.data.get("token", entry.data)
        id_token = token_data.get("id_token")
        if id_token:
            try:
                claims = _decode_jwt_payload(id_token)
                new_uid = claims.get("sub")
                if new_uid:
                    hass.config_entries.async_update_entry(entry, unique_id=new_uid)
                    LOGGER.info("Migrated unique_id from '%s' to '%s'", DOMAIN, new_uid)
            except (ValueError, json.JSONDecodeError) as err:
                LOGGER.warning("Could not migrate unique_id: %s", err)

    implementation = (
        await config_entry_oauth2_flow.async_get_config_entry_implementation(
            hass, entry
        )
    )

    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)
    auth = AsyncConfigEntryAuth(session)
    integration = hass.data["integrations"][DOMAIN]
    api = BasisAPI(auth, integration.version)

    discovery = BoardsDiscoveryCoordinator(hass, entry, api)
    await discovery.async_config_entry_first_refresh()
    entry.runtime_data = BasisData(api=api, discovery=discovery)

    for serial in discovery.switchboard_serials:
        if serial not in entry.runtime_data.boards:
            entry.runtime_data.boards[serial] = await _async_setup_board(
                hass, entry, api, serial
            )

    await _async_register_switchboard_devices(hass, entry)
    _async_migrate_circuit_unique_ids(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_remove_stale_entities(hass, entry)

    @callback
    def _async_on_discovery_update() -> None:
        _async_check_boards(hass, entry)

    entry.async_on_unload(discovery.async_add_listener(_async_on_discovery_update))
    for board in entry.runtime_data.boards.values():
        entry.async_on_unload(
            board.live.async_add_listener(partial(_async_check_circuits, hass, entry, board))
        )
        entry.async_on_unload(
            board.live.async_add_listener(partial(_async_sync_device_name, hass, entry, board))
        )

    return True


async def _async_setup_board(
    hass: HomeAssistant, entry: BasisConfigEntry, api: BasisAPI, serial: str
) -> BoardCoordinators:
    """Create the coordinators of one switchboard and fetch their first data.

    A failed fetch does not stop the setup. The entities of that switchboard
    stay unavailable until the coordinator gets data.
    """
    board = BoardCoordinators(
        live=SwitchboardDataCoordinator(hass, entry, api, serial),
        energy=EnergyStatsCoordinator(hass, entry, api, serial),
        subcircuit_energy=SubcircuitEnergyCoordinator(hass, entry, api, serial),
    )
    for coordinator in (board.live, board.energy, board.subcircuit_energy):
        await coordinator.async_refresh()
    if board.live.data is not None:
        board.layout = board.live.data.circuit_layout
    LOGGER.debug("Created coordinators for switchboard %s", serial)
    return board


async def _async_register_switchboard_devices(
    hass: HomeAssistant, entry: BasisConfigEntry
) -> None:
    """Register each switchboard as a device."""
    device_registry = dr.async_get(hass)
    data = entry.runtime_data

    for serial in data.discovery.switchboard_serials:
        board = data.boards.get(serial)
        if board is None:
            continue

        # Without data, keep the name of an existing device; a new one gets the default.
        details: dict = {"default_name": _device_name(serial, None)}
        if (switchboard := board.live.data) is not None:
            model = switchboard.model
            if (model == "unknown"):
                model = DEFAULT_MODEL
            details = {
                "name": _device_name(serial, switchboard.name),
                "model": model,
                "sw_version": switchboard.version,
                "hw_version": (
                    switchboard.subcircuits[0].config_version
                    if switchboard.subcircuits
                    else "Unknown"
                ),
            }

        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, serial)},
            manufacturer=BRAND,
            serial_number=serial,
            **details,
        )
        LOGGER.debug(f"Registered device for switchboard {serial}")


@callback
def _async_check_boards(hass: HomeAssistant, entry: BasisConfigEntry) -> None:
    """Reload the entry when a switchboard appears or stays missing."""
    data = entry.runtime_data
    if not data.discovery.last_update_success:
        return

    current = set(data.discovery.switchboard_serials)
    if new := current - set(data.boards):
        LOGGER.info("Found new switchboards %s, reloading", new)
        hass.config_entries.async_schedule_reload(entry.entry_id)
        return

    # An empty list is more likely an API fault than the loss of every board.
    if not current:
        return

    device_registry = dr.async_get(hass)
    reload = False
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        serial = _device_serial(device)
        if serial is None:
            continue
        if serial in current:
            data.missing_polls.pop(serial, None)
            continue
        data.missing_polls[serial] = data.missing_polls.get(serial, 0) + 1
        if data.missing_polls[serial] < BOARD_REMOVAL_POLLS:
            continue
        LOGGER.info("Switchboard %s is no longer in the account, removing it", serial)
        device_registry.async_remove_device(device.id)
        reload |= serial in data.boards

    if reload:
        hass.config_entries.async_schedule_reload(entry.entry_id)


@callback
def _async_check_circuits(
    hass: HomeAssistant, entry: BasisConfigEntry, board: BoardCoordinators
) -> None:
    """Reload the entry when the circuits that have entities change."""
    if not board.live.last_update_success or board.live.data is None:
        return
    layout = board.live.data.circuit_layout
    # An empty list is more likely an API fault than the loss of every circuit.
    if layout and layout != board.layout:
        LOGGER.info("The circuits of switchboard %s changed, reloading", board.live.serial)
        hass.config_entries.async_schedule_reload(entry.entry_id)


@callback
def _async_migrate_circuit_unique_ids(hass: HomeAssistant, entry: BasisConfigEntry) -> None:
    """Move circuit entities from the module serial to the circuit position."""
    renames: dict[str, tuple[str, str]] = {}
    for serial, board in entry.runtime_data.boards.items():
        if board.live.data is None:
            continue
        for sub in board.live.data.subcircuits:
            for key in MODULE_KEYS:
                prefix = f"basis_{key}_{serial}_"
                renames[f"{prefix}{sub.serial}"] = (
                    prefix,
                    circuit_unique_id(key, serial, sub.number),
                )

    entity_registry = er.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if (rename := renames.get(registry_entry.unique_id)) is None:
            continue
        prefix, new_unique_id = rename
        if entity_registry.async_get_entity_id(registry_entry.domain, DOMAIN, new_unique_id):
            continue
        if (original := _replaced_original(entity_registry, registry_entry, prefix, renames)):
            LOGGER.info(
                "Removing %s and keeping %s, the entity from before the module was replaced",
                registry_entry.entity_id,
                original.entity_id,
            )
            entity_registry.async_remove(registry_entry.entity_id)
            registry_entry = original
        entity_registry.async_update_entity(registry_entry.entity_id, new_unique_id=new_unique_id)


def _replaced_original(
    entity_registry: er.EntityRegistry,
    registry_entry: er.RegistryEntry,
    prefix: str,
    renames: dict[str, tuple[str, str]],
) -> er.RegistryEntry | None:
    """Return the entity of an earlier module at the same position, if the user replaced it.

    HA gave the entity of the new module the entity ID of the earlier one with a "_2" suffix.
    """
    base, _, suffix = registry_entry.entity_id.rpartition("_")
    if not suffix.isdigit() or (original := entity_registry.async_get(base)) is None:
        return None
    unique_id = original.unique_id
    if (
        original.config_entry_id != registry_entry.config_entry_id
        or not unique_id.startswith(prefix)
        or unique_id.startswith(f"{prefix}circuit_")
        or unique_id in renames
    ):
        return None
    return original


@callback
def _async_remove_stale_entities(hass: HomeAssistant, entry: BasisConfigEntry) -> None:
    """Remove the registry entries of entities that the platforms no longer create."""
    data = entry.runtime_data
    # HA logs an error in a platform setup and goes on, so a failed platform adds no unique IDs.
    if not data.set_up_platforms.issuperset(PLATFORMS):
        return
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if registry_entry.unique_id in data.unique_ids:
            continue
        device = device_registry.async_get(registry_entry.device_id or "")
        board = data.boards.get(_device_serial(device)) if device else None
        # Without circuit data, the platforms could not decide the entities of a board.
        if board is None or not board.layout:
            continue
        # The migration renames this entry when its module is in the live data again.
        if _is_module_unique_id(registry_entry.unique_id, board.live.serial):
            continue
        LOGGER.info("Removing %s, which no circuit provides", registry_entry.entity_id)
        entity_registry.async_remove(registry_entry.entity_id)


def _is_module_unique_id(unique_id: str, serial: str) -> bool:
    """Return True for a circuit unique ID from before it followed the circuit position."""
    return any(
        unique_id.startswith(f"basis_{key}_{serial}_")
        and not unique_id.startswith(f"basis_{key}_{serial}_circuit_")
        for key in MODULE_KEYS
    )


def _device_name(serial: str, name: str | None) -> str:
    return name or f"Basis Panel {serial}"


@callback
def _async_sync_device_name(
    hass: HomeAssistant, entry: BasisConfigEntry, board: BoardCoordinators
) -> None:
    """Rename the device when the panel is renamed in the Basis app."""
    if board.live.data is None:
        return
    name = _device_name(board.live.serial, board.live.data.name)
    device_registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if _device_serial(device) == board.live.serial and device.name != name:
            device_registry.async_update_device(device.id, name=name)


def _device_serial(device: dr.DeviceEntry) -> str | None:
    return next((value for domain, value in device.identifiers if domain == DOMAIN), None)


async def async_unload_entry(hass: HomeAssistant, entry: BasisConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
