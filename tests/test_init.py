"""Tests for setup, unload and board changes."""

from __future__ import annotations

from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.basis_smart_panel.const import (
    DOMAIN,
    SWITCHBOARD_UPDATE_INTERVAL,
)

from .conftest import ACCESS_TOKEN, USER_SUB, make_token, setup_integration
from .fake_backend import SERIAL_A, SERIAL_B, FakeBasisBackend, subcircuit

# The coordinator adds up to 1 s of jitter to each refresh.
POLL = SWITCHBOARD_UPDATE_INTERVAL + timedelta(seconds=1)


async def advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta) -> None:
    """Move the clock and run the timers that are due."""
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


def board_device(
    device_registry: dr.DeviceRegistry, entry: MockConfigEntry, serial: str
) -> dr.DeviceEntry | None:
    return next(
        (
            device
            for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id)
            if (DOMAIN, serial) in device.identifiers
        ),
        None,
    )


async def test_setup_and_unload(
    hass: HomeAssistant, fake_backend: FakeBasisBackend, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED


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
        "sensor", DOMAIN, f"basis_power_{SERIAL_A}_SC-A01"
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
        "sensor", DOMAIN, f"basis_power_{SERIAL_A}_SC-A02"
    )

    fake_backend.board(SERIAL_A)["subcircuits"][1]["liveState"]["power"] = 1200.0
    await advance(hass, freezer, POLL)
    assert hass.states.get(entity_id).state == "1200.0"


@pytest.mark.xfail(
    strict=True,
    reason="the board-change handler unloads all platforms, then "
    "async_config_entry_first_refresh raises because the entry is LOADED",
)
async def test_board_added_after_setup(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    fake_backend.remove_board(SERIAL_B)
    await setup_integration(hass, config_entry)
    power_a = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"basis_power_{SERIAL_A}_SC-A01"
    )

    fake_backend.sites["site-2"] = [SERIAL_B]
    await advance(hass, freezer, timedelta(minutes=5))

    assert hass.states.get(power_a).state == "120.5"
    assert entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"basis_power_{SERIAL_B}_SC-B01"
    )


async def test_board_removed_after_setup(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    assert board_device(device_registry, config_entry, SERIAL_B)

    fake_backend.remove_board(SERIAL_B)
    await advance(hass, freezer, timedelta(minutes=5))

    assert board_device(device_registry, config_entry, SERIAL_B) is None
    assert not entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"basis_power_{SERIAL_B}_SC-B01"
    )
    power_a = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"basis_power_{SERIAL_A}_SC-A01"
    )
    assert hass.states.get(power_a).state == "120.5"


@pytest.mark.xfail(
    strict=True,
    reason="sensor.py calls .get on a null subcircuit liveState",
)
async def test_subcircuit_without_live_state(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    new_circuit = subcircuit(8, "SC-A08", "pool")
    new_circuit["liveState"] = None
    fake_backend.board(SERIAL_A)["subcircuits"].append(new_circuit)
    await setup_integration(hass, config_entry)

    entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"basis_power_{SERIAL_A}_SC-A08"
    )
    assert entity_id
    assert hass.states.get(entity_id).state == "unknown"
