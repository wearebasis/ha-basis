"""Tests for the connectivity binary sensor."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.basis_smart_panel.const import DOMAIN

from .conftest import POLL, advance, setup_integration
from .fake_backend import SERIAL_A, SERIAL_B, FakeBasisBackend


def connectivity_entity(entity_registry: er.EntityRegistry, serial: str) -> er.RegistryEntry:
    entity_id = entity_registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"basis_connectivity_{serial}"
    )
    assert entity_id
    return entity_registry.async_get(entity_id)


async def test_connectivity_is_a_diagnostic_entity(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)

    assert connectivity_entity(entity_registry, SERIAL_A).entity_category is EntityCategory.DIAGNOSTIC


async def test_connected_panel_does_not_write_a_state_on_each_poll(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    entity_id = connectivity_entity(entity_registry, SERIAL_A).entity_id
    before = hass.states.get(entity_id)

    fake_backend.board(SERIAL_A)["connectivity"]["updatedTimestamp"] = "2026-10-14T21:00:04Z"
    await advance(hass, freezer, POLL)

    after = hass.states.get(entity_id)
    assert after.state == "on"
    assert "last_seen" not in after.attributes
    assert after.last_updated == before.last_updated


async def test_disconnected_panel_shows_last_seen_and_reason(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)

    state = hass.states.get(connectivity_entity(entity_registry, SERIAL_B).entity_id)
    assert state.state == "off"
    assert state.attributes["last_seen"] == "2026-10-14T08:00:00Z"
    assert state.attributes["disconnect_reason"] == "UNKNOWN"
