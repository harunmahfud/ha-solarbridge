"""Decode raw Modbus values using a SolarBridge profile."""

from __future__ import annotations

from typing import Any


def decode_value(sensor: dict[str, Any], registers: dict[int, int]) -> Any:
    """Decode one sensor from all of its registers."""
    count = sensor.get("register_count", 2 if sensor["data_type"] == "uint32" else 1)
    addresses = sensor.get("addresses", range(sensor["address"], sensor["address"] + count))
    words = [registers[address] for address in addresses]
    data_type = sensor["data_type"]

    if data_type == "uint16":
        value: Any = words[0]
    elif data_type == "int16":
        value = words[0] - 65536 if words[0] >= 32768 else words[0]
    elif data_type == "uint32":
        first, second = words
        value = first + second * 65536 if sensor["word_order"] == "low_high" else first * 65536 + second
    elif data_type == "string":
        ordered = words if sensor["word_order"] == "high_low" else list(reversed(words))
        value = b"".join(word.to_bytes(2, "big") for word in ordered).decode("ascii", errors="ignore").strip("\x00 ")
    elif data_type == "decimal_hhmm":
        hours, minutes = divmod(words[0], 100)
        value = f"{hours:02d}:{minutes:02d}" if hours < 24 and minutes < 60 else "invalid"
    else:  # Profile validation prevents this.
        raise ValueError(f"Unsupported data type: {data_type}")

    if isinstance(value, int | float):
        if "bitmask" in sensor:
            value = (value & sensor["bitmask"]) >> sensor.get("bitshift", 0)
        value = (value + sensor["offset"]) * sensor["scale"]
        if isinstance(sensor["scale"], float):
            precision = len(str(sensor["scale"]).partition(".")[2].rstrip("0"))
            value = round(value, precision)
        lookup = sensor.get("lookup", {})
        if str(value) in lookup:
            return lookup[str(value)]
    return value


def decode_profile(profile: dict[str, Any], registers: dict[int, int], tier: str) -> dict[str, Any]:
    """Decode all available sensors in a tier."""
    decoded: dict[str, Any] = {}
    for sensor in profile["sensors"]:
        if sensor["polling_tier"] != tier:
            continue
        try:
            decoded[sensor["key"]] = decode_value(sensor, registers)
        except KeyError:
            continue
    return decoded
