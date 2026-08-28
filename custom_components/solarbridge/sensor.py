"""SolarBridge sensors."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Create all profile sensors."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SolarBridgeSensor(runtime["coordinator"], entry, runtime["profile"], description)
        for description in runtime["profile"]["sensors"]
    )


class SolarBridgeSensor(CoordinatorEntity, SensorEntity):
    """A profile-defined inverter measurement."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, profile, description) -> None:
        super().__init__(coordinator)
        self._description = description
        self._attr_unique_id = f"{entry.entry_id}_{description['key']}"
        self._attr_translation_key = description["key"]
        self._attr_native_unit_of_measurement = description.get("unit")
        self._attr_device_class = description.get("device_class")
        self._attr_state_class = description.get("state_class")
        self._attr_icon = description.get("icon")
        if description.get("entity_category") == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=profile["manufacturer"],
            model=profile["model"],
        )

    @property
    def native_value(self):
        return self.coordinator.data.get(self._description["key"])
