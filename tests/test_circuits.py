"""Tests for how circuit entities follow the circuits of a panel."""

from __future__ import annotations

from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.basis_smart_panel import BOARD_REMOVAL_POLLS
from custom_components.basis_smart_panel.const import DOMAIN

from .conftest import (
    DISCOVERY,
    POLL,
    advance,
    board_device,
    circuit_device,
    circuit_uid,
    setup_integration,
)
from .fake_backend import SERIAL_A, SERIAL_B, FakeBasisBackend, subcircuit

CIRCUIT_KEYS = ("power", "current", "voltage", "energy_import", "switch", "fault", "state")


def entity_id_of(
    entity_registry: er.EntityRegistry, domain: str, key: str, number: int
) -> str | None:
    return entity_registry.async_get_entity_id(
        domain, DOMAIN, circuit_uid(key, SERIAL_A, number)
    )


async def test_circuit_entities_are_on_a_circuit_device_under_the_panel(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)

    device = circuit_device(device_registry, config_entry, SERIAL_A, 1)
    assert device.via_device_id == board_device(device_registry, config_entry, SERIAL_A).id
    assert {
        entry.unique_id for entry in er.async_entries_for_device(entity_registry, device.id)
    } == {circuit_uid(key, SERIAL_A, 1) for key in CIRCUIT_KEYS}
    assert circuit_device(device_registry, config_entry, SERIAL_A, 4) is None


async def test_existing_circuit_entities_move_to_the_circuit_device(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    config_entry.add_to_hass(hass)
    panel = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={(DOMAIN, SERIAL_A)}
    )
    old_power = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        circuit_uid("power", SERIAL_A, 1),
        config_entry=config_entry,
        device_id=panel.id,
        suggested_object_id="my_lights_power",
    )

    await setup_integration(hass, config_entry)

    device = circuit_device(device_registry, config_entry, SERIAL_A, 1)
    assert entity_registry.async_get(old_power.entity_id).device_id == device.id
    assert hass.states.get(old_power.entity_id).state == "120.5"


async def test_new_circuit_device_gets_the_area_of_the_panel(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    area_registry: ar.AreaRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    garage = area_registry.async_create("Garage")
    config_entry.add_to_hass(hass)
    panel = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={(DOMAIN, SERIAL_A)}
    )
    device_registry.async_update_device(panel.id, area_id=garage.id)

    await setup_integration(hass, config_entry)

    assert circuit_device(device_registry, config_entry, SERIAL_A, 1).area_id == garage.id


async def test_existing_circuit_device_does_not_take_the_panel_area(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    area_registry: ar.AreaRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    garage = area_registry.async_create("Garage")
    await setup_integration(hass, config_entry)
    panel = board_device(device_registry, config_entry, SERIAL_A)
    device_registry.async_update_device(panel.id, area_id=garage.id)
    device = circuit_device(device_registry, config_entry, SERIAL_A, 1)
    assert device.area_id is None

    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert circuit_device(device_registry, config_entry, SERIAL_A, 1).area_id is None


async def test_unique_ids_move_from_module_serial_to_position(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    config_entry.add_to_hass(hass)
    old_power = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"basis_power_{SERIAL_A}_SC-A01",
        config_entry=config_entry,
        suggested_object_id="my_lights_power",
    )
    old_switch = entity_registry.async_get_or_create(
        SWITCH_DOMAIN,
        DOMAIN,
        f"basis_switch_{SERIAL_A}_SC-A01",
        config_entry=config_entry,
        suggested_object_id="my_lights",
    )

    await setup_integration(hass, config_entry)

    assert entity_id_of(entity_registry, "sensor", "power", 1) == old_power.entity_id
    assert entity_id_of(entity_registry, SWITCH_DOMAIN, "switch", 1) == old_switch.entity_id
    assert hass.states.get(old_power.entity_id).state == "120.5"
    assert not entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"basis_power_{SERIAL_A}_SC-A01"
    )


async def test_old_entity_of_a_missing_circuit_is_kept_until_it_returns(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    config_entry.add_to_hass(hass)
    panel = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={(DOMAIN, SERIAL_A)}
    )
    old_power = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"basis_power_{SERIAL_A}_SC-A01",
        config_entry=config_entry,
        device_id=panel.id,
        suggested_object_id="my_lights_power",
    )
    circuits = fake_backend.board(SERIAL_A)["subcircuits"]
    lights = circuits.pop(0)

    await setup_integration(hass, config_entry)

    assert entity_registry.async_get(old_power.entity_id)

    circuits.insert(0, lights)
    await advance(hass, freezer, POLL)

    assert entity_id_of(entity_registry, "sensor", "power", 1) == old_power.entity_id


async def test_original_entity_takes_the_position_of_a_module_replaced_before_the_upgrade(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    config_entry.add_to_hass(hass)
    panel = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={(DOMAIN, SERIAL_A)}
    )
    original, replacement = (
        entity_registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"basis_power_{SERIAL_A}_{module}",
            config_entry=config_entry,
            device_id=panel.id,
            suggested_object_id="my_lights_power",
        )
        for module in ("SC-OLD", "SC-A01")
    )
    assert replacement.entity_id == f"{original.entity_id}_2"

    await setup_integration(hass, config_entry)

    assert entity_id_of(entity_registry, "sensor", "power", 1) == original.entity_id
    assert hass.states.get(original.entity_id).state == "120.5"
    assert not entity_registry.async_get(replacement.entity_id)


