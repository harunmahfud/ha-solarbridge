"""Coordinator freshness and reconnect-backoff regressions."""

import logging

from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryNotReady
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


async def test_failed_polls_and_backoff_preserve_data_until_a_real_recovery(hass, caplog):
    stale = {"battery_soc": 50}
    client = SequenceClient(
        [
            ModbusConnectionError("Unable to connect"),
            ReconnectBackoffActive(0.04),
            ModbusConnectionError("Still offline"),
            ModbusConnectionError("Third failure"),
            ReconnectBackoffActive(0.01),
            {184: 97},
            ModbusConnectionError("New failure streak"),
        ]
    )
    coordinator = make_coordinator(hass, client, stale)
    coordinator.profile["sensors"] = [{
        "key": "battery_soc", "address": 184, "data_type": "uint16",
        "scale": 1, "offset": 0, "polling_tier": "fast",
    }]
    caplog.set_level(logging.DEBUG, logger="custom_components.solarbridge.coordinator")
    notifications = []

    @callback
    def record_update():
        notifications.append((coordinator.last_update_success, coordinator.data))

    unsubscribe = coordinator.async_add_listener(record_update)
    try:
        for _ in range(3):  # Failure, deferred poll, failure.
            await coordinator.async_refresh()
            assert coordinator.last_update_success
            assert coordinator.data == stale
        assert not notifications
        assert "SolarBridge poll failed (1/3): Unable to connect" in caplog.messages
        assert "SolarBridge poll failed (2/3): Still offline" in caplog.messages
        assert "SolarBridge poll deferred: Reconnect backoff active for 0.1s" in caplog.messages

        await coordinator.async_refresh()
        assert not coordinator.last_update_success
        assert isinstance(coordinator.last_exception, UpdateFailed)
        assert notifications == [(False, stale)]

        failure = coordinator.last_exception
        await coordinator.async_refresh()
        assert not coordinator.last_update_success
        assert coordinator.last_exception is failure
        assert notifications == [(False, stale)]
        assert "Fetching SolarBridge data recovered" not in caplog.messages

        await coordinator.async_refresh()
        assert coordinator.last_update_success
        assert notifications == [(False, stale), (True, {"battery_soc": 97})]
        await coordinator.async_refresh()
        assert coordinator.last_update_success
        assert "SolarBridge poll failed (1/3): New failure streak" in caplog.messages
    finally:
        unsubscribe()


async def test_no_data_does_not_report_success(hass):
    client = SequenceClient([ModbusConnectionError("offline"), ReconnectBackoffActive(0.04)])
    coordinator = make_coordinator(hass, client, None)

    for _ in range(2):
        await coordinator.async_refresh()
        assert not coordinator.last_update_success
        assert coordinator.data is None
        assert isinstance(coordinator.last_exception, ConfigEntryNotReady)
