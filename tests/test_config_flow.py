"""Config flow regression tests."""

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from homeassistant import block_async_io, config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.loader import async_get_integration
from homeassistant.setup import async_setup_component
from modbus_connection import ModbusTcpParams
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solarbridge.config_flow import _probe
from custom_components.solarbridge.const import (
    CONF_POLL_INTERVAL,
    CONF_PROFILE,
    CONF_UNIT_ID,
    DOMAIN,
)

MANIFEST = Path(__file__).parents[1] / "custom_components" / DOMAIN / "manifest.json"

USER_INPUT = {
    CONF_HOST: "192.168.0.51",
    CONF_PORT: 502,
    CONF_UNIT_ID: 1,
    CONF_PROFILE: "deye_sg05lp1_eu_sm2_p.yaml",
    CONF_POLL_INTERVAL: 10,
}


def test_manifest_uses_home_assistant_modbus_connection():
    """Use Home Assistant's transport dependency instead of a private client."""
    manifest = json.loads(MANIFEST.read_text())

    assert manifest["dependencies"] == ["modbus"]
    assert "requirements" not in manifest


async def test_probe_uses_temporary_shared_modbus_unit(hass):
    """Release config-flow connections after probing the first fast range."""
    unit = AsyncMock()
    unit.read_holding_registers.return_value = [0]

    @asynccontextmanager
    async def temporary_unit(_hass, params, unit_id):
        assert (_hass, params, unit_id) == (
            hass,
            ModbusTcpParams(host=USER_INPUT[CONF_HOST], port=USER_INPUT[CONF_PORT]),
            USER_INPUT[CONF_UNIT_ID],
        )
        yield unit

    with patch("custom_components.solarbridge.config_flow.async_get_temporary_unit", temporary_unit):
        await _probe(hass, USER_INPUT)

    unit.read_holding_registers.assert_awaited_once_with(79, 1)
    unit.read_input_registers.assert_not_awaited()


async def test_user_config_flow_loads_and_creates_entry(hass):
    """Load the flow through HA's integration loader, then configure the gateway."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with (
        patch(
            "custom_components.solarbridge.config_flow._probe",
            new_callable=AsyncMock,
        ) as probe,
        patch(
            "custom_components.solarbridge.async_setup_entry",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=USER_INPUT,
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "SolarBridge 192.168.0.51"
    assert result["data"] == USER_INPUT
    probe.assert_awaited_once_with(hass, USER_INPUT)


async def test_config_flow_form_is_json_serializable(hass, hass_client):
    """Serve user and options forms through HA's real HTTP endpoints."""
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT)
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, "config", {})
    client = await hass_client()

    response = await client.post("/api/config/config_entries/flow", json={"handler": DOMAIN})

    assert response.status == 200
    result = await response.json()
    assert result["type"] == FlowResultType.FORM
    assert next(field for field in result["data_schema"] if field["name"] == CONF_HOST)["type"] == "string"

    response = await client.post(
        "/api/config/config_entries/options/flow", json={"handler": entry.entry_id}
    )

    assert response.status == 200
    result = await response.json()
    assert result["type"] == FlowResultType.FORM
    assert next(field for field in result["data_schema"] if field["name"] == CONF_HOST)["type"] == "string"


async def test_config_flow_profile_io_does_not_block_event_loop(hass, caplog, disable_block_async_io):
    """Keep profile directory scans and reads out of HA's event loop."""
    await async_get_integration(hass, DOMAIN)
    with patch.object(block_async_io, "_IN_TESTS", False):
        block_async_io.enable()
    caplog.set_level(logging.WARNING, logger="homeassistant.util.loop")

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    assert result["type"] is FlowResultType.FORM
    assert not [
        record
        for record in caplog.records
        if record.name == "homeassistant.util.loop" and "solarbridge" in record.getMessage()
    ]


async def test_invalid_host_is_rejected_before_probe(hass):
    """Validate host syntax in Python while keeping the form schema serializable."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    with patch("custom_components.solarbridge.config_flow._probe", new_callable=AsyncMock) as probe:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={**USER_INPUT, CONF_HOST: "not a valid host!"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_HOST: "invalid_host"}
    probe.assert_not_awaited()


async def test_options_flow_rejects_invalid_host(hass):
    """Apply the same nonblocking schema and host validation to options."""
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    with patch("custom_components.solarbridge.config_flow._probe", new_callable=AsyncMock) as probe:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                CONF_HOST: "bad host!",
                CONF_PORT: 502,
                CONF_POLL_INTERVAL: 10,
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_HOST: "invalid_host"}
    probe.assert_not_awaited()
