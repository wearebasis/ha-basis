"""Tests for sites, and for sites that more than one account can see."""

from __future__ import annotations

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.basis_smart_panel import BOARD_REMOVAL_POLLS
from custom_components.basis_smart_panel.const import DOMAIN

from .conftest import (
    DISCOVERY,
    advance,
    board_device,
    power_entity,
    setup_integration,
)
from .fake_backend import MONTH_START, SERIAL_A, SERIAL_B, TODAY_START, FakeBasisBackend

SITE_ENERGY_TODAY = "basis_energy_today_import_site_site-1"


def site_device(
    device_registry: dr.DeviceRegistry, entry: MockConfigEntry, site_id: str
) -> dr.DeviceEntry | None:
    return next(
        (
            device
            for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id)
            if (DOMAIN, f"site_{site_id}") in device.identifiers
        ),
        None,
    )


def share_site_1(fake_backend: FakeBasisBackend) -> None:
    """Put both panels in site-1, with energy totals for the site."""
    fake_backend.sites = {"site-1": [SERIAL_A, SERIAL_B]}
    fake_backend.site_energy["site-1"] = {
        TODAY_START: {"importKwh": 20.0, "exportKwh": 3.25},
        MONTH_START: {"importKwh": 400.0, "exportKwh": 80.5},
    }


