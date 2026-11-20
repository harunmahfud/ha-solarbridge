"""Coordinator freshness and reconnect-backoff regressions."""

import logging

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed
from modbus_connection import ModbusConnectionError

from custom_components.solarbridge.coordinator import SolarBridgeCoordinator
from custom_components.solarbridge.modbus import ReconnectBackoffActive


class SequenceClient:
    """Return or raise one configured outcome for each coordinator read."""

    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = 0

    async def async_read(self, _ranges):
        self.calls += 1
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_coordinator(hass, client, data):
    coordinator = SolarBridgeCoordinator(hass, client, {"ranges": [], "sensors": []}, interval=1)
    coordinator._slow_due = float("inf")
    coordinator.data = data
    return coordinator


async def test_failures_and_backoff_never_return_cached_data(hass, caplog):
    stale = {"battery_soc": 50}
    client = SequenceClient(
        [
            ModbusConnectionError("Unable to connect"),
            ReconnectBackoffActive(0.04),
            ReconnectBackoffActive(0.01),
            ModbusConnectionError("Still offline"),
        ]
    )
    coordinator = make_coordinator(hass, client, stale)
    caplog.set_level(logging.DEBUG, logger="custom_components.solarbridge.coordinator")

    for _ in range(4):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
    assert "SolarBridge poll deferred: Reconnect backoff active for 0.1s" in caplog.messages
    assert not any("0.0s" in message for message in caplog.messages)


async def test_first_genuine_failure_marks_update_failed(hass):
    client = SequenceClient([ModbusConnectionError("offline")])
    coordinator = make_coordinator(hass, client, {"last": "good"})

    with pytest.raises(UpdateFailed, match="Modbus polling failed: offline"):
        await coordinator._async_update_data()


async def test_success_after_failure_publishes_new_values(hass):
    client = SequenceClient([ModbusConnectionError("transient"), {184: 97}])
    coordinator = make_coordinator(hass, client, {"battery_soc": 50})
    coordinator.profile["sensors"] = [{
        "key": "battery_soc", "address": 184, "data_type": "uint16",
        "scale": 1, "offset": 0, "polling_tier": "fast",
    }]

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    assert await coordinator._async_update_data() == {"battery_soc": 97}


async def test_no_data_backoff_uses_retry_after(hass, caplog):
    client = SequenceClient([ReconnectBackoffActive(0.04)])
    coordinator = make_coordinator(hass, client, None)
    caplog.set_level(logging.WARNING, logger="custom_components.solarbridge.coordinator")

    with pytest.raises(UpdateFailed, match="Modbus polling deferred") as raised:
        await coordinator._async_update_data()

    assert raised.value.retry_after == pytest.approx(0.04)
    assert not caplog.records
