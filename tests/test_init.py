"""SolarBridge setup wiring regressions."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import CONF_HOST, CONF_PORT
from modbus_connection import ModbusTcpParams
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solarbridge import async_setup_entry
from custom_components.solarbridge.const import (
    CONF_POLL_INTERVAL,
    CONF_PROFILE,
    CONF_UNIT_ID,
    DOMAIN,
    PLATFORMS,
)


async def test_setup_acquires_entry_owned_shared_modbus_unit(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: "deye.home",
            CONF_PORT: 502,
            CONF_UNIT_ID: 1,
            CONF_PROFILE: "deye_sg05lp1_eu_sm2_p.yaml",
            CONF_POLL_INTERVAL: 10,
        },
    )
    entry.add_to_hass(hass)
    unit = MagicMock()
    profile = {"key": "deye"}
    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()

    with (
        patch("homeassistant.components.modbus.async_get_unit", return_value=unit) as get_unit,
        patch("custom_components.solarbridge.profile.async_load_profile", AsyncMock(return_value=profile)),
        patch("custom_components.solarbridge.coordinator.SolarBridgeCoordinator", return_value=coordinator) as factory,
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()) as forward,
    ):
        assert await async_setup_entry(hass, entry)

    get_unit.assert_called_once_with(
        hass,
        entry,
        ModbusTcpParams(host="deye.home", port=502),
        1,
    )
    client = factory.call_args.args[1]
    assert client._unit is unit
    coordinator.async_config_entry_first_refresh.assert_awaited_once_with()
    forward.assert_awaited_once_with(entry, PLATFORMS)
    assert hass.data[DOMAIN][entry.entry_id] == {"coordinator": coordinator, "profile": profile}
