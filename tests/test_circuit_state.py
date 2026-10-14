"""Tests for the fault and state sensors of a circuit."""

from __future__ import annotations

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.basis_smart_panel.const import DOMAIN

from .conftest import POLL, advance, circuit_uid, setup_integration
from .fake_backend import SERIAL_A, FakeBasisBackend


@pytest.mark.parametrize(
    ("api_state", "fault", "state"),
    [
        ("LIVE", STATE_OFF, "live"),
        ("STANDBY", STATE_OFF, "standby"),
        ("SAFE", STATE_OFF, "safe"),
        ("ELECTRICAL_FAULT", STATE_ON, "electrical_fault"),
        ("SYSTEM_FAULT", STATE_OFF, "system_fault"),
        ("LOCKOUT", STATE_OFF, "lockout"),
        ("UNKNOWN", STATE_UNKNOWN, STATE_UNKNOWN),
        ("UNAVAILABLE", STATE_UNKNOWN, STATE_UNKNOWN),
    ],
)
async def test_fault_and_state_follow_the_circuit_state(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    api_state: str,
    fault: str,
    state: str,
) -> None:
    await setup_integration(hass, config_entry)

    fake_backend.board(SERIAL_A)["subcircuits"][0]["liveState"]["state"] = api_state
    await advance(hass, freezer, POLL)

    fault_id = entity_registry.async_get_entity_id(
        "binary_sensor", DOMAIN, circuit_uid("fault", SERIAL_A, 1)
    )
    state_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, circuit_uid("state", SERIAL_A, 1)
    )
    assert hass.states.get(fault_id).state == fault
    assert hass.states.get(state_id).state == state


async def test_locked_circuit_has_fault_and_state(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)

    assert entity_registry.async_get_entity_id(
        "binary_sensor", DOMAIN, circuit_uid("fault", SERIAL_A, 3)
    )
    assert entity_registry.async_get_entity_id(
        "sensor", DOMAIN, circuit_uid("state", SERIAL_A, 3)
    )
    assert not entity_registry.async_get_entity_id(
        "binary_sensor", DOMAIN, circuit_uid("fault", SERIAL_A, 4)
    )


async def test_state_is_a_diagnostic_entity_with_translated_options(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)

    entry = entity_registry.async_get(
        entity_registry.async_get_entity_id("sensor", DOMAIN, circuit_uid("state", SERIAL_A, 1))
    )
    assert entry.entity_category is EntityCategory.DIAGNOSTIC
    translations = await async_get_translations(hass, "en", "entity", {DOMAIN})
    prefix = f"component.{DOMAIN}.entity.sensor.circuit_state.state"
    for option in entry.capabilities["options"]:
        assert translations.get(f"{prefix}.{option}")
