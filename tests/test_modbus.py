"""Reconnect and backoff transport regressions."""

from unittest.mock import patch

import pytest

from custom_components.solarbridge.modbus import (
    ModbusConnectionError,
    ReconnectBackoffActive,
    SolarBridgeModbusClient,
)


class SequenceExecutor:
    """Return or raise configured outcomes while recording real attempts."""

    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = 0

    async def __call__(self, _function, _ranges):
        self.calls += 1
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


async def test_exponential_backoff_boundary_retry_and_success_reset():
    executor = SequenceExecutor(
        [
            ModbusConnectionError("first"),
            ModbusConnectionError("second"),
            ModbusConnectionError("third"),
            {79: 1},
        ]
    )
    client = SolarBridgeModbusClient("deye.home", 502, 1, executor)
    now = 100.0

    with patch("custom_components.solarbridge.modbus.monotonic", side_effect=lambda: now):
        with pytest.raises(ModbusConnectionError, match="first"):
            await client.async_read([])
        assert (client._retry_at, client._backoff) == (101.0, 2.0)

        now = 101.0
        with pytest.raises(ModbusConnectionError, match="second"):
            await client.async_read([])
        assert (client._retry_at, client._backoff) == (103.0, 4.0)

        now = 103.0
        with pytest.raises(ModbusConnectionError, match="third"):
            await client.async_read([])
        assert (client._retry_at, client._backoff) == (107.0, 8.0)

        now = 107.0
        assert await client.async_read([]) == {79: 1}

    assert executor.calls == 4
    assert (client._retry_at, client._backoff) == (0.0, 1.0)


async def test_near_boundary_backoff_skips_executor_without_displaying_zero():
    executor = SequenceExecutor([ModbusConnectionError("offline"), {79: 1}])
    client = SolarBridgeModbusClient("deye.home", 502, 1, executor)
    now = 100.0

    with patch("custom_components.solarbridge.modbus.monotonic", side_effect=lambda: now):
        with pytest.raises(ModbusConnectionError, match="offline"):
            await client.async_read([])

        now = 100.96
        with pytest.raises(ReconnectBackoffActive) as raised:
            await client.async_read([])
        assert raised.value.remaining == pytest.approx(0.04)
        assert str(raised.value) == "Reconnect backoff active for 0.1s"
        assert "0.0s" not in str(raised.value)
        assert executor.calls == 1

        now = 101.0
        assert await client.async_read([]) == {79: 1}

    assert executor.calls == 2
