"""Coordinator failure-threshold and reconnect-backoff regressions."""

import logging

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.solarbridge.const import FAILURE_THRESHOLD
from custom_components.solarbridge.coordinator import SolarBridgeCoordinator
from custom_components.solarbridge.modbus import ModbusConnectionError, ReconnectBackoffActive


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


async def test_backoff_skips_preserve_data_without_counting_or_warning(hass, caplog):
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

    assert await coordinator._async_update_data() is stale
    assert coordinator._failures == 1

    assert await coordinator._async_update_data() is stale
    assert await coordinator._async_update_data() is stale
    assert coordinator._failures == 1

    assert await coordinator._async_update_data() is stale
    assert coordinator._failures == 2
    warnings = [record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING]
    assert warnings == [
        "SolarBridge poll failed (1/3): Unable to connect",
        "SolarBridge poll failed (2/3): Still offline",
    ]
    assert "SolarBridge poll deferred: Reconnect backoff active for 0.1s" in caplog.messages
    assert not any("0.0s" in message for message in caplog.messages)


async def test_third_genuine_failure_marks_update_failed(hass):
    client = SequenceClient([ModbusConnectionError(f"failure {number}") for number in range(1, 4)])
    coordinator = make_coordinator(hass, client, {"last": "good"})

    assert await coordinator._async_update_data() == {"last": "good"}
    assert await coordinator._async_update_data() == {"last": "good"}
    with pytest.raises(UpdateFailed, match="3 consecutive times: failure 3"):
        await coordinator._async_update_data()

    assert coordinator._failures == FAILURE_THRESHOLD
    assert client.calls == FAILURE_THRESHOLD


async def test_success_after_failure_resets_counter(hass):
    client = SequenceClient([ModbusConnectionError("transient"), {}])
    coordinator = make_coordinator(hass, client, {"last": "good"})

    assert await coordinator._async_update_data() == {"last": "good"}
    assert coordinator._failures == 1
    assert await coordinator._async_update_data() == {"last": "good"}
    assert coordinator._failures == 0


async def test_no_data_backoff_uses_retry_after_without_counting(hass, caplog):
    client = SequenceClient([ReconnectBackoffActive(0.04)])
    coordinator = make_coordinator(hass, client, None)
    caplog.set_level(logging.WARNING, logger="custom_components.solarbridge.coordinator")

    with pytest.raises(UpdateFailed, match="Modbus polling deferred") as raised:
        await coordinator._async_update_data()

    assert raised.value.retry_after == pytest.approx(0.04)
    assert coordinator._failures == 0
    assert not caplog.records
