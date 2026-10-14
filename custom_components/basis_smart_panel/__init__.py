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
from datetime import tzinfo
from functools import partial

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    config_entry_oauth2_flow,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.util import dt as dt_util
from homeassistant.util.hass_dict import HassKey
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
    SiteEnergyCoordinator,
    SubcircuitEnergyCoordinator,
    SwitchboardDataCoordinator,
    site_identifier,
)
from .api import BasisAPI, AsyncConfigEntryAuth
from .entity import circuit_unique_id
from .models import Site

BOARD_REMOVAL_POLLS = 3
MODULE_KEYS = ("power", "current", "voltage", "switch", "energy_import")

# Site ID to the ID of the config entry that provides its devices.
SITE_OWNERS: HassKey[dict[str, str]] = HassKey(DOMAIN)


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

    # Two accounts can see the same site, and HA allows one entity for each unique ID.
    owners = hass.data.setdefault(SITE_OWNERS, {})
    for site in discovery.sites:
        if site.id not in owners and _may_claim(hass, entry, site):
            owners[site.id] = entry.entry_id
    entry.async_on_unload(partial(_async_release_sites, hass, entry))

    sites = _owned_sites(hass, entry)
    time_zones = {site.id: await _async_time_zone(site) for site in sites}
    for site in sites:
        for serial in site.serials:
            if serial not in entry.runtime_data.boards:
                entry.runtime_data.boards[serial] = await _async_setup_board(
                    hass, entry, api, serial, site, time_zones[site.id]
                )
    for site in _grouped(sites):
        site_energy = SiteEnergyCoordinator(hass, entry, api, site, time_zones[site.id])
        await site_energy.async_refresh()
        entry.runtime_data.site_energy[site.id] = site_energy

    _async_register_devices(hass, entry)
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


async def _async_time_zone(site: Site) -> tzinfo | None:
    """Return the time zone of the site, or None for the time zone of HA."""
    if site.time_zone is None:
        return None
    if (time_zone := await dt_util.async_get_time_zone(site.time_zone)) is None:
        LOGGER.warning(
            "Site %s has the unknown time zone %s, so its energy periods use the time zone of HA",
            site.id,
            site.time_zone,
        )
    return time_zone


async def _async_setup_board(
    hass: HomeAssistant,
    entry: BasisConfigEntry,
    api: BasisAPI,
    serial: str,
    site: Site,
    time_zone: tzinfo | None,
) -> BoardCoordinators:
    """Create the coordinators of one switchboard and fetch their first data.

    A failed fetch does not stop the setup. The entities of that switchboard
    stay unavailable until the coordinator gets data.
    """
    board = BoardCoordinators(
        live=SwitchboardDataCoordinator(hass, entry, api, serial),
        energy=EnergyStatsCoordinator(hass, entry, api, serial, time_zone),
        subcircuit_energy=SubcircuitEnergyCoordinator(hass, entry, api, serial, time_zone),
        site_id=site.id,
    )
    for coordinator in (board.live, board.energy, board.subcircuit_energy):
        await coordinator.async_refresh()
    if board.live.data is not None:
        board.layout = board.live.data.circuit_layout
    LOGGER.debug("Created coordinators for switchboard %s", serial)
    return board


@callback
def _async_register_devices(hass: HomeAssistant, entry: BasisConfigEntry) -> None:
    """Register each switchboard, and each site with more than one, as a device."""
    device_registry = dr.async_get(hass)
    data = entry.runtime_data
    grouped = {site.id for site in _grouped(_owned_sites(hass, entry))}

    for site in _owned_sites(hass, entry):
        site_device_id = None
        if site.id in grouped:
            site_device_id = device_registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, site_identifier(site.id))},
                manufacturer=BRAND,
                model="Site",
                name=site.address or "Basis Site",
            ).id
        for serial in site.serials:
            if (board := data.boards.get(serial)) is not None:
                _async_register_switchboard_device(
                    device_registry, entry, board, site_device_id
                )


@callback
def _async_register_switchboard_device(
    device_registry: dr.DeviceRegistry,
    entry: BasisConfigEntry,
    board: BoardCoordinators,
    site_device_id: str | None,
) -> None:
    serial = board.live.serial
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
        via_device_id=site_device_id,
        **details,
    )
    LOGGER.debug(f"Registered device for switchboard {serial}")


