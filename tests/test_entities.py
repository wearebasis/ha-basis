"""Snapshot of the entities and devices that the integration creates."""

from __future__ import annotations

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

from custom_components.basis_smart_panel.const import DOMAIN

from .conftest import POLL, advance, circuit_device, circuit_uid, setup_integration
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
    assert state.name == f"01 · Kitchen · Basis Panel {SERIAL_A} Power"
    assert state.attributes["icon"] == "mdi:lightbulb"


@pytest.mark.parametrize(
    ("label", "name"), [("sauna", "Sauna"), ("extLights", "Outside Lights")]
)
async def test_circuit_name_uses_the_label_text_of_the_app(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    label: str,
    name: str,
) -> None:
    fake_backend.board(SERIAL_A)["subcircuits"][0]["config"]["label"] = label
    await setup_integration(hass, config_entry)

    device = circuit_device(device_registry, config_entry, SERIAL_A, 1)
    assert device.name == f"01 · {name} · Basis Panel {SERIAL_A}"


async def test_entity_ids_use_the_serial_and_position_not_the_names(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    fake_backend.board(SERIAL_A)["name"] = "Office Panel"
    fake_backend.board(SERIAL_A)["subcircuits"][0]["config"]["name_from_app"] = "Kitchen"
    await setup_integration(hass, config_entry)

    def entity_id(domain: str, unique_id: str) -> str | None:
        return entity_registry.async_get_entity_id(domain, DOMAIN, unique_id)

    prefix = "basis_panel_sb_0000000001"
    assert entity_id("sensor", circuit_uid("power", SERIAL_A, 1)) == f"sensor.{prefix}_01_power"
    assert (
        entity_id("sensor", circuit_uid("energy_import", SERIAL_A, 1))
        == f"sensor.{prefix}_01_consumption_energy_today"
    )
    assert entity_id("switch", circuit_uid("switch", SERIAL_A, 1)) == f"switch.{prefix}_01"
    assert (
        entity_id("sensor", f"basis_power_panel_{SERIAL_A}") == f"sensor.{prefix}_net_power"
    )
    assert (
        entity_id("binary_sensor", f"basis_connectivity_{SERIAL_A}")
        == f"binary_sensor.{prefix}_connectivity"
    )


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
    assert device.model == "Smart Panel"
    assert device.serial_number == SERIAL_A
    entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, circuit_uid("power", SERIAL_A, 1)
    )
    assert hass.states.get(entity_id).name == "01 · Lights · Office Panel Power"


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


async def test_circuit_entities_take_the_circuit_device_name(
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

    assert name("sensor", "power", 2) == f"02 · Power · Basis Panel {SERIAL_A} Power"
    assert name("sensor", "current", 2) == f"02 · Power · Basis Panel {SERIAL_A} Current"
    assert name("switch", "switch", 2) == f"02 · Power · Basis Panel {SERIAL_A}"


async def test_circuit_device_name_follows_a_rename_in_the_app(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    await setup_integration(hass, config_entry)

    fake_backend.board(SERIAL_A)["name"] = "Office Panel"
    fake_backend.board(SERIAL_A)["subcircuits"][0]["config"]["name_from_app"] = "Kitchen"
    await advance(hass, freezer, POLL)

    device = circuit_device(device_registry, config_entry, SERIAL_A, 1)
    assert device.name == "01 · Kitchen · Office Panel"


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
    assert hass.states.get(entity_id).name == "01 · Lights · My Panel Power"
