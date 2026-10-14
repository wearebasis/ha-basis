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

import asyncio
from typing import cast

from aiohttp import ClientError
from homeassistant.helpers import config_entry_oauth2_flow
from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport
from gql.transport.exceptions import TransportError

from .const import (
    LOGGER,
    API_BASE_URL
)
from .models import (
    Connectivity,
    EnergyTotals,
    Subcircuit,
    SubcircuitLiveState,
    Switchboard,
    SwitchboardLiveState,
)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2

class AsyncConfigEntryAuth():
    """Provide Basis Smart Panel authentication tied to an OAuth2 based config entry."""

    def __init__(
        self,
        oauth_session: config_entry_oauth2_flow.OAuth2Session,
    ) -> None:
        """Initialize Basis Smart Panel auth."""
        self._oauth_session = oauth_session

    async def async_get_access_token(self) -> str:
        """Return a valid access token."""
        if not self._oauth_session.valid_token:
            await self._oauth_session.async_ensure_token_valid()

        LOGGER.debug(f"token scope {self._oauth_session.token['scope']}")

        return cast(str, self._oauth_session.token["access_token"])


class BasisAPI:
    """Basis Smart Panel API client."""

    def __init__(self, auth: AsyncConfigEntryAuth, integration_version: str = "unknown") -> None:
        """Initialize the API client.

        Args:
            auth: AsyncConfigEntryAuth instance for OAuth2
            integration_version: Home Assistant integration version for User-Agent header
        """
        self._auth = auth
        self._integration_version = integration_version

    async def _get_auth_token(self) -> str:
        """Get the current authentication token."""
        return await self._auth.async_get_access_token()

    async def _create_client(self) -> Client:
        """Create a new GraphQL client with current auth token."""
        auth_token = await self._get_auth_token()
        transport = AIOHTTPTransport(
            url=f'{API_BASE_URL}/query',
            headers={
                'User-Agent': f'HomeAssistantBasisSmartPanelIntegration/{self._integration_version}',
                'Authorization': f'Bearer {auth_token}',
            },
            ssl=True,
        )
        return Client(transport=transport, fetch_schema_from_transport=False)

    async def _execute_with_retry(self, document, variables=None) -> dict:
        """Execute a GraphQL query with retry on transient failures."""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                client = await self._create_client()
                return await client.execute_async(document, variable_values=variables)
            except (asyncio.TimeoutError, ClientError, TransportError, OSError) as err:
                if attempt == MAX_RETRIES:
                    LOGGER.error("Query failed after %s attempts: %s", MAX_RETRIES, err)
                    raise
                LOGGER.warning(
                    "Query attempt %s/%s failed (%s: %s), retrying in %ss",
                    attempt, MAX_RETRIES, type(err).__name__, err, RETRY_DELAY_SECONDS,
                )
                await asyncio.sleep(RETRY_DELAY_SECONDS)

    async def get_available_switchboards(self) -> list[str]:
        """Return the serials of all switchboards available to the user."""
        query = gql("""
            query {
                sites(input: { query: "" }) {
                    sites {
                        id
                        switchboards {
                            serial
                            connectivity {
                                connected
                            }
                        }
                    }
                }
            }
        """)

        result = await self._execute_with_retry(query)
        serials = [
            board["serial"]
            for site in result["sites"]["sites"]
            for board in site["switchboards"]
        ]
        LOGGER.debug(f"Discovered {len(serials)} switchboards")
        return serials

    async def get_switchboard_data(self, serial: str) -> Switchboard:
        """Get switchboard data from the API."""
        query = gql("""
            query GetSwitchboardData($serial: String!) {
                switchboard(serial: $serial) {
                    serial
                    model
                    version
                    connectivity {
                        connected
                        updatedTimestamp
                        disconnectReason
                    }
                    liveState {
                        power
                        powerUsage {
                            importPower
                            exportPower
                        }
                        primaryCurrent
                        updatedTimestamp
                    }
                    subcircuits {
                        serial
                        number
                        config {
                            label
                            standbyLocked
                            version
                        }
                        liveState {
                            state
                            power
                            primaryCurrent
                            phaseVoltage
                            updatedTimestamp
                        }
                    }
                }
            }
        """)

        variables = {
            "serial": serial
        }

        result = await self._execute_with_retry(query, variables)
        return _parse_switchboard(result["switchboard"])

    async def get_switchboard_energy_usage(
        self, serial: str, start_time: str
    ) -> EnergyTotals:
        """Get the energy that the switchboard used since start_time (ISO 8601)."""
        query = gql("""
            query GetSwitchboardEnergyUsage($serial: String!, $startTime: Time!) {
                switchboard(serial: $serial) {
                    totalSwitchboardEnergyUsage(input: { startTime: $startTime }) {
                        importKwh
                        exportKwh
                    }
                }
            }
        """)

        variables = {
            "serial": serial,
            "startTime": start_time,
        }

        result = await self._execute_with_retry(query, variables)
        usage = result["switchboard"]["totalSwitchboardEnergyUsage"]
        return EnergyTotals(import_kwh=usage["importKwh"], export_kwh=usage["exportKwh"])

    async def get_subcircuit_energy_usage(
        self, serial: str, start_time: str
    ) -> dict[str, float | None]:
        """Get the import energy of each subcircuit in the last daily bucket.

        Keys are subcircuit serials. start_time is ISO 8601 (midnight today).
        """
        query = gql("""
            query GetSubcircuitEnergyUsage($serial: String!, $startTime: Time!) {
                switchboard(serial: $serial) {
                    subcircuits {
                        serial
                        number
                        config {
                            label
                        }
                        energyUsage(input: {
                            startTime: $startTime
                            resolution: {
                                value: 1
                                unit: DAY
                            }
                        }) {
                            data {
                                time
                                usage {
                                    importKwh
                                }
                            }
                        }
                    }
                }
            }
        """)

        variables = {
            "serial": serial,
            "startTime": start_time,
        }

        result = await self._execute_with_retry(query, variables)
        return {
            subcircuit["serial"]: _last_import_kwh(subcircuit["energyUsage"]["data"])
            for subcircuit in result["switchboard"]["subcircuits"]
        }

    async def set_subcircuit_standby(
        self, switchboard_serial: str, subcircuit_serial: str, standby_state: bool
    ):
        """Set subcircuit standby state."""
        client = await self._create_client()

        mutation = gql("""
            mutation UpdateSubcircuitStandby($input: UpdateSubcircuitStandbyStateInput!) {
                updateSubcircuitStandbyState(input: $input) {
                    serial
                    liveState {
                        state
                    }
                }
            }
        """)

        variables = {
            "input": {
                "switchboardSerial": switchboard_serial,
                "subcircuitSerial": subcircuit_serial,
                "activateStandby": standby_state
            }
        }

        return await client.execute_async(mutation, variable_values=variables)


