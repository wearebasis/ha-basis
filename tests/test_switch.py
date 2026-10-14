"""Tests for the circuit standby switches."""

from __future__ import annotations

import pytest
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF, SERVICE_TURN_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.basis_smart_panel.const import DOMAIN

from .conftest import setup_integration
from .fake_backend import SERIAL_A, FakeBasisBackend


@pytest.mark.parametrize(
    ("service", "activate_standby"),
    [(SERVICE_TURN_OFF, True), (SERVICE_TURN_ON, False)],
)
async def test_switch_sends_standby_command(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    service: str,
    activate_standby: bool,
) -> None:
    await setup_integration(hass, config_entry)
    entity_id = entity_registry.async_get_entity_id(
        SWITCH_DOMAIN, DOMAIN, f"basis_switch_{SERIAL_A}_SC-A01"
    )

    await hass.services.async_call(
        SWITCH_DOMAIN, service, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )

    assert fake_backend.standby_calls == [
        {
            "switchboardSerial": SERIAL_A,
            "subcircuitSerial": "SC-A01",
            "activateStandby": activate_standby,
        }
    ]


@pytest.mark.parametrize("serial", ["SC-A03", "SC-A04"])
async def test_no_switch_for_locked_or_spare_circuit(
    hass: HomeAssistant,
    fake_backend: FakeBasisBackend,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    serial: str,
) -> None:
    await setup_integration(hass, config_entry)
    assert entity_registry.async_get_entity_id(
        SWITCH_DOMAIN, DOMAIN, f"basis_switch_{SERIAL_A}_SC-A01"
    )
    assert not entity_registry.async_get_entity_id(
        SWITCH_DOMAIN, DOMAIN, f"basis_switch_{SERIAL_A}_{serial}"
    )
