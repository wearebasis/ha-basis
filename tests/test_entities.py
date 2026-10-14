"""Snapshot of the entities and devices that the integration creates."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

from custom_components.basis_smart_panel.const import DOMAIN

from .conftest import POLL, advance, circuit_uid, setup_integration
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


async def test_circuit_name_uses_the_name_from_the_app(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    fake_backend.board(SERIAL_A)["subcircuits"][0]["config"]["name_from_app"] = "Kitchen"
    await setup_integration(hass, config_entry)

    entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, circuit_uid("power", SERIAL_A, 1)
    )
    state = hass.states.get(entity_id)
    assert state.name == f"Basis Panel {SERIAL_A} [01] Kitchen · Power"
    assert state.attributes["icon"] == "mdi:lightbulb"


def panel_device(
    device_registry: dr.DeviceRegistry, entry: MockConfigEntry, serial: str
) -> dr.DeviceEntry:
    return next(
        device
        for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id)
        if (DOMAIN, serial) in device.identifiers
    )


async def test_device_uses_the_panel_name_from_the_app(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    fake_backend.board(SERIAL_A)["name"] = "Office Panel"
    await setup_integration(hass, config_entry)

    device = panel_device(device_registry, config_entry, SERIAL_A)
    assert device.name == "Office Panel"
    assert device.serial_number == SERIAL_A
    entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, circuit_uid("power", SERIAL_A, 1)
    )
    assert hass.states.get(entity_id).name == "Office Panel [01] Lights · Power"


async def test_device_name_follows_a_rename_in_the_app(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    fake_backend.board(SERIAL_A)["name"] = "Office Panel"
    await setup_integration(hass, config_entry)

    fake_backend.board(SERIAL_A)["name"] = "Garage Panel"
    await advance(hass, freezer, POLL)

    assert panel_device(device_registry, config_entry, SERIAL_A).name == "Garage Panel"


async def test_separator_keeps_name_and_measurement_apart(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)

    def name(domain: str, key: str, number: int) -> str:
        entity_id = entity_registry.async_get_entity_id(
            domain, DOMAIN, circuit_uid(key, SERIAL_A, number)
        )
        return hass.states.get(entity_id).name

    assert name("sensor", "power", 2) == f"Basis Panel {SERIAL_A} [02] Power · Power"
    assert name("sensor", "current", 2) == f"Basis Panel {SERIAL_A} [02] Power · Current"
    assert name("switch", "switch", 2) == f"Basis Panel {SERIAL_A} [02] Power"


async def test_device_name_set_in_ha_survives_a_rename_in_the_app(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    fake_backend.board(SERIAL_A)["name"] = "Office Panel"
    await setup_integration(hass, config_entry)
    device = panel_device(device_registry, config_entry, SERIAL_A)
    device_registry.async_update_device(device.id, name_by_user="My Panel")

    fake_backend.board(SERIAL_A)["name"] = "Garage Panel"
    await advance(hass, freezer, POLL)

    device = panel_device(device_registry, config_entry, SERIAL_A)
    assert device.name_by_user == "My Panel"
    assert device.name == "Garage Panel"
    entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, circuit_uid("power", SERIAL_A, 1)
    )
    assert hass.states.get(entity_id).name == "My Panel [01] Lights · Power"
