"""Profile loading and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .const import MAX_READ_REGISTERS, PROFILE_DIR

SUPPORTED_TYPES = {"uint16", "int16", "uint32", "string", "decimal_hhmm"}
SUPPORTED_FUNCTIONS = {3, 4}
SUPPORTED_TIERS = {"fast", "slow"}


class ProfileError(ValueError):
    """Raised for an invalid profile."""


@dataclass(frozen=True)
class ReadRange:
    """A contiguous Modbus read."""

    start: int
    count: int
    function: int
    tier: str


def available_profiles(directory: Path = PROFILE_DIR) -> dict[str, str]:
    """Return profile filenames and display names."""
    profiles: dict[str, str] = {}
    for path in sorted(directory.glob("*.yaml")):
        try:
            profile = load_profile(path.name, directory)
            profiles[path.name] = profile["name"]
        except ProfileError:
            continue
    return profiles


async def async_available_profiles(
    hass: HomeAssistant, directory: Path = PROFILE_DIR
) -> dict[str, str]:
    """Return profiles without blocking the event loop on file I/O."""
    return await hass.async_add_executor_job(available_profiles, directory)


def load_profile(filename: str, directory: Path = PROFILE_DIR) -> dict[str, Any]:
    """Load a JSON-compatible YAML profile without a runtime YAML dependency."""
    if Path(filename).name != filename or not filename.endswith(".yaml"):
        raise ProfileError("Invalid profile filename")
    path = directory / filename
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise ProfileError(f"Unable to load profile {filename}: {err}") from err
    validate_profile(profile)
    return profile


async def async_load_profile(
    hass: HomeAssistant, filename: str, directory: Path = PROFILE_DIR
) -> dict[str, Any]:
    """Load a profile without blocking the event loop on file I/O."""
    return await hass.async_add_executor_job(load_profile, filename, directory)


def read_ranges(profile: dict[str, Any], tier: str) -> list[ReadRange]:
    """Return typed ranges for a polling tier."""
    return [ReadRange(**item) for item in profile["ranges"] if item["tier"] == tier]


def validate_profile(profile: dict[str, Any]) -> None:
    """Validate the complete profile contract and range coverage."""
    if profile.get("schema_version") != 1:
        raise ProfileError("schema_version must be 1")
    for key in ("key", "name", "manufacturer", "model", "ranges", "sensors"):
        if key not in profile:
            raise ProfileError(f"Missing required key: {key}")
    if not isinstance(profile["ranges"], list) or not profile["ranges"]:
        raise ProfileError("ranges must be a non-empty list")

    coverage: dict[tuple[int, int], set[str]] = {}
    for item in profile["ranges"]:
        if set(item) != {"start", "count", "function", "tier"}:
            raise ProfileError("Each range requires start, count, function, and tier")
        start, count = item["start"], item["count"]
        if not isinstance(start, int) or start < 0:
            raise ProfileError("Range start must be a non-negative integer")
        if not isinstance(count, int) or not 1 <= count <= MAX_READ_REGISTERS:
            raise ProfileError(f"Range count must be 1..{MAX_READ_REGISTERS}")
        if item["function"] not in SUPPORTED_FUNCTIONS:
            raise ProfileError("Only FC03 and FC04 are supported")
        if item["tier"] not in SUPPORTED_TIERS:
            raise ProfileError("Range tier must be fast or slow")
        for address in range(start, start + count):
            coverage.setdefault((item["function"], address), set()).add(item["tier"])

    seen: set[str] = set()
    for sensor in profile["sensors"]:
        required = {"key", "name", "address", "function", "data_type", "scale", "offset", "word_order", "polling_tier"}
        missing = required - sensor.keys()
        if missing:
            raise ProfileError(f"Sensor is missing keys: {', '.join(sorted(missing))}")
        if sensor["key"] in seen:
            raise ProfileError(f"Duplicate sensor key: {sensor['key']}")
        seen.add(sensor["key"])
        if sensor["data_type"] not in SUPPORTED_TYPES:
            raise ProfileError(f"Unsupported data_type: {sensor['data_type']}")
        if sensor["function"] not in SUPPORTED_FUNCTIONS:
            raise ProfileError("Sensor function must be 3 or 4")
        if sensor["polling_tier"] not in SUPPORTED_TIERS:
            raise ProfileError("Sensor polling_tier must be fast or slow")
        if sensor["word_order"] not in {"low_high", "high_low"}:
            raise ProfileError("word_order must be low_high or high_low")
        register_count = sensor.get("register_count", 2 if sensor["data_type"] == "uint32" else 1)
        addresses = sensor.get("addresses", range(sensor["address"], sensor["address"] + register_count))
        if len(addresses) != register_count:
            raise ProfileError(f"{sensor['key']} address count does not match its data type")
        for address in addresses:
            if sensor["polling_tier"] not in coverage.get((sensor["function"], address), set()):
                raise ProfileError(f"{sensor['key']} register {address} is not covered by its polling tier")