async def test_failed_platform_keeps_its_entities(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    switch = entity_id_of(entity_registry, SWITCH_DOMAIN, "switch", 1)
    assert switch

    with patch(
        "custom_components.basis_smart_panel.switch.async_setup_entry",
        side_effect=RuntimeError("platform failed"),
    ):
        await hass.config_entries.async_reload(config_entry.entry_id)
        await hass.async_block_till_done()

    assert entity_registry.async_get(switch)


async def test_replaced_module_keeps_entities(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    power = entity_id_of(entity_registry, "sensor", "power", 1)
    switch = entity_id_of(entity_registry, SWITCH_DOMAIN, "switch", 1)

    circuits = fake_backend.board(SERIAL_A)["subcircuits"]
    circuits[0] = subcircuit(1, "SC-NEW", "lights", power=60.0)
    fake_backend.subcircuit_energy[SERIAL_A]["SC-NEW"] = []
    await advance(hass, freezer, POLL)

    assert hass.states.get(power).state == "60.0"
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: switch}, blocking=True
    )
    assert fake_backend.standby_calls[-1]["subcircuitSerial"] == "SC-NEW"


async def test_locked_circuit_loses_its_switch(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    assert entity_id_of(entity_registry, SWITCH_DOMAIN, "switch", 1)

    fake_backend.board(SERIAL_A)["subcircuits"][0]["config"]["standbyLocked"] = True
    await advance(hass, freezer, POLL)

    assert config_entry.state is ConfigEntryState.LOADED
    assert not entity_id_of(entity_registry, SWITCH_DOMAIN, "switch", 1)
    assert entity_id_of(entity_registry, "sensor", "power", 1)


async def test_spare_circuit_gets_entities_when_labelled(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    assert not entity_id_of(entity_registry, "sensor", "power", 4)

    fake_backend.board(SERIAL_A)["subcircuits"][3]["config"]["label"] = "lights"
    await advance(hass, freezer, POLL)

    assert entity_id_of(entity_registry, "sensor", "power", 4)
    assert entity_id_of(entity_registry, SWITCH_DOMAIN, "switch", 4)


async def test_circuit_that_becomes_spare_loses_its_device(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)

    fake_backend.board(SERIAL_A)["subcircuits"][0]["config"]["label"] = "spare"
    await advance(hass, freezer, POLL)

    assert circuit_device(device_registry, config_entry, SERIAL_A, 1) is None
    assert not entity_id_of(entity_registry, "sensor", "power", 1)
    assert circuit_device(device_registry, config_entry, SERIAL_A, 2)


async def test_new_circuit_gets_entities(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)

    fake_backend.board(SERIAL_A)["subcircuits"].append(subcircuit(8, "SC-A08", "pool"))
    await advance(hass, freezer, POLL)

    assert entity_id_of(entity_registry, "sensor", "power", 8)


async def test_removed_circuit_loses_its_entities(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)

    circuits = fake_backend.board(SERIAL_A)["subcircuits"]
    circuits[:] = [sub for sub in circuits if sub["number"] != 1]
    await advance(hass, freezer, POLL)

    assert not entity_id_of(entity_registry, "sensor", "power", 1)
    assert not entity_id_of(entity_registry, SWITCH_DOMAIN, "switch", 1)
    assert entity_id_of(entity_registry, "sensor", "power", 2)
    assert circuit_device(device_registry, config_entry, SERIAL_A, 1) is None


async def test_circuit_devices_stay_through_discovery_polls(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    await setup_integration(hass, config_entry)

    for _ in range(BOARD_REMOVAL_POLLS):
        await advance(hass, freezer, DISCOVERY)

    assert circuit_device(device_registry, config_entry, SERIAL_A, 1)


async def test_board_without_data_keeps_its_circuit_devices(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    config_entry.add_to_hass(hass)
    panel = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={(DOMAIN, SERIAL_B)}
    )
    device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, f"{SERIAL_B}_circuit_1")},
        via_device_id=panel.id,
    )
    fake_backend.broken_boards.add(SERIAL_B)

    await setup_integration(hass, config_entry)

    assert circuit_device(device_registry, config_entry, SERIAL_B, 1)


async def test_empty_circuit_list_changes_nothing(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)

    fake_backend.board(SERIAL_A)["subcircuits"] = []
    await advance(hass, freezer, POLL)
    await advance(hass, freezer, POLL)

    assert entity_id_of(entity_registry, "sensor", "power", 1)
    assert entity_id_of(entity_registry, SWITCH_DOMAIN, "switch", 1)


async def test_switch_state_unknown_when_circuit_not_live_or_standby(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    switch = entity_id_of(entity_registry, SWITCH_DOMAIN, "switch", 1)

    fake_backend.board(SERIAL_A)["subcircuits"][0]["liveState"]["state"] = "UNAVAILABLE"
    await advance(hass, freezer, POLL)

    assert hass.states.get(switch).state == STATE_UNKNOWN
