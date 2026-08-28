"""Validate every shipped profile."""

import json
from copy import deepcopy

import pytest

from custom_components.solarbridge.const import MAX_READ_REGISTERS, PROFILE_DIR
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
    assert not any("l2" in key or "gen_power" in key or "micro_inverter" in key for key in sensors)
    assert sensors["tou_time_1"]["data_type"] == "decimal_hhmm"
    assert sensors["tou_1_grid_charge"]["bitmask"] == 0b01
    assert sensors["tou_1_generator_charge"]["bitmask"] == 0b10


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