@callback
def _async_check_boards(hass: HomeAssistant, entry: BasisConfigEntry) -> None:
    """Reload the entry when a switchboard appears, and remove devices that stay missing."""
    data = entry.runtime_data
    if not data.discovery.last_update_success:
        return

    if new := _owned_serials(hass, entry, claimable=True) - set(data.boards):
        LOGGER.info("Found new switchboards %s, reloading", new)
        hass.config_entries.async_schedule_reload(entry.entry_id)
        return

    if moved := {
        serial
        for site in _owned_sites(hass, entry)
        for serial in site.serials
        if (board := data.boards.get(serial)) is not None and board.site_id != site.id
    }:
        LOGGER.info("Switchboards %s moved to a different site, reloading", moved)
        hass.config_entries.async_schedule_reload(entry.entry_id)
        return

    # An empty list is more likely an API fault than the loss of every board.
    if not data.discovery.switchboard_serials:
        return

    sites = _owned_sites(hass, entry)
    current = {site_identifier(site.id) for site in _grouped(sites)} | {
        serial for site in sites for serial in site.serials
    }

    device_registry = dr.async_get(hass)
    reload = False
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        identifier = _device_identifier(device)
        if identifier is None:
            continue
        if identifier in current:
            data.missing_polls.pop(identifier, None)
            continue
        data.missing_polls[identifier] = data.missing_polls.get(identifier, 0) + 1
        if data.missing_polls[identifier] < BOARD_REMOVAL_POLLS:
            continue
        LOGGER.info("Device %s is no longer in this account, removing it", identifier)
        device_registry.async_remove_device(device.id)
        reload |= identifier in data.boards

    if reload:
        hass.config_entries.async_schedule_reload(entry.entry_id)


def _owned_sites(
    hass: HomeAssistant, entry: BasisConfigEntry, claimable: bool = False
) -> list[Site]:
    """Return the sites that the entry owns.

    With claimable, also return the sites that no entry owns and that this entry can claim.
    """
    owners = hass.data[SITE_OWNERS]
    return [
        site
        for site in entry.runtime_data.discovery.sites
        if owners.get(site.id) == entry.entry_id
        or (claimable and site.id not in owners and _may_claim(hass, entry, site))
    ]


def _may_claim(hass: HomeAssistant, entry: BasisConfigEntry, site: Site) -> bool:
    """Return True if the entry can own the site and keep the devices that HA has for it.

    Each entry has its own devices, so a change of owner gives the site new devices.
    Of the entries that have devices for the site and can set up, the first entry ID owns it.
    """
    identifiers = {(DOMAIN, serial) for serial in site.serials}
    identifiers.add((DOMAIN, site_identifier(site.id)))
    holders = {
        device.config_entry_id
        for device in dr.async_get(hass).async_get_devices(identifiers=identifiers)
    }
    candidates = [
        holder.entry_id
        for holder_id in holders
        if (holder := hass.config_entries.async_get_entry(holder_id)) is not None
        and _can_set_up(hass, holder)
    ]
    return not candidates or min(candidates) == entry.entry_id


def _can_set_up(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if entry.disabled_by is not None:
        return False
    if entry.state is ConfigEntryState.NOT_LOADED:
        # At startup HA sets up the entries in any order, so a waiting entry keeps its sites.
        return not hass.is_running
    return entry.state in (
        ConfigEntryState.LOADED,
        ConfigEntryState.SETUP_IN_PROGRESS,
        ConfigEntryState.SETUP_RETRY,
    )


def _grouped(sites: list[Site]) -> list[Site]:
    """Return the sites with more than one switchboard.

    Only these sites get a device and energy sensors, because one switchboard needs no group.
    """
    return [site for site in sites if len(site.serials) > 1]


def _owned_serials(
    hass: HomeAssistant, entry: BasisConfigEntry, claimable: bool = False
) -> set[str]:
    return {serial for site in _owned_sites(hass, entry, claimable) for serial in site.serials}


@callback
def _async_release_sites(hass: HomeAssistant, entry: BasisConfigEntry) -> None:
    """Let the entries of other accounts take the sites of this entry."""
    owners = hass.data[SITE_OWNERS]
    for site_id in [site_id for site_id, owner in owners.items() if owner == entry.entry_id]:
        del owners[site_id]


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
    sites = {site_identifier(site.id) for site in _grouped(_owned_sites(hass, entry))}
    for registry_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if registry_entry.unique_id in data.unique_ids:
            continue
        device = device_registry.async_get(registry_entry.device_id or "")
        identifier = _device_identifier(device) if device else None
        if identifier not in sites:
            board = data.boards.get(identifier)
            # Without circuit data, the platforms could not decide the entities of a board.
            if board is None or not board.layout:
                continue
            # The migration renames this entry when its module is in the live data again.
            if _is_module_unique_id(registry_entry.unique_id, board.live.serial):
                continue
        LOGGER.info("Removing %s, which no device provides", registry_entry.entity_id)
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
        if _device_identifier(device) == board.live.serial and device.name != name:
            device_registry.async_update_device(device.id, name=name)


def _device_identifier(device: dr.DeviceEntry) -> str | None:
    return next((value for domain, value in device.identifiers if domain == DOMAIN), None)


async def async_unload_entry(hass: HomeAssistant, entry: BasisConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
