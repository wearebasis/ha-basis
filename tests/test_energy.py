"""Tests for the energy values of the subcircuits."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.basis_smart_panel.const import (
    DOMAIN,
    ENERGY_STATS_UPDATE_INTERVAL,
)

from .conftest import POLL, advance, circuit_uid, setup_integration
from .fake_backend import SERIAL_A, TODAY_BUCKET, FakeBasisBackend

EARLIER_BUCKET = "2026-10-13T11:00:00Z"
# Sydney starts daylight saving time on 4 October 2026.
SYDNEY_TODAY_START = "2026-10-15T00:00:00+11:00"
SYDNEY_MONTH_START = "2026-10-01T00:00:00+10:00"


def import_energy_state(
    hass: HomeAssistant, entity_registry: er.EntityRegistry, number: int
) -> str:
    entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, circuit_uid("energy_import", SERIAL_A, number)
    )
    assert entity_id
    return hass.states.get(entity_id).state


async def test_import_energy_sums_all_day_buckets(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    fake_backend.subcircuit_energy[SERIAL_A]["SC-A01"] = [
        (EARLIER_BUCKET, 1.0),
        (TODAY_BUCKET, None),
        (TODAY_BUCKET, 0.5),
    ]
    await setup_integration(hass, config_entry)

    assert import_energy_state(hass, entity_registry, 1) == "1.5"


async def test_import_energy_unknown_without_data(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    fake_backend.subcircuit_energy[SERIAL_A]["SC-A01"] = [(TODAY_BUCKET, None)]
    await setup_integration(hass, config_entry)

    assert import_energy_state(hass, entity_registry, 1) == STATE_UNKNOWN


async def test_import_energy_name_follows_the_label(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, circuit_uid("energy_import", SERIAL_A, 1)
    )
    assert hass.states.get(entity_id).name == (
        f"01 · Lights · Basis Panel {SERIAL_A} Import Energy Today"
    )

    fake_backend.board(SERIAL_A)["subcircuits"][0]["config"]["label"] = "hwc"
    await advance(hass, freezer, ENERGY_STATS_UPDATE_INTERVAL + timedelta(seconds=1))

    state = hass.states.get(entity_id)
    assert state.name == f"01 · Hot Water Cylinder · Basis Panel {SERIAL_A} Import Energy Today"
    assert state.attributes["icon"] == "mdi:water-boiler"


async def test_energy_periods_start_at_midnight_of_the_site(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    fake_backend.site_details["site-1"]["timeZone"] = "Australia/Sydney"
    fake_backend.board_energy[SERIAL_A] = {
        SYDNEY_TODAY_START: {"importKwh": 4.0, "exportKwh": 1.0},
        SYDNEY_MONTH_START: {"importKwh": 90.0, "exportKwh": 30.0},
    }
    fake_backend.today_starts[SERIAL_A] = SYDNEY_TODAY_START
    await setup_integration(hass, config_entry)

    for key, value in (("energy_today_import", "4.0"), ("energy_month_import", "90.0")):
        entity_id = entity_registry.async_get_entity_id(
            "sensor", DOMAIN, f"basis_{key}_{SERIAL_A}"
        )
        assert hass.states.get(entity_id).state == value
    assert import_energy_state(hass, entity_registry, 1) == "1.2"


async def test_unknown_time_zone_of_the_site_uses_the_time_zone_of_ha(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_backend.site_details["site-1"]["timeZone"] = "Mars/Olympus_Mons"
    await setup_integration(hass, config_entry)

    assert any(
        record.levelno == logging.WARNING and "Mars/Olympus_Mons" in record.getMessage()
        for record in caplog.records
    )
    entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"basis_energy_today_import_{SERIAL_A}"
    )
    assert hass.states.get(entity_id).state == "12.5"


async def test_import_energy_name_follows_the_label_at_the_next_live_poll(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, circuit_uid("energy_import", SERIAL_A, 1)
    )

    fake_backend.board(SERIAL_A)["subcircuits"][0]["config"]["label"] = "hwc"
    await advance(hass, freezer, POLL)

    state = hass.states.get(entity_id)
    assert state.name == f"01 · Hot Water Cylinder · Basis Panel {SERIAL_A} Import Energy Today"
    assert state.attributes["icon"] == "mdi:water-boiler"

    reported = state.last_reported
    await advance(hass, freezer, POLL)
    assert hass.states.get(entity_id).last_reported == reported
