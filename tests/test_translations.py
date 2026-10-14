"""Tests for the translations that the config flow uses."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations

from custom_components.basis_smart_panel.const import DOMAIN

ABORT_REASONS = [
    "already_configured",
    "wrong_account",
    "reauth_successful",
    "authorize_url_timeout",
    "missing_configuration",
    "missing_credentials",
    "no_url_available",
    "oauth_error",
    "oauth_failed",
    "oauth_implementation_unavailable",
    "oauth_timeout",
    "oauth_unauthorized",
    "user_rejected_authorize",
]


@pytest.mark.parametrize("reason", ABORT_REASONS)
async def test_abort_reason_has_text(hass: HomeAssistant, reason: str) -> None:
    translations = await async_get_translations(hass, "en", "config", {DOMAIN})
    assert translations.get(f"component.{DOMAIN}.config.abort.{reason}")


async def test_reauth_dialog_has_text(hass: HomeAssistant) -> None:
    translations = await async_get_translations(hass, "en", "config", {DOMAIN})
    prefix = f"component.{DOMAIN}.config.step.reauth_confirm"
    assert translations.get(f"{prefix}.title")
    assert translations.get(f"{prefix}.description")
