"""Tests for how API and token errors reach Home Assistant."""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from unittest.mock import patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.basis_smart_panel.api import MAX_RETRIES, TOTAL_TIMEOUT
from custom_components.basis_smart_panel.const import DOMAIN, OAUTH2_TOKEN

from .conftest import POLL, advance, circuit_uid, make_token, setup_integration
from .fake_backend import SERIAL_A, SERIAL_B, FakeBasisBackend


def reauth_started(hass: HomeAssistant, entry: MockConfigEntry) -> bool:
    return any(
        flow["context"]["source"] == SOURCE_REAUTH
        and flow["context"].get("entry_id") == entry.entry_id
        for flow in hass.config_entries.flow.async_progress()
    )


def live_requests(backend: FakeBasisBackend) -> int:
    return sum(
        "GetSwitchboardData" in request["body"]["query"] for request in backend.requests
    )


def power_entity(entity_registry: er.EntityRegistry) -> str:
    entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, circuit_uid("power", SERIAL_A, 1)
    )
    assert entity_id
    return entity_id


async def test_rejected_token_at_setup_starts_reauth(
    hass: HomeAssistant, fake_backend: FakeBasisBackend, config_entry: MockConfigEntry
) -> None:
    fake_backend.fail_status = 401
    await setup_integration(hass, config_entry)

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert reauth_started(hass, config_entry)
    assert len(fake_backend.requests) == 1


async def test_rejected_token_while_polling_starts_reauth_and_stops_polling(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    entity_id = power_entity(entity_registry)

    fake_backend.fail_status = 401
    await advance(hass, freezer, POLL)
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
    assert reauth_started(hass, config_entry)

    requests = len(fake_backend.requests)
    for _ in range(3):
        await advance(hass, freezer, POLL)
    assert len(fake_backend.requests) == requests


@pytest.mark.parametrize(("status", "reauth"), [(401, True), (403, False)])
async def test_rejected_request_with_graphql_errors(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    status: int,
    reauth: bool,
) -> None:
    await setup_integration(hass, config_entry)
    entity_id = power_entity(entity_registry)

    fake_backend.fail_status = status
    fake_backend.fail_body = {"data": None, "errors": [{"message": "not allowed"}]}
    await advance(hass, freezer, POLL)

    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
    assert reauth_started(hass, config_entry) is reauth


async def test_rejected_refresh_token_starts_reauth(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    token = make_token()
    token["expires_at"] = time.time() - 60
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="auth0|user-1",
        data={"auth_implementation": DOMAIN, "token": token},
    )
    aioclient_mock.post(OAUTH2_TOKEN, status=400, json={"error": "invalid_grant"})

    await setup_integration(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert reauth_started(hass, entry)
    assert aioclient_mock.call_count == 1
    assert not fake_backend.requests


async def test_graphql_error_is_not_retried(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    entity_id = power_entity(entity_registry)
    requests = live_requests(fake_backend)

    fake_backend.graphql_error = "access denied"
    await advance(hass, freezer, POLL)

    assert live_requests(fake_backend) - requests == len([SERIAL_A, SERIAL_B])
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
    assert not reauth_started(hass, config_entry)


async def test_server_error_is_retried_and_logged_once(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await setup_integration(hass, config_entry)
    requests = live_requests(fake_backend)

    fake_backend.fail_status = 503
    await advance(hass, freezer, POLL)
    await advance(hass, freezer, POLL)

    assert live_requests(fake_backend) - requests == 2 * MAX_RETRIES * len([SERIAL_A, SERIAL_B])
    assert "Unexpected error" not in caplog.text
    assert caplog.text.count(f"Error fetching basis_smart_panel_{SERIAL_A} data") == 1


async def test_rate_limit_waits_for_retry_after(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    entity_id = power_entity(entity_registry)
    requests = live_requests(fake_backend)

    fake_backend.fail_status = 429
    fake_backend.fail_headers = {"Retry-After": "60"}
    await advance(hass, freezer, POLL)
    assert live_requests(fake_backend) - requests == len([SERIAL_A, SERIAL_B])

    requests = live_requests(fake_backend)
    await advance(hass, freezer, timedelta(seconds=50))
    assert live_requests(fake_backend) == requests

    fake_backend.fail_status = None
    await advance(hass, freezer, timedelta(seconds=15))
    assert hass.states.get(entity_id).state == "120.5"


async def test_failed_switch_command_raises_home_assistant_error(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    entity_id = entity_registry.async_get_entity_id(
        SWITCH_DOMAIN, DOMAIN, circuit_uid("switch", SERIAL_A, 1)
    )

    fake_backend.graphql_error = "standby command blocked"
    with pytest.raises(HomeAssistantError, match="standby command blocked"):
        await hass.services.async_call(
            SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
        )


async def test_refresh_stops_at_total_timeout(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    entity_id = power_entity(entity_registry)

    fake_backend.hang = True
    freezer.tick(POLL)
    async_fire_time_changed(hass)
    for _ in range(10):
        await asyncio.sleep(0)
    assert hass.states.get(entity_id).state == "120.5"

    freezer.tick(TOTAL_TIMEOUT + timedelta(seconds=1))
    async_fire_time_changed(hass)
    # async_block_till_done skips tasks that are being cancelled, as the timed-out ones are.
    for _ in range(10):
        await asyncio.sleep(0)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE


async def test_token_refresh_stops_at_total_timeout(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    entity_id = power_entity(entity_registry)

    token_endpoint_answers = asyncio.Event()
    with patch.object(
        config_entry_oauth2_flow.OAuth2Session,
        "async_ensure_token_valid",
        side_effect=token_endpoint_answers.wait,
    ):
        freezer.tick(POLL)
        async_fire_time_changed(hass)
        for _ in range(10):
            await asyncio.sleep(0)
        freezer.tick(TOTAL_TIMEOUT + timedelta(seconds=1))
        async_fire_time_changed(hass)
        for _ in range(10):
            await asyncio.sleep(0)
        state = hass.states.get(entity_id).state
        token_endpoint_answers.set()
        await hass.async_block_till_done(wait_background_tasks=True)

    assert state == STATE_UNAVAILABLE
