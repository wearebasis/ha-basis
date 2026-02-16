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

import logging

from typing import Any
from collections.abc import Mapping

from homeassistant.config_entries import ConfigEntry
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

    async def async_oauth_create_entry(self, data: dict) -> FlowResult:
        """Create an entry."""
        existing_entry = await self.async_set_unique_id(DOMAIN)
        if existing_entry:
            self.hass.config_entries.async_update_entry(existing_entry, data=data)
            await self.hass.config_entries.async_reload(existing_entry.entry_id)
            return self.async_abort(reason="reauth_successful")
        return await super().async_oauth_create_entry(data)
