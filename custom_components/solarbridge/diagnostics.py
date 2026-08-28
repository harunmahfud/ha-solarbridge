"""Diagnostics for SolarBridge."""

from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data

from .const import DOMAIN

TO_REDACT = {"host", "serial", "inverter_id"}


async def async_get_config_entry_diagnostics(hass, entry):
    """Return useful state without network or device identifiers."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    return async_redact_data(
        {
            "entry": {"data": entry.data, "options": entry.options},
            "profile": {
                "key": runtime["profile"]["key"],
                "schema_version": runtime["profile"]["schema_version"],
                "sensor_count": len(runtime["profile"]["sensors"]),
            },
            "last_update_success": runtime["coordinator"].last_update_success,
            "data": runtime["coordinator"].data,
        },
        TO_REDACT,
    )
