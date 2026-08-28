"""UI configuration for SolarBridge."""

from __future__ import annotations

import ipaddress
import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_POLL_INTERVAL,
    CONF_PROFILE,
    CONF_UNIT_ID,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_UNIT_ID,
    DOMAIN,
    MIN_POLL_INTERVAL,
)
from .modbus import ModbusConnectionError, ModbusResponseError, SolarBridgeModbusClient
from .profile import async_available_profiles, async_load_profile, read_ranges

_HOSTNAME = re.compile(
    r"^(?=.{1,253}\.?$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.?$"
)


def valid_host(value: str) -> str:
    """Accept an IPv4/IPv6 address or RFC-compatible hostname."""
    value = value.strip()
    try:
        ipaddress.ip_address(value)
    except ValueError:
        if not _HOSTNAME.fullmatch(value):
            raise vol.Invalid("Enter a valid IP address or hostname") from None
    return value


def _schema(
    defaults: dict[str, Any], profiles: dict[str, str], include_unit_profile: bool = True
) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): cv.string,
        vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
    }
    if include_unit_profile:
        fields[vol.Required(CONF_UNIT_ID, default=defaults.get(CONF_UNIT_ID, DEFAULT_UNIT_ID))] = vol.All(
            vol.Coerce(int), vol.Range(min=0, max=247)
        )
        fields[vol.Required(CONF_PROFILE, default=defaults.get(CONF_PROFILE, next(iter(profiles))))] = vol.In(profiles)
    fields[vol.Required(CONF_POLL_INTERVAL, default=defaults.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))] = vol.All(
        vol.Coerce(int), vol.Range(min=MIN_POLL_INTERVAL)
    )
    return vol.Schema(fields)


async def _async_schema(
    hass, defaults: dict[str, Any], include_unit_profile: bool = True
) -> vol.Schema:
    """Build a form schema without reading profiles on the event loop."""
    profiles = await async_available_profiles(hass) if include_unit_profile else {}
    return _schema(defaults, profiles, include_unit_profile)


async def _probe(hass, values: dict[str, Any]) -> None:
    profile = await async_load_profile(hass, values[CONF_PROFILE])
    client = SolarBridgeModbusClient(
        values[CONF_HOST], values[CONF_PORT], values[CONF_UNIT_ID], hass.async_add_executor_job
    )
    await client.async_read(read_ranges(profile, "fast")[:1])


class SolarBridgeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create SolarBridge config entries."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                user_input = {**user_input, CONF_HOST: valid_host(user_input[CONF_HOST])}
            except vol.Invalid:
                errors[CONF_HOST] = "invalid_host"
            if not errors:
                await self.async_set_unique_id(
                    f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}:{user_input[CONF_UNIT_ID]}"
                )
                self._abort_if_unique_id_configured()
                try:
                    await _probe(self.hass, user_input)
                except ModbusConnectionError:
                    errors["base"] = "cannot_connect"
                except ModbusResponseError:
                    errors["base"] = "invalid_unit_or_profile"
                except Exception:
                    errors["base"] = "unknown"
                else:
                    return self.async_create_entry(title=f"SolarBridge {user_input[CONF_HOST]}", data=user_input)
        return self.async_show_form(
            step_id="user", data_schema=await _async_schema(self.hass, user_input or {}), errors=errors
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return SolarBridgeOptionsFlow(config_entry)


class SolarBridgeOptionsFlow(config_entries.OptionsFlow):
    """Edit networking and polling settings."""

    def __init__(self, entry) -> None:
        self.entry = entry

    async def async_step_init(self, user_input=None):
        errors: dict[str, str] = {}
        defaults = {**self.entry.data, **self.entry.options}
        if user_input is not None:
            try:
                user_input = {**user_input, CONF_HOST: valid_host(user_input[CONF_HOST])}
            except vol.Invalid:
                errors[CONF_HOST] = "invalid_host"
            if not errors:
                probe_values = {**defaults, **user_input}
                try:
                    await _probe(self.hass, probe_values)
                except ModbusConnectionError:
                    errors["base"] = "cannot_connect"
                except ModbusResponseError:
                    errors["base"] = "invalid_unit_or_profile"
                except Exception:
                    errors["base"] = "unknown"
                else:
                    return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=await _async_schema(self.hass, defaults, include_unit_profile=False),
            errors=errors,
        )
