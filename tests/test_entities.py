"""Snapshot of the entities and devices that the integration creates."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from syrupy.assertion import SnapshotAssertion

from custom_components.basis_smart_panel.const import (
    DOMAIN,
    SWITCHBOARD_UPDATE_INTERVAL,
)

from .conftest import setup_integration
from .fake_backend import SERIAL_A, FakeBasisBackend


async def test_entities(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await setup_integration(hass, config_entry)

    entries = er.async_entries_for_config_entry(entity_registry, config_entry.entry_id)
    assert entries
    for entry in sorted(entries, key=lambda e: e.entity_id):
        assert entry == snapshot(name=f"{entry.entity_id}-entry")
        assert hass.states.get(entry.entity_id) == snapshot(name=f"{entry.entity_id}-state")


async def test_devices(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await setup_integration(hass, config_entry)

    devices = dr.async_entries_for_config_entry(device_registry, config_entry.entry_id)
    assert sorted(devices, key=lambda d: sorted(d.identifiers)) == snapshot


async def test_circuit_missing_from_data(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    power = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"basis_power_{SERIAL_A}_SC-A01"
    )
    switch = entity_registry.async_get_entity_id(
        "switch", DOMAIN, f"basis_switch_{SERIAL_A}_SC-A01"
    )

    subcircuits = fake_backend.board(SERIAL_A)["subcircuits"]
    subcircuits[:] = [sub for sub in subcircuits if sub["serial"] != "SC-A01"]
    freezer.tick(SWITCHBOARD_UPDATE_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    power_state = hass.states.get(power)
    assert power_state.state == STATE_UNKNOWN
    assert power_state.attributes["friendly_name"] == f"Basis Panel {SERIAL_A} [01] Power"
    assert power_state.attributes["icon"] == "mdi:flash"
    switch_state = hass.states.get(switch)
    assert switch_state.state == STATE_UNKNOWN
    assert switch_state.attributes["friendly_name"] == f"Basis Panel {SERIAL_A} [01] Circuit"
    assert switch_state.attributes["icon"] == "mdi:power-socket"
