"""Fixtures for Basis Smart Panel tests."""

from __future__ import annotations

import base64
import json
import time
from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion

from custom_components.basis_smart_panel.const import DOMAIN

from .fake_backend import FakeBasisBackend

USER_SUB = "auth0|user-1"
USER_EMAIL = "user@example.com"
ACCESS_TOKEN = "test-access-token"
NOW = "2026-10-15T10:00:00+13:00"


def make_id_token(sub: str, email: str) -> str:
    """Return an unsigned JWT with the claims that the integration reads."""

    def encode(part: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(part).encode()).rstrip(b"=").decode()

    return f"{encode({'alg': 'none'})}.{encode({'sub': sub, 'email': email})}.sig"


def make_token(sub: str = USER_SUB, email: str = USER_EMAIL) -> dict:
    """Return a token that is valid for one hour."""
    return {
        "access_token": ACCESS_TOKEN,
        "refresh_token": "test-refresh-token",
        "id_token": make_id_token(sub, email),
        "scope": "home openid profile email offline_access",
        "token_type": "Bearer",
        "expires_in": 3600,
        "expires_at": time.time() + 3600,
    }


# The plugin defines this fixture too, but syrupy's plugin registers later and hides it.
@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Serialize Home Assistant objects without their random IDs."""
    return snapshot.use_extension(HomeAssistantSnapshotExtension)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the integration from custom_components."""


@pytest.fixture(autouse=True)
async def nz_time(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Run every test at a fixed time in the time zone of the panels."""
    await hass.config.async_set_time_zone("Pacific/Auckland")
    freezer.move_to(NOW)


@pytest.fixture
async def fake_backend(socket_enabled: None) -> AsyncGenerator[FakeBasisBackend]:
    """Point the integration at a fake GraphQL API."""
    backend = FakeBasisBackend()
    await backend.start()
    with (
        patch("custom_components.basis_smart_panel.api.API_BASE_URL", backend.url),
        patch("custom_components.basis_smart_panel.api.RETRY_DELAY_SECONDS", 0),
    ):
        yield backend
    await backend.close()


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a config entry for one Basis account."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Basis ({USER_EMAIL})",
        unique_id=USER_SUB,
        data={"auth_implementation": DOMAIN, "token": make_token()},
    )


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add the config entry and wait for the setup to finish."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
