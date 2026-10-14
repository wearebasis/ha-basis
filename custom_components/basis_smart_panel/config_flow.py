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

from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_entry_oauth2_flow
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

        if self.source == SOURCE_REAUTH:
            entry = self._get_reauth_entry()
            # Entries from before v1.1 have the domain as unique_id and accept any account.
            if entry.unique_id != DOMAIN:
                self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(
                entry, unique_id=user_id, data=data
            )

        # New entry: prevent duplicate accounts
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=f"Basis ({email})", data=data)
