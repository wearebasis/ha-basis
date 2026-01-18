from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.components.application_credentials import ClientCredential
from homeassistant.helpers.config_entry_oauth2_flow import AbstractOAuth2Implementation, LocalOAuth2ImplementationWithPkce

from .const import OAUTH2_AUTHORIZE, OAUTH2_TOKEN

async def async_get_auth_implementation(
    hass: HomeAssistant, auth_domain: str, credential: ClientCredential
) -> AbstractOAuth2Implementation:
    """Return auth implementation for a custom auth implementation."""
    return LocalOAuth2ImplementationWithPkce(
        hass,
        auth_domain,
        credential.client_id,
        authorize_url=OAUTH2_AUTHORIZE,
        token_url=OAUTH2_TOKEN,
        client_secret=credential.client_secret, # optional `""` is default
        code_verifier_length=128 # optional
    )
