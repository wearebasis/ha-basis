"""Fake Basis GraphQL API that executes queries against the schema subset."""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestServer
from graphql import GraphQLError, build_schema, graphql

SCHEMA = build_schema((Path(__file__).parent / "schema.graphql").read_text())

SERIAL_A = "SB-0000000001"
SERIAL_B = "SB-0000000002"

TODAY_START = "2026-10-15T00:00:00+13:00"
MONTH_START = "2026-10-01T00:00:00+13:00"
TODAY_BUCKET = "2026-10-14T11:00:00Z"


def subcircuit(
    number: int,
    serial: str,
    label: str,
    state: str = "LIVE",
    power: float = 0.0,
    current: float = 0.0,
    voltage: float = 230.0,
    locked: bool = False,
    name_from_app: str | None = None,
) -> dict[str, Any]:
    """Return a subcircuit as the backend stores it."""
    return {
        "number": number,
        "serial": serial,
        "config": {
            "version": "3.13.0",
            "label": label,
            "standbyLocked": locked,
            "name_from_app": name_from_app,
        },
        "liveState": {
            "state": state,
            "power": power,
            "primaryCurrent": current,
            "phaseVoltage": voltage,
            "updatedTimestamp": "2026-10-14T20:59:58Z",
        },
    }


def default_boards() -> dict[str, dict[str, Any]]:
    """Return a connected panel A and a disconnected panel B."""
    return {
        SERIAL_A: {
            "name": None,
            "serial": SERIAL_A,
            "model": "GEN1",
            "version": "3.2.1",
            "connectivity": {
                "connected": True,
                "updatedTimestamp": "2026-10-14T20:59:58Z",
                "disconnectReason": None,
            },
            "liveState": {
                "power": -1414.5,
                "powerUsage": {"importPower": 985.5, "exportPower": 2400.0},
                "primaryCurrent": 17.0,
                "updatedTimestamp": "2026-10-14T20:59:58Z",
            },
            "subcircuits": [
                subcircuit(1, "SC-A01", "lights", power=120.5, current=0.52, voltage=231.2),
                subcircuit(2, "SC-A02", "power", power=850.0, current=3.7, voltage=231.0),
                subcircuit(3, "SC-A03", "hob", voltage=230.8, locked=True),
                subcircuit(4, "SC-A04", "spare", state="UNKNOWN", voltage=230.9),
                subcircuit(5, "SC-A05", "evCharger", state="STANDBY", voltage=231.1),
                subcircuit(6, "SC-A06", "light", power=15.0, current=0.07, voltage=231.0),
                subcircuit(7, "SC-A07", "solar", power=-2400.0, current=10.4, voltage=232.0),
            ],
        },
        SERIAL_B: {
            "name": None,
            "serial": SERIAL_B,
            "model": None,
            "version": None,
            "connectivity": {
                "connected": False,
                "updatedTimestamp": "2026-10-14T08:00:00Z",
                "disconnectReason": "UNKNOWN",
            },
            "liveState": None,
            "subcircuits": [
                subcircuit(1, "SC-B01", "lights", state="UNAVAILABLE"),
                subcircuit(2, "SC-B02", "hwc", state="UNAVAILABLE"),
            ],
        },
    }


def default_board_energy() -> dict[str, dict[str, dict[str, float | None]]]:
    """Return board energy totals keyed by the requested start time."""
    return {
        SERIAL_A: {
            TODAY_START: {"importKwh": 12.5, "exportKwh": 3.25},
            MONTH_START: {"importKwh": 250.75, "exportKwh": 80.5},
        },
        SERIAL_B: {
            TODAY_START: {"importKwh": None, "exportKwh": None},
            MONTH_START: {"importKwh": 10.0, "exportKwh": 0.0},
        },
    }


def default_subcircuit_energy() -> dict[str, dict[str, list[tuple[str, float | None]]]]:
    """Return daily import buckets for each subcircuit."""
    return {
        SERIAL_A: {
            "SC-A01": [(TODAY_BUCKET, 1.2)],
            "SC-A02": [(TODAY_BUCKET, 5.4)],
            "SC-A03": [(TODAY_BUCKET, 0.0)],
            "SC-A04": [(TODAY_BUCKET, None)],
            "SC-A05": [(TODAY_BUCKET, 7.0)],
            "SC-A06": [(TODAY_BUCKET, 0.3)],
            "SC-A07": [(TODAY_BUCKET, 0.0)],
        },
        SERIAL_B: {
            "SC-B01": [(TODAY_BUCKET, 0.0)],
            "SC-B02": [(TODAY_BUCKET, 0.0)],
        },
    }