async def test_panel_device_is_under_its_site_device(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    share_site_1(fake_backend)
    await setup_integration(hass, config_entry)

    site = site_device(device_registry, config_entry, "site-1")
    assert site.name == "1 Example Street"
    assert site.model == "Site"
    assert board_device(device_registry, config_entry, SERIAL_A).via_device_id == site.id


async def test_site_device_without_address_has_default_name(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    share_site_1(fake_backend)
    fake_backend.site_details["site-1"]["address"] = None
    await setup_integration(hass, config_entry)

    assert site_device(device_registry, config_entry, "site-1").name == "Basis Site"


async def test_site_with_one_panel_has_no_device(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    await setup_integration(hass, config_entry)

    assert site_device(device_registry, config_entry, "site-1") is None
    assert board_device(device_registry, config_entry, SERIAL_A).via_device_id is None


async def test_site_without_panels_has_no_device(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    fake_backend.sites["site-3"] = []
    await setup_integration(hass, config_entry)

    assert site_device(device_registry, config_entry, "site-3") is None


async def test_site_device_removed_when_site_keeps_one_panel(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    share_site_1(fake_backend)
    await setup_integration(hass, config_entry)

    fake_backend.remove_board(SERIAL_B)
    # The panel goes after its missing polls, then the reload starts the polls of the site.
    for _ in range(2 * BOARD_REMOVAL_POLLS):
        await advance(hass, freezer, DISCOVERY)

    assert site_device(device_registry, config_entry, "site-1") is None
    assert board_device(device_registry, config_entry, SERIAL_A).via_device_id is None


async def test_site_device_kept_while_site_exists(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    share_site_1(fake_backend)
    await setup_integration(hass, config_entry)

    for _ in range(BOARD_REMOVAL_POLLS):
        await advance(hass, freezer, DISCOVERY)

    assert site_device(device_registry, config_entry, "site-1")


async def test_site_energy_on_site_with_two_panels(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    share_site_1(fake_backend)
    await setup_integration(hass, config_entry)

    entity_id = entity_registry.async_get_entity_id("sensor", DOMAIN, SITE_ENERGY_TODAY)
    assert hass.states.get(entity_id).state == "20.0"
    month_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, "basis_energy_month_import_site_site-1"
    )
    assert hass.states.get(month_id).state == "400.0"
    site = site_device(device_registry, config_entry, "site-1")
    assert entity_registry.async_get(entity_id).device_id == site.id


async def test_site_energy_unknown_without_data(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    share_site_1(fake_backend)
    fake_backend.site_energy["site-1"][TODAY_START] = None
    await setup_integration(hass, config_entry)

    entity_id = entity_registry.async_get_entity_id("sensor", DOMAIN, SITE_ENERGY_TODAY)
    assert hass.states.get(entity_id).state == STATE_UNKNOWN


async def test_no_site_energy_on_site_with_one_panel(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)

    assert not entity_registry.async_get_entity_id("sensor", DOMAIN, SITE_ENERGY_TODAY)


async def test_site_energy_removed_when_site_keeps_one_panel(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    share_site_1(fake_backend)
    await setup_integration(hass, config_entry)
    assert entity_registry.async_get_entity_id("sensor", DOMAIN, SITE_ENERGY_TODAY)

    fake_backend.remove_board(SERIAL_B)
    for _ in range(BOARD_REMOVAL_POLLS):
        await advance(hass, freezer, DISCOVERY)

    assert not entity_registry.async_get_entity_id("sensor", DOMAIN, SITE_ENERGY_TODAY)
    assert hass.states.get(power_entity(entity_registry, SERIAL_A, 1)).state == "120.5"


async def test_shared_site_has_one_owner(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    other_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await setup_integration(hass, config_entry)
    await setup_integration(hass, other_entry)

    assert "does not generate unique IDs" not in caplog.text
    assert not dr.async_entries_for_config_entry(device_registry, other_entry.entry_id)
    entity_id = power_entity(entity_registry, SERIAL_A, 1)
    assert entity_registry.async_get(entity_id).config_entry_id == config_entry.entry_id


async def test_other_account_takes_over_after_owner_unloads(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    other_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    await setup_integration(hass, other_entry)

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await advance(hass, freezer, DISCOVERY)

    entity_id = power_entity(entity_registry, SERIAL_A, 1)
    assert entity_registry.async_get(entity_id).config_entry_id == other_entry.entry_id
    assert hass.states.get(entity_id).state == "120.5"


async def test_device_of_site_owned_by_other_account_removed(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    other_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    await setup_integration(hass, other_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await advance(hass, freezer, DISCOVERY)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    for _ in range(BOARD_REMOVAL_POLLS):
        await advance(hass, freezer, DISCOVERY)

    assert board_device(device_registry, config_entry, SERIAL_A) is None
    assert board_device(device_registry, other_entry, SERIAL_A)
    assert hass.states.get(power_entity(entity_registry, SERIAL_A, 1)).state == "120.5"


@pytest.mark.parametrize("first_owner", [0, 1])
@pytest.mark.parametrize("restart_order", [(0, 1), (1, 0)])
async def test_shared_site_keeps_its_owner_after_a_restart(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    other_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    first_owner: int,
    restart_order: tuple[int, int],
) -> None:
    entries = (config_entry, other_entry)
    owner = entries[first_owner]
    await setup_integration(hass, owner)
    await setup_integration(hass, entries[1 - first_owner])
    connectivity = entity_registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"basis_connectivity_{SERIAL_A}"
    )
    device_id = entity_registry.async_get(connectivity).device_id

    for entry in entries:
        assert await hass.config_entries.async_unload(entry.entry_id)
    hass.set_state(CoreState.not_running)
    for index in restart_order:
        await hass.config_entries.async_setup(entries[index].entry_id)
    await hass.async_block_till_done()
    hass.set_state(CoreState.running)

    assert entity_registry.async_get(connectivity).config_entry_id == owner.entry_id
    assert entity_registry.async_get(connectivity).device_id == device_id
    assert hass.states.get(power_entity(entity_registry, SERIAL_A, 1)).state == "120.5"


async def test_panel_that_moves_to_another_site_goes_under_that_site(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    assert site_device(device_registry, config_entry, "site-1") is None

    share_site_1(fake_backend)
    await advance(hass, freezer, DISCOVERY)

    site = site_device(device_registry, config_entry, "site-1")
    assert site is not None
    assert board_device(device_registry, config_entry, SERIAL_B).via_device_id == site.id
