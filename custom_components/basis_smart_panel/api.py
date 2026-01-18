from __future__ import annotations

from typing import cast

from homeassistant.helpers import config_entry_oauth2_flow
from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport

from .const import (
    LOGGER,
    API_BASE_URL
)

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

    async def get_available_switchboards(self) -> list[dict]:
        """Discover all switchboards available to the user.

        Returns:
            List of switchboard info dicts with serial and connected status.
        """
        client = await self._create_client()

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

        result = await client.execute_async(query)

        # Flatten switchboards from all sites
        switchboards = []
        for site in result.get("sites", {}).get("sites", []):
            site_id = site.get("id")
            for board in site.get("switchboards", []):
                switchboards.append({
                    "serial": board["serial"],
                    "site_id": site_id,
                    "connected": board.get("connectivity", {}).get("connected", False),
                })

        LOGGER.debug(f"Discovered {len(switchboards)} switchboards")
        return switchboards

    async def get_switchboard_data(self, serial: str):
        """Get switchboard data from the API."""
        client = await self._create_client()

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

        return await client.execute_async(query, variables)

    async def get_switchboard_energy_usage(self, serial: str, start_time: str):
        """Get energy usage for the switchboard.

        Args:
            serial: Switchboard serial number
            start_time: ISO 8601 formatted start time

        Returns:
            Energy usage data with import/export kWh
        """
        client = await self._create_client()

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

        return await client.execute_async(query, variables)

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

        return await client.execute_async(mutation, variables)