def _parse_switchboard(data: dict) -> Switchboard:
    connectivity = data["connectivity"]
    live = data["liveState"]
    return Switchboard(
        serial=data["serial"],
        model=data["model"],
        version=data["version"],
        connectivity=Connectivity(
            connected=connectivity["connected"],
            last_seen=connectivity["updatedTimestamp"],
            disconnect_reason=connectivity["disconnectReason"],
        ),
        live=SwitchboardLiveState(
            power=live["power"],
            import_power=live["powerUsage"]["importPower"],
            export_power=live["powerUsage"]["exportPower"],
            primary_current=live["primaryCurrent"],
        )
        if live
        else None,
        subcircuits=tuple(_parse_subcircuit(sub) for sub in data["subcircuits"]),
    )


def _parse_subcircuit(data: dict) -> Subcircuit:
    config = data["config"]
    live = data["liveState"]
    return Subcircuit(
        serial=data["serial"],
        number=data["number"],
        label=config["label"],
        config_version=config["version"],
        standby_locked=config["standbyLocked"],
        live=SubcircuitLiveState(
            state=live["state"],
            power=live["power"],
            primary_current=live["primaryCurrent"],
            phase_voltage=live["phaseVoltage"],
        )
        if live
        else None,
    )


def _last_import_kwh(data_points: list[dict]) -> float | None:
    """Return the last non-null importKwh of the data points."""
    result = None
    for point in data_points:
        value = point["usage"]["importKwh"]
        if value is not None:
            result = value
    return result
