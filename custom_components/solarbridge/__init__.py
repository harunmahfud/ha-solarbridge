"""SolarBridge integration setup."""

from __future__ import annotations


async def async_setup_entry(hass, entry) -> bool:
    """Set up an inverter from a config entry."""
    from homeassistant.const import CONF_HOST, CONF_PORT

    from .const import CONF_POLL_INTERVAL, CONF_PROFILE, CONF_UNIT_ID, DOMAIN, PLATFORMS
    from .coordinator import SolarBridgeCoordinator
    from .modbus import SolarBridgeModbusClient
    from .profile import async_load_profile

    config = {**entry.data, **entry.options}
    profile = await async_load_profile(hass, config[CONF_PROFILE])
    client = SolarBridgeModbusClient(
        config[CONF_HOST], config[CONF_PORT], config[CONF_UNIT_ID], hass.async_add_executor_job
    )
    coordinator = SolarBridgeCoordinator(hass, client, profile, config[CONF_POLL_INTERVAL])
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coordinator, "profile": profile}
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry) -> bool:
    """Unload an inverter."""
    from .const import DOMAIN, PLATFORMS

    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        return True
    return False


async def _async_reload_entry(hass, entry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
