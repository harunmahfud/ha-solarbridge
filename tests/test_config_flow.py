"""Config flow regression tests."""

import json
from importlib.metadata import version
from pathlib import Path
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.data_entry_flow import FlowResultType
from packaging.requirements import Requirement

from custom_components.solarbridge.const import (
    CONF_POLL_INTERVAL,
    CONF_PROFILE,
    CONF_UNIT_ID,
    DOMAIN,
)

MANIFEST = Path(__file__).parents[1] / "custom_components" / DOMAIN / "manifest.json"


def test_pymodbus_requirement_accepts_home_assistant_version():
    """Do not conflict with the pymodbus version constrained by Home Assistant."""
    requirement = Requirement(json.loads(MANIFEST.read_text())["requirements"][0])

    assert version("pymodbus") in requirement.specifier


async def test_user_config_flow_loads_and_creates_entry(hass):
    """Load the flow through HA's integration loader, then configure the gateway."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    user_input = {
        CONF_HOST: "192.168.0.51",
        CONF_PORT: 502,
        CONF_UNIT_ID: 1,
        CONF_PROFILE: "deye_sg05lp1_eu_sm2_p.yaml",
        CONF_POLL_INTERVAL: 10,
    }
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
            user_input=user_input,
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "SolarBridge 192.168.0.51"
    assert result["data"] == user_input
    probe.assert_awaited_once_with(hass, user_input)
