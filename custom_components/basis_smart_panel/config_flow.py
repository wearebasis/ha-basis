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

import base64
import json
import logging

from typing import Any
from collections.abc import Mapping

from homeassistant.config_entries import ConfigEntry
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import LocalOAuth2ImplementationWithPkce

from .const import (
    DOMAIN,
    LOGGER,
    OAUTH2_CLIENT_ID,
    OAUTH2_AUTHORIZE,
    OAUTH2_TOKEN,
    OAUTH2_SCOPE,
    OAUTH2_AUDIENCE,
)

CONFIG_VERSION = 1


class BasisOAuth2Implementation(LocalOAuth2ImplementationWithPkce):
    """OAuth2 implementation that includes audience in token requests."""

    @property
    def extra_authorize_data(self) -> dict:
        """Extra data that needs to be appended to the authorize url."""
        data = {
            "scope": OAUTH2_SCOPE,
            "audience": OAUTH2_AUDIENCE,
        }
        data.update(super().extra_authorize_data)
        return data

    @property
    def extra_token_resolve_data(self) -> dict:
        """Extra data for the token resolve request."""
        data = {"audience": OAUTH2_AUDIENCE}
        data.update(super().extra_token_resolve_data)
        return data

    async def async_resolve_external_data(self, external_data: Any) -> dict:
        """Resolve the authorization code to tokens."""
        LOGGER.debug("async_resolve_external_data called with keys: %s", list(external_data.keys()) if isinstance(external_data, dict) else type(external_data))
        LOGGER.debug("extra_authorize_data: %s", self.extra_authorize_data)
        LOGGER.debug("extra_token_resolve_data: %s", self.extra_token_resolve_data)
        return await super().async_resolve_external_data(external_data)

    async def _token_request(self, data: dict) -> dict:
        """Make a token request with logging."""
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        # Log what we're about to send
        log_data = {k: (v[:20] + "..." if isinstance(v, str) and len(v) > 20 else v) for k, v in data.items()}
        LOGGER.debug("Token request to %s with data: %s", self.token_url, log_data)

        session = async_get_clientsession(self.hass)

        data["client_id"] = self.client_id
        if self.client_secret:
            data["client_secret"] = self.client_secret

        LOGGER.debug("Final token request params: %s", list(data.keys()))

        resp = await session.post(self.token_url, data=data)
        resp_body = await resp.text()

        LOGGER.debug("Token response status: %s", resp.status)
        LOGGER.debug("Token response body: %s", resp_body[:500] if len(resp_body) > 500 else resp_body)

        if resp.status >= 400:
            LOGGER.error("Token request failed: status=%s body=%s", resp.status, resp_body)
            resp.raise_for_status()

        return await resp.json(content_type=None)


def _decode_jwt_payload(token: str) -> dict:
    """Decode the payload segment of a JWT without verification."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Token is not a valid JWT")
    payload = parts[1]
    # Add padding if needed
    padding = 4 - len(payload) % 4
    if padding != 4:
        payload += "=" * padding
    decoded = base64.urlsafe_b64decode(payload)
    return json.loads(decoded)


class BasisSmartPanelConfigFlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler,
    domain=DOMAIN
):
    DOMAIN = DOMAIN

    def __init__(self) -> None:
        """Set up instance."""
        super().__init__()
        self._reauth_entry: ConfigEntry | None = None

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return LOGGER

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        config_entry_oauth2_flow.async_register_implementation(
            self.hass,
            DOMAIN,
            BasisOAuth2Implementation(
                self.hass,
                DOMAIN,
                OAUTH2_CLIENT_ID,
                authorize_url=OAUTH2_AUTHORIZE,
                token_url=OAUTH2_TOKEN,
                client_secret="",
                code_verifier_length=128,
            ),
        )
        return await super().async_step_user(user_input)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        """Perform reauth upon an API authentication error."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Dialog that informs the user that reauth is required."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    async def _get_user_info(self, data: dict) -> tuple[str, str]:
        """Extract user ID and email from OAuth token data."""
        token_data = data.get("token", data)

        # Try decoding the id_token JWT
        id_token = token_data.get("id_token")
        if id_token:
            try:
                claims = _decode_jwt_payload(id_token)
                sub = claims.get("sub")
                email = claims.get("email", "unknown")
                if sub:
                    return sub, email
            except (ValueError, json.JSONDecodeError, KeyError) as err:
                LOGGER.debug("Failed to decode id_token: %s", err)

        raise ValueError("Could not determine user identity from OAuth tokens")

    async def async_oauth_create_entry(self, data: dict) -> FlowResult:
        """Create an entry for the authenticated user."""
        user_id, email = await self._get_user_info(data)
        await self.async_set_unique_id(user_id)

        # Reauth: update existing entry
        if self._reauth_entry:
            self.hass.config_entries.async_update_entry(
                self._reauth_entry, data=data
            )
            await self.hass.config_entries.async_reload(
                self._reauth_entry.entry_id
            )
            return self.async_abort(reason="reauth_successful")

        # New entry: prevent duplicate accounts
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=f"Basis ({email})", data=data)
