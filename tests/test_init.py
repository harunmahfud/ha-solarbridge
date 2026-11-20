"""SolarBridge setup wiring regressions."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import entity_registry as er
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


async def test_battery_mode_selects_voltage_or_capacity_entities_live(hass):
    """Read real profile registers through setup and observe HA states, not chemistry guesses."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="SolarBridge",
        data={
            CONF_HOST: "deye.home",
            CONF_PORT: 502,
            CONF_UNIT_ID: 1,
            CONF_PROFILE: "deye_sg05lp1_eu_sm2_p.yaml",
            CONF_POLL_INTERVAL: 10,
        },
    )
    entry.add_to_hass(hass)
    raw = {
        183: 5127,
        184: 87,
        200: 1,
        213: 0,
        217: 13,
        218: 27,
        219: 21,
        220: 4431,
        221: 5052,
        222: 4763,
        261: 2222,
        262: 4831,
        263: 4942,
        264: 5053,
        265: 5164,
        266: 5275,
        267: 5386,
        268: 11,
        269: 22,
        270: 33,
        271: 44,
        272: 55,
        273: 66,
    }
    unit = MagicMock()
    unit.read_holding_registers = AsyncMock(
        side_effect=lambda start, count: [raw.get(i, 0) for i in range(start, start + count)]
    )
    registry = er.async_get(hass)

    def state(key):
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
        result = hass.states.get(entity_id)
        assert result is not None, key
        return result

    with patch("homeassistant.components.modbus.async_get_unit", return_value=unit):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
        assert state("battery_type").state == "Lithium"
        assert state("battery_mode").state == "Voltage"
        assert state("battery_voltage").state == "51.27"
        assert state("battery_voltage").attributes["battery_mode"] == "Voltage"
        assert state("battery_soc").state == "unavailable"
        for key, value in {"shutdown": "44.31", "restart": "50.52", "low": "47.63"}.items():
            assert state(f"battery_{key}_voltage").state == value
            assert state(f"battery_{key}_voltage").attributes["unit_of_measurement"] == "V"
            assert state(f"battery_{key}_soc").state == "unavailable"
        for slot, value in enumerate(["48.31", "49.42", "50.53", "51.64", "52.75", "53.86"], 1):
            assert state(f"tou_voltage_{slot}").state == value
            assert state(f"tou_soc_{slot}").state == "unavailable"

        # Chemistry and control basis are independent settings.
        raw.update({200: 0, 213: 1})
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert state("battery_type").state == "Lead-acid"
        assert state("battery_mode").state == "Capacity"
        assert state("battery_soc").state == "87"
        assert state("battery_soc").attributes["unit_of_measurement"] == "%"
        assert state("battery_voltage").attributes["battery_mode"] == "Capacity"
        for key, value in {"shutdown": "13", "restart": "27", "low": "21"}.items():
            assert state(f"battery_{key}_soc").state == value
            assert state(f"battery_{key}_voltage").state == "unavailable"
        for slot, value in enumerate(["11", "22", "33", "44", "55", "66"], 1):
            assert state(f"tou_soc_{slot}").state == value
            assert state(f"tou_voltage_{slot}").state == "unavailable"

        for mode in [2, 99]:
            raw[213] = mode
            await coordinator.async_refresh()
            await hass.async_block_till_done()
            assert state("battery_mode").state == ("No battery" if mode == 2 else "99")
            for key in [
                "battery_soc",
                "battery_shutdown_soc",
                "battery_shutdown_voltage",
                "tou_soc_1",
                "tou_voltage_1",
            ]:
                assert state(key).state == "unavailable"

        coordinator.async_set_update_error(RuntimeError("offline"))
        await hass.async_block_till_done()
        assert state("battery_voltage").state == "unavailable"
        assert state("battery_mode").state == "unavailable"
        assert await hass.config_entries.async_unload(entry.entry_id)
