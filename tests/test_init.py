"""SolarBridge setup wiring regressions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import entity_registry as er
from modbus_connection import ModbusTcpParams, ModbusTimeoutError
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
        203: 5544,
        204: 321,
        205: 4123,
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
    # No write methods: setup, refresh, and reload must work with a read-only unit.
    unit = SimpleNamespace(
        disconnect=AsyncMock(),
        read_holding_registers=AsyncMock(
            side_effect=lambda start, count: [raw.get(i, 0) for i in range(start, start + count)]
        ),
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
        assert state("battery_capacity").state == "321"
        assert state("battery_capacity").attributes["unit_of_measurement"] == "Ah"
        assert "device_class" not in state("battery_capacity").attributes
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

        # External/cloud changes must appear on the very next poll, not a cached minute later.
        raw.update({204: 875, 220: 4537, 221: 5183, 222: 4879})
        for slot in range(1, 7):
            raw[249 + slot] = slot * 300 + 17
            raw[255 + slot] = slot * 401
            raw[261 + slot] = 5400 + slot * 13
            raw[273 + slot] = slot % 4
        unchanged = dict(raw)
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert state("battery_capacity").state == "875"
        assert state("battery_shutdown_voltage").state == "45.37"
        assert state("battery_restart_voltage").state == "51.83"
        assert state("battery_low_voltage").state == "48.79"
        for slot, voltage in enumerate(["54.13", "54.26", "54.39", "54.52", "54.65", "54.78"], 1):
            assert state(f"tou_time_{slot}").state == f"{slot * 3:02d}:17"
            assert state(f"tou_power_{slot}").state == str(slot * 401)
            assert state(f"tou_voltage_{slot}").state == voltage
            assert state(f"tou_{slot}_grid_charge").state == ("Enabled" if slot % 2 else "Disabled")
            assert state(f"tou_{slot}_generator_charge").state == ("Enabled" if slot % 4 >= 2 else "Disabled")
        assert raw == unchanged

        # Chemistry and control basis are independent settings.
        raw.update({200: 0, 213: 1, 268: 97, 269: 89, 270: 81, 271: 73, 272: 65, 273: 57})
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert state("battery_type").state == "Lead-acid"
        assert state("battery_mode").state == "Capacity"
        assert state("battery_capacity").state == "875"
        assert state("battery_soc").state == "87"
        assert state("battery_soc").attributes["unit_of_measurement"] == "%"
        assert state("battery_voltage").attributes["battery_mode"] == "Capacity"
        for key, value in {"shutdown": "13", "restart": "27", "low": "21"}.items():
            assert state(f"battery_{key}_soc").state == value
            assert state(f"battery_{key}_voltage").state == "unavailable"
        for slot, value in enumerate(["97", "89", "81", "73", "65", "57"], 1):
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

        # Keep the last good settings for two failed polls (each exhausting its retry).
        unit.read_holding_registers.side_effect = ModbusTimeoutError("offline")
        with patch("custom_components.solarbridge.modbus.monotonic", return_value=100.0) as clock:
            for now in (100.0, 101.0, 103.0):
                clock.return_value = now
                await coordinator.async_refresh()
                if now < 103.0:
                    assert state("battery_mode").state == "99"
                    assert state("tou_time_1").state == "03:17"
            assert state("battery_mode").state == "unavailable"
            # An immediate refresh is deferred and cannot make stale settings available again.
            await coordinator.async_refresh()
        assert state("battery_voltage").state == "unavailable"
        assert "battery_mode" not in state("battery_voltage").attributes
        assert "battery_type" not in state("battery_voltage").attributes
        assert state("battery_mode").state == "unavailable"
        assert state("tou_time_1").state == "unavailable"
        assert state("battery_capacity").state == "unavailable"
        raw.update({204: 1200, 213: 0, 262: 5789})
        unit.read_holding_registers.side_effect = lambda start, count: [
            raw.get(i, 0) for i in range(start, start + count)
        ]
        # A fresh setup must read externally changed values, never restore previous settings.
        unchanged = dict(raw)
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert state("battery_mode").state == "Voltage"
        assert state("battery_capacity").state == "1200"
        assert state("tou_voltage_1").state == "57.89"
        assert raw == unchanged
        assert await hass.config_entries.async_unload(entry.entry_id)
