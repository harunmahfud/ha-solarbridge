"""Validate every shipped profile."""

import json
from copy import deepcopy

import pytest

from custom_components.solarbridge.const import MAX_READ_REGISTERS, PROFILE_DIR
from custom_components.solarbridge.decoder import decode_value
from custom_components.solarbridge.profile import ProfileError, load_profile, validate_profile


@pytest.mark.parametrize("path", list(PROFILE_DIR.glob("*.yaml")))
def test_profile_schema_ranges_and_coverage(path):
    profile = load_profile(path.name)
    assert all(item["count"] <= MAX_READ_REGISTERS for item in profile["ranges"])
    ranges = {(item["start"], item["count"]) for item in profile["ranges"]}
    assert {(3, 110), (150, 100), (250, 30)} <= ranges


def test_sg05lp1_corrections_are_explicit():
    profile = load_profile("deye_sg05lp1_eu_sm2_p.yaml")
    sensors = {sensor["key"]: sensor for sensor in profile["sensors"]}
    assert sensors["total_production"]["word_order"] == "low_high"
    assert sensors["total_grid_bought"]["addresses"] == [78, 80]
    assert sensors["aux_port_power"]["data_type"] == "int16"
    assert sensors["aux_status_raw"]["entity_category"] == "diagnostic"
    inverter_voltage = sensors["inverter_output_voltage"]
    assert inverter_voltage["address"] == 154
    assert inverter_voltage["unit"] == "V"
    assert inverter_voltage["device_class"] == "voltage"
    assert inverter_voltage["state_class"] == "measurement"
    assert decode_value(inverter_voltage, {154: 2301}) == 230.1
    assert any(item["start"] <= 154 < item["start"] + item["count"] for item in profile["ranges"])
    assert not any("l2" in key or "gen_power" in key or "micro_inverter" in key for key in sensors)
    assert sensors["tou_time_1"]["data_type"] == "decimal_hhmm"
    assert sensors["tou_1_grid_charge"]["bitmask"] == 0b01
    assert sensors["tou_1_generator_charge"]["bitmask"] == 0b10


def test_sg05lp1_bms_block_matches_validated_registers():
    profile = load_profile("deye_sg05lp1_eu_sm2_p.yaml")
    sensors = {sensor["key"]: sensor for sensor in profile["sensors"]}
    raw = {312: 5170, 313: 0, 314: 80, 315: 85, 316: 36, 317: 4965, 318: 0xFFFF, 319: 1321}
    expected = {
        "bms_charging_voltage": (312, 51.7),
        "bms_discharge_voltage": (313, 0.0),
        "bms_charge_current_limit": (314, 80),
        "bms_discharge_current_limit": (315, 85),
        "bms_soc": (316, 36),
        "bms_voltage": (317, 49.65),
        "bms_current": (318, -1),
        "bms_temperature": (319, 32.1),
    }
    for key, (address, value) in expected.items():
        assert sensors[key]["address"] == address
        assert sensors[key]["polling_tier"] == "fast"
        assert decode_value(sensors[key], raw) == value


def test_documented_power_register_types_and_addresses():
    profile = load_profile("deye_sg05lp1_eu_sm2_p.yaml")
    sensors = {sensor["key"]: sensor for sensor in profile["sensors"]}
    expected = {
        "grid_power": (169, "int16"),
        "inverter_power": (173, "int16"),
        "load_power": (178, "uint16"),
        "pv1_power": (186, "uint16"),
        "pv2_power": (187, "uint16"),
        "battery_power": (190, "int16"),
        "battery_current": (191, "int16"),
    }
    for key, (address, data_type) in expected.items():
        assert sensors[key]["address"] == address
        assert sensors[key]["data_type"] == data_type


def test_uncovered_register_is_rejected():
    profile = load_profile("deye_sg05lp1_eu_sm2_p.yaml")
    invalid = deepcopy(profile)
    invalid["sensors"][0]["address"] = 999
    with pytest.raises(ProfileError, match="not covered"):
        validate_profile(invalid)


def test_every_entity_name_is_translated():
    profile = load_profile("deye_sg05lp1_eu_sm2_p.yaml")
    component = PROFILE_DIR.parents[1]
    strings = json.loads((component / "strings.json").read_text())["entity"]["sensor"]
    english = json.loads((component / "translations" / "en.json").read_text())["entity"]["sensor"]
    keys = {sensor["key"] for sensor in profile["sensors"]}
    assert keys <= strings.keys()
    assert keys <= english.keys()