class FakeBasisBackend:
    """Serve /query for the integration from in-memory panel data."""

    def __init__(self) -> None:
        """Load the default data."""
        self.sites: dict[str, list[str]] = {"site-1": [SERIAL_A], "site-2": [SERIAL_B]}
        self.boards = default_boards()
        self.board_energy = default_board_energy()
        self.subcircuit_energy = default_subcircuit_energy()
        self.standby_calls: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []
        self.fail_status: int | None = None
        self.fail_body: dict[str, Any] | None = None
        self.fail_headers: dict[str, str] = {}
        self.graphql_error: str | None = None
        self.hang = False
        self.broken_boards: set[str] = set()
        self.broken_energy: set[str] = set()
        self._release = asyncio.Event()
        self._server = TestServer(self._app())

    @property
    def url(self) -> str:
        """Return the base URL, without the /query path."""
        return str(self._server.make_url("")).rstrip("/")

    async def start(self) -> None:
        """Start the HTTP server."""
        # The access log cannot format the frozen time of the tests.
        await self._server.start_server(access_log=None)

    async def close(self) -> None:
        """Stop the HTTP server."""
        self._release.set()
        await self._server.close()

    def board(self, serial: str) -> dict[str, Any]:
        """Return the stored data of one panel, for changes in a test."""
        return self.boards[serial]

    def remove_board(self, serial: str) -> None:
        """Remove a panel from every site."""
        for serials in self.sites.values():
            if serial in serials:
                serials.remove(serial)

    def _app(self) -> web.Application:
        app = web.Application()
        app.router.add_post("/query", self._handle)
        return app

    async def _handle(self, request: web.Request) -> web.Response:
        body = await request.json()
        self.requests.append({"headers": dict(request.headers), "body": body})
        if self.hang:
            await self._release.wait()
        if self.fail_status is not None:
            if self.fail_body is not None:
                return web.json_response(
                    self.fail_body, status=self.fail_status, headers=self.fail_headers
                )
            return web.Response(status=self.fail_status, headers=self.fail_headers)
        if self.graphql_error is not None:
            return web.json_response(
                {"data": None, "errors": [{"message": self.graphql_error}]}
            )
        result = await graphql(
            SCHEMA,
            body["query"],
            root_value=self._root(),
            variable_values=body.get("variables"),
            operation_name=body.get("operationName"),
        )
        payload: dict[str, Any] = {"data": result.data}
        if result.errors:
            payload["errors"] = [error.formatted for error in result.errors]
        return web.json_response(payload)

    def _root(self) -> dict[str, Any]:
        return {
            "sites": self._resolve_sites,
            "switchboard": self._resolve_switchboard,
            "updateSubcircuitStandbyState": self._resolve_standby,
        }

    def _resolve_sites(self, info: Any, input: dict[str, Any]) -> dict[str, Any]:
        sites = [
            {
                "id": site_id,
                "switchboards": [self._board_view(serial) for serial in serials],
            }
            for site_id, serials in self.sites.items()
        ]
        return {"sites": sites}

    def _resolve_switchboard(self, info: Any, serial: str) -> dict[str, Any]:
        if not any(serial in serials for serials in self.sites.values()):
            raise GraphQLError(f"switchboard {serial} not found")
        if serial in self.broken_boards:
            raise GraphQLError(f"switchboard {serial} failed")
        return self._board_view(serial)

    def _resolve_standby(self, info: Any, input: dict[str, Any]) -> dict[str, Any]:
        self.standby_calls.append(dict(input))
        view = self._board_view(input["switchboardSerial"])
        for sub in view["subcircuits"]:
            if sub["serial"] == input["subcircuitSerial"]:
                return sub
        raise GraphQLError(f"subcircuit {input['subcircuitSerial']} not found")

    def _board_view(self, serial: str) -> dict[str, Any]:
        board = copy.deepcopy(self.boards[serial])
        energy = self.board_energy.get(serial, {})

        def total(info: Any, input: dict[str, Any]) -> dict[str, Any]:
            if serial in self.broken_energy:
                raise GraphQLError(f"energy of {serial} failed")
            if input["startTime"] not in energy:
                raise GraphQLError(f"unexpected startTime {input['startTime']}")
            return energy[input["startTime"]]

        board["totalSwitchboardEnergyUsage"] = total
        for sub in board["subcircuits"]:
            config = sub["config"]
            config["displayLabel"] = config["name_from_app"] or config["label"]
            sub["energyUsage"] = self._subcircuit_energy_resolver(serial, sub["serial"])
        return board

    def _subcircuit_energy_resolver(self, serial: str, sub_serial: str) -> Any:
        buckets = self.subcircuit_energy.get(serial, {}).get(sub_serial, [])

        def resolve(info: Any, input: dict[str, Any]) -> dict[str, Any]:
            if input["startTime"] != TODAY_START:
                raise GraphQLError(f"unexpected startTime {input['startTime']}")
            return {
                "data": [
                    {"time": time, "usage": {"importKwh": kwh, "exportKwh": None}}
                    for time, kwh in buckets
                ]
            }

        return resolve
