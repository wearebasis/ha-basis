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

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_entry_oauth2_flow, device_registry as dr
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

BOARD_REMOVAL_POLLS = 3


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
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    @callback
    def _async_on_discovery_update() -> None:
        _async_check_boards(hass, entry)

    entry.async_on_unload(discovery.async_add_listener(_async_on_discovery_update))

    return True


async def _async_setup_board(
    hass: HomeAssistant, entry: BasisConfigEntry, api: BasisAPI, serial: str
) -> BoardCoordinators:
    """Create the coordinators of one switchboard and fetch their first data."""
    board = BoardCoordinators(
        live=SwitchboardDataCoordinator(hass, entry, api, serial),
        energy=EnergyStatsCoordinator(hass, entry, api, serial),
        subcircuit_energy=SubcircuitEnergyCoordinator(hass, entry, api, serial),
    )
    for coordinator in (board.live, board.energy, board.subcircuit_energy):
        await coordinator.async_config_entry_first_refresh()
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

        if board and board.live.data:
            switchboard = board.live.data
            model = switchboard.model
            subcircuits_version = (
                switchboard.subcircuits[0].config_version
                if switchboard.subcircuits
                else "Unknown"
            )

            if (model == "unknown"):
                model = DEFAULT_MODEL

            device_registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, serial)},
                manufacturer=BRAND,
                name=f"Basis Panel {serial}",
                model=model,
                sw_version=switchboard.version,
                hw_version=subcircuits_version,
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


def _device_serial(device: dr.DeviceEntry) -> str | None:
    return next((value for domain, value in device.identifiers if domain == DOMAIN), None)


async def async_unload_entry(hass: HomeAssistant, entry: BasisConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
