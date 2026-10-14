"""Tests for setup, unload and board changes."""

from __future__ import annotations

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.basis_smart_panel import BOARD_REMOVAL_POLLS
from custom_components.basis_smart_panel.const import DOMAIN

from .conftest import (
    ACCESS_TOKEN,
    DISCOVERY,
    POLL,
    USER_SUB,
    advance,
    board_device,
    circuit_device,
    circuit_uid,
    make_token,
    power_entity,
    setup_integration,
)
from .fake_backend import SERIAL_A, SERIAL_B, FakeBasisBackend, subcircuit


async def test_setup_and_unload(
    hass: HomeAssistant, fake_backend: FakeBasisBackend, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_and_polls_cause_no_ha_usage_report(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await setup_integration(hass, config_entry)
    await advance(hass, freezer, POLL)

    assert "Detected that custom integration" not in caplog.text


async def test_requests_carry_token_and_user_agent(
    hass: HomeAssistant, fake_backend: FakeBasisBackend, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)

    assert fake_backend.requests
    for request in fake_backend.requests:
        assert request["headers"]["Authorization"] == f"Bearer {ACCESS_TOKEN}"
        assert request["headers"]["User-Agent"].startswith(
            "HomeAssistantBasisSmartPanelIntegration/"
        )


async def test_setup_retries_when_api_fails(
    hass: HomeAssistant, fake_backend: FakeBasisBackend, config_entry: MockConfigEntry
) -> None:
    fake_backend.fail_status = 503
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_legacy_unique_id_migrates_to_user_sub(
    hass: HomeAssistant, fake_backend: FakeBasisBackend
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={"auth_implementation": DOMAIN, "token": make_token()},
    )
    await setup_integration(hass, entry)
    assert entry.unique_id == USER_SUB


async def test_entities_unavailable_when_poll_fails(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, circuit_uid("power", SERIAL_A, 1)
    )
    assert hass.states.get(entity_id).state == "120.5"

    fake_backend.fail_status = 503
    await advance(hass, freezer, POLL)
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE

    fake_backend.fail_status = None
    await advance(hass, freezer, POLL)
    assert hass.states.get(entity_id).state == "120.5"


async def test_live_values_update_on_poll(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, circuit_uid("power", SERIAL_A, 2)
    )

    fake_backend.board(SERIAL_A)["subcircuits"][1]["liveState"]["power"] = 1200.0
    await advance(hass, freezer, POLL)
    assert hass.states.get(entity_id).state == "1200.0"


async def test_board_added_after_setup(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    fake_backend.remove_board(SERIAL_B)
    await setup_integration(hass, config_entry)

    fake_backend.sites["site-2"] = [SERIAL_B]
    await advance(hass, freezer, DISCOVERY)

    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(power_entity(entity_registry, SERIAL_A, 1)).state == "120.5"
    assert hass.states.get(power_entity(entity_registry, SERIAL_B, 1))


async def test_board_removed_after_missing_polls(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    await setup_integration(hass, config_entry)

    fake_backend.remove_board(SERIAL_B)
    for _ in range(BOARD_REMOVAL_POLLS - 1):
        await advance(hass, freezer, DISCOVERY)
    assert board_device(device_registry, config_entry, SERIAL_B)

    await advance(hass, freezer, DISCOVERY)
    assert board_device(device_registry, config_entry, SERIAL_B) is None
    assert circuit_device(device_registry, config_entry, SERIAL_B, 1) is None
    assert not entity_registry.async_get_entity_id(
        "sensor", DOMAIN, circuit_uid("power", SERIAL_B, 1)
    )
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(power_entity(entity_registry, SERIAL_A, 1)).state == "120.5"


async def test_board_missing_once_is_kept(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    await setup_integration(hass, config_entry)

    fake_backend.remove_board(SERIAL_B)
    await advance(hass, freezer, DISCOVERY)
    fake_backend.sites["site-2"] = [SERIAL_B]
    for _ in range(BOARD_REMOVAL_POLLS):
        await advance(hass, freezer, DISCOVERY)

    assert board_device(device_registry, config_entry, SERIAL_B)


async def test_empty_board_list_removes_nothing(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    await setup_integration(hass, config_entry)

    fake_backend.sites = {}
    for _ in range(BOARD_REMOVAL_POLLS + 1):
        await advance(hass, freezer, DISCOVERY)

    assert board_device(device_registry, config_entry, SERIAL_A)
    assert board_device(device_registry, config_entry, SERIAL_B)


async def test_orphan_device_removed_after_missing_polls(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    config_entry.add_to_hass(hass)
    device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={(DOMAIN, "SB-REMOVED")}
    )
    await setup_integration(hass, config_entry)

    for _ in range(BOARD_REMOVAL_POLLS):
        await advance(hass, freezer, DISCOVERY)

    assert board_device(device_registry, config_entry, "SB-REMOVED") is None
    assert board_device(device_registry, config_entry, SERIAL_A)


@pytest.mark.parametrize(
    ("domain", "unique_id"),
    [
        ("sensor", circuit_uid("power", SERIAL_A, 8)),
        ("sensor", circuit_uid("current", SERIAL_A, 8)),
        ("sensor", circuit_uid("voltage", SERIAL_A, 8)),
        ("switch", circuit_uid("switch", SERIAL_A, 8)),
    ],
)
async def test_subcircuit_without_live_state(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    domain: str,
    unique_id: str,
) -> None:
    new_circuit = subcircuit(8, "SC-A08", "pool")
    new_circuit["liveState"] = None
    fake_backend.board(SERIAL_A)["subcircuits"].append(new_circuit)
    await setup_integration(hass, config_entry)

    entity_id = entity_registry.async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id
    assert hass.states.get(entity_id).state == STATE_UNKNOWN


async def test_board_without_subcircuits(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    fake_backend.board(SERIAL_A)["subcircuits"] = []
    await setup_integration(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert board_device(device_registry, config_entry, SERIAL_A).hw_version == "Unknown"


async def test_failing_board_does_not_block_other_boards(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    fake_backend.broken_boards.add(SERIAL_B)
    await setup_integration(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(power_entity(entity_registry, SERIAL_A, 1)).state == "120.5"
    connectivity_b = entity_registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"basis_connectivity_{SERIAL_B}"
    )
    assert hass.states.get(connectivity_b).state == STATE_UNAVAILABLE
    assert not entity_registry.async_get_entity_id(
        "sensor", DOMAIN, circuit_uid("power", SERIAL_B, 1)
    )

    fake_backend.broken_boards.clear()
    await advance(hass, freezer, POLL)

    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(power_entity(entity_registry, SERIAL_B, 1))
    assert hass.states.get(connectivity_b).state == "off"


async def test_failing_energy_does_not_block_live_data(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    fake_backend.broken_energy.add(SERIAL_A)
    await setup_integration(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(power_entity(entity_registry, SERIAL_A, 1)).state == "120.5"
    energy_today = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"basis_energy_today_import_{SERIAL_A}"
    )
    assert hass.states.get(energy_today).state == STATE_UNAVAILABLE
