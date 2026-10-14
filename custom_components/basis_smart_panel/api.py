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
from collections.abc import Mapping
from datetime import timedelta
from http import HTTPStatus
from typing import cast

from aiohttp import ClientError, ClientResponseError
from homeassistant.helpers import config_entry_oauth2_flow
from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport
from gql.transport.exceptions import TransportError, TransportQueryError

from .const import (
    LOGGER,
    API_BASE_URL
)
from .models import (
    Connectivity,
    EnergyTotals,
    Site,
    Subcircuit,
    SubcircuitLiveState,
    Switchboard,
    SwitchboardLiveState,
)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2
ATTEMPT_TIMEOUT = timedelta(seconds=10)
TOTAL_TIMEOUT = timedelta(seconds=15)


class BasisApiError(Exception):
    """A request to the Basis API failed."""


class BasisConnectionError(BasisApiError):
    """The request did not complete, or the API had a temporary fault."""


class BasisAuthError(BasisApiError):
    """The API or the token endpoint rejected the credentials."""


class BasisRateLimitError(BasisApiError):
    """The API limited the rate of requests."""

    def __init__(self, message: str, retry_after: float | None) -> None:
        """Initialize the error with the seconds to wait, if the API sent them."""
        super().__init__(message)
        self.retry_after = retry_after


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
        try:
            await self._oauth_session.async_ensure_token_valid()
        except ClientResponseError as err:
            if _is_rejection(err.status):
                raise BasisAuthError(f"Token refresh rejected ({err.status})") from err
            raise BasisConnectionError(f"Token refresh failed ({err.status})") from err
        except (ClientError, TimeoutError) as err:
            raise BasisConnectionError(f"Token refresh failed: {err!r}") from err

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

    def _create_client(self, auth_token: str) -> Client:
        """Create a new GraphQL client with the access token."""
        transport = AIOHTTPTransport(
            url=f'{API_BASE_URL}/query',
            headers={
                'User-Agent': f'HomeAssistantBasisSmartPanelIntegration/{self._integration_version}',
                'Authorization': f'Bearer {auth_token}',
            },
            ssl=True,
            # Without this, gql reads a GraphQL body of an error response and drops the status.
            client_session_args={"raise_for_status": True},
        )
        # gql's own timeout cancels with anyio, which defeats the asyncio.timeout in _execute.
        return Client(
            transport=transport, fetch_schema_from_transport=False, execute_timeout=None
        )

    async def _execute(self, document, variables=None, *, retry: bool = True) -> dict:
        """Execute a GraphQL document and raise BasisApiError on failure.

        Only a BasisConnectionError is retried, and only when retry is True.
        The token refresh and all attempts together must finish within TOTAL_TIMEOUT.
        """
        try:
            async with asyncio.timeout(TOTAL_TIMEOUT.total_seconds()):
                auth_token = await self._auth.async_get_access_token()
                return await self._execute_attempts(
                    document, variables, auth_token, MAX_RETRIES if retry else 1
                )
        except TimeoutError as err:
            raise BasisConnectionError(f"No answer within {TOTAL_TIMEOUT}") from err

    async def _execute_attempts(
        self, document, variables, auth_token: str, attempts: int
    ) -> dict:
        for attempt in range(1, attempts + 1):
            try:
                client = self._create_client(auth_token)
                async with asyncio.timeout(ATTEMPT_TIMEOUT.total_seconds()):
                    return await client.execute_async(document, variable_values=variables)
            except (TransportError, ClientError, TimeoutError, OSError) as err:
                error = _api_error(err)
                if not isinstance(error, BasisConnectionError) or attempt == attempts:
                    raise error from err
                LOGGER.debug(
                    "Query attempt %s/%s failed, retrying in %ss: %r",
                    attempt, attempts, RETRY_DELAY_SECONDS, err,
                )
                await asyncio.sleep(RETRY_DELAY_SECONDS)

    async def get_sites(self) -> list[Site]:
        """Return all sites available to the user."""
        query = gql("""
            query {
                sites(input: { query: "" }) {
                    sites {
                        id
                        address {
                            address
                        }
                        timeZone
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

        result = await self._execute(query)
        sites = [
            Site(
                id=site["id"],
                address=site["address"]["address"] if site["address"] else None,
                time_zone=site["timeZone"],
                serials=tuple(board["serial"] for board in site["switchboards"]),
            )
            for site in result["sites"]["sites"]
        ]
        LOGGER.debug(f"Discovered {len(sites)} sites")
        return sites

    async def get_switchboard_data(self, serial: str) -> Switchboard:
        """Get switchboard data from the API."""
        query = gql("""
            query GetSwitchboardData($serial: String!) {
                switchboard(serial: $serial) {
                    name
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
                            displayLabel
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

        result = await self._execute(query, variables)
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

        result = await self._execute(query, variables)
        usage = result["switchboard"]["totalSwitchboardEnergyUsage"]
        return EnergyTotals(import_kwh=usage["importKwh"], export_kwh=usage["exportKwh"])

    async def get_site_energy_usage(self, site_id: str, start_time: str) -> EnergyTotals:
        """Get the energy that all switchboards of the site used since start_time (ISO 8601)."""
        query = gql("""
            query GetSiteEnergyUsage($id: ID!, $startTime: Time!) {
                site(id: $id) {
                    totalEnergyUsage(input: { startTime: $startTime }) {
                        importKwh
                        exportKwh
                    }
                }
            }
        """)

        variables = {
            "id": site_id,
            "startTime": start_time,
        }

        result = await self._execute(query, variables)
        if (usage := result["site"]["totalEnergyUsage"]) is None:
            return EnergyTotals(import_kwh=None, export_kwh=None)
        return EnergyTotals(import_kwh=usage["importKwh"], export_kwh=usage["exportKwh"])

    async def get_subcircuit_energy_usage(
        self, serial: str, start_time: str
    ) -> dict[int, float | None]:
        """Get the import energy of each subcircuit since start_time.

        Keys are subcircuit numbers. start_time is ISO 8601 (midnight today).
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

        result = await self._execute(query, variables)
        return {
            subcircuit["number"]: _import_kwh_total(subcircuit["energyUsage"]["data"])
            for subcircuit in result["switchboard"]["subcircuits"]
        }

    async def set_subcircuit_standby(
        self, switchboard_serial: str, subcircuit_serial: str, standby_state: bool
    ):
        """Set subcircuit standby state."""
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

        return await self._execute(mutation, variables, retry=False)


def _parse_switchboard(data: dict) -> Switchboard:
    connectivity = data["connectivity"]
    live = data["liveState"]
    return Switchboard(
        name=data["name"],
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
        display_label=config["displayLabel"],
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


def _import_kwh_total(data_points: list[dict]) -> float | None:
    """Return the sum of the non-null importKwh values, or None if all are null."""
    # The DAY buckets need not start at start_time, so the range can span two buckets.
    values = [point["usage"]["importKwh"] for point in data_points]
    values = [value for value in values if value is not None]
    return sum(values) if values else None


def _is_rejection(status: int | None) -> bool:
    """Return True for a 4xx status other than 429, which retries cannot fix."""
    return (
        status is not None
        and 400 <= status < 500
        and status != HTTPStatus.TOO_MANY_REQUESTS
    )


def _retry_after(headers: Mapping[str, str] | None) -> float | None:
    """Return the Retry-After seconds, or None without the header or for the HTTP date form."""
    value = (headers or {}).get("Retry-After", "")
    return float(value) if value.isdigit() else None


def _api_error(err: Exception) -> BasisApiError:
    """Return the BasisApiError for an error of the GraphQL client."""
    # gql 4 wraps the aiohttp error, gql 3 does not.
    response_error = next(
        (e for e in (err, err.__cause__) if isinstance(e, ClientResponseError)), None
    )
    if response_error is not None:
        # The API answers a rejected access token with HTTP 401.
        if response_error.status == HTTPStatus.UNAUTHORIZED:
            return BasisAuthError("The API rejected the access token")
        if response_error.status == HTTPStatus.TOO_MANY_REQUESTS:
            return BasisRateLimitError(
                str(response_error), _retry_after(response_error.headers)
            )
        if _is_rejection(response_error.status):
            return BasisApiError(str(response_error))
        return BasisConnectionError(str(response_error))
    if isinstance(err, TransportQueryError):
        return BasisApiError(str(err))
    return BasisConnectionError(repr(err))
