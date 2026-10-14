"""Tests for the OAuth2 config flow and reauth."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator
from yarl import URL

from custom_components.basis_smart_panel.const import (
    DOMAIN,
    OAUTH2_AUDIENCE,
    OAUTH2_AUTHORIZE,
    OAUTH2_CLIENT_ID,
    OAUTH2_SCOPE,
    OAUTH2_TOKEN,
)

from .conftest import USER_EMAIL, USER_SUB, make_id_token

REDIRECT_URI = "https://example.com/auth/external/callback"


def token_response(sub: str = USER_SUB, email: str = USER_EMAIL) -> dict:
    return {
        "access_token": "new-access-token",
        "refresh_token": "new-refresh-token",
        "id_token": make_id_token(sub, email),
        "scope": OAUTH2_SCOPE,
        "token_type": "Bearer",
        "expires_in": 3600,
    }


@pytest.fixture(autouse=True)
async def setup_components(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "auth", {})
    assert await async_setup_component(hass, DOMAIN, {})


async def run_oauth(
    hass: HomeAssistant,
    flow: dict,
    client_factory: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    token: dict,
) -> dict:
    """Follow the external step through the callback and the token request."""
    assert flow["type"] is FlowResultType.EXTERNAL_STEP
    state = URL(flow["url"]).query["state"]
    client = await client_factory()
    response = await client.get(f"/auth/external/callback?code=test-code&state={state}")
    assert response.status == 200

    aioclient_mock.post(OAUTH2_TOKEN, json=token)
    with patch(
        "custom_components.basis_smart_panel.async_setup_entry", return_value=True
    ):
        return await hass.config_entries.flow.async_configure(flow["flow_id"])


@pytest.mark.usefixtures("current_request_with_host")
async def test_full_flow(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    authorize = URL(flow["url"])
    assert authorize.with_query(None) == URL(OAUTH2_AUTHORIZE)
    assert authorize.query["client_id"] == OAUTH2_CLIENT_ID
    assert authorize.query["redirect_uri"] == REDIRECT_URI
    assert authorize.query["scope"] == OAUTH2_SCOPE
    assert authorize.query["audience"] == OAUTH2_AUDIENCE
    assert authorize.query["code_challenge_method"] == "S256"
    assert authorize.query["code_challenge"]

    result = await run_oauth(
        hass, flow, hass_client_no_auth, aioclient_mock, token_response()
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Basis ({USER_EMAIL})"
    assert result["result"].unique_id == USER_SUB
    assert result["data"]["token"]["access_token"] == "new-access-token"

    _, _, token_request, _ = aioclient_mock.mock_calls[-1]
    assert token_request["grant_type"] == "authorization_code"
    assert token_request["code"] == "test-code"
    assert token_request["client_id"] == OAUTH2_CLIENT_ID
    assert token_request["audience"] == OAUTH2_AUDIENCE
    assert token_request["redirect_uri"] == REDIRECT_URI
    assert token_request["code_verifier"]


@pytest.mark.usefixtures("current_request_with_host")
async def test_same_account_twice_aborts(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    config_entry.add_to_hass(hass)
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    result = await run_oauth(
        hass, flow, hass_client_no_auth, aioclient_mock, token_response()
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def start_reauth(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    entry.add_to_hass(hass)
    form = await entry.start_reauth_flow(hass)
    assert form["type"] is FlowResultType.FORM
    assert form["step_id"] == "reauth_confirm"
    return await hass.config_entries.flow.async_configure(form["flow_id"], {})


@pytest.mark.usefixtures("current_request_with_host")
async def test_reauth_updates_token(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    flow = await start_reauth(hass, config_entry)

    result = await run_oauth(
        hass, flow, hass_client_no_auth, aioclient_mock, token_response()
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data["token"]["access_token"] == "new-access-token"


@pytest.mark.xfail(
    strict=True,
    reason="reauth does not compare the account with the unique_id of the entry",
)
@pytest.mark.usefixtures("current_request_with_host")
async def test_reauth_with_other_account_aborts(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    flow = await start_reauth(hass, config_entry)

    result = await run_oauth(
        hass,
        flow,
        hass_client_no_auth,
        aioclient_mock,
        token_response("auth0|someone-else", "other@example.com"),
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert config_entry.data["token"]["access_token"] != "new-access-token"
