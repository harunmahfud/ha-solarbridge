"""Shared Modbus unit and reconnect-backoff regressions."""

from unittest.mock import AsyncMock, patch

import pytest
from modbus_connection import ModbusConnectionError, ModbusTimeoutError

from custom_components.solarbridge.modbus import ReconnectBackoffActive, SolarBridgeModbusClient
from custom_components.solarbridge.profile import ReadRange


class SequenceUnit:
    """Return or raise configured outcomes while recording unit operations."""

    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = []
        self.disconnect = AsyncMock()

    async def _read(self, function, address, count):
        self.calls.append((function, address, count))
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def read_holding_registers(self, address, count):
        return await self._read(3, address, count)

    async def read_input_registers(self, address, count):
        return await self._read(4, address, count)


RANGE = ReadRange(start=79, count=1, function=3, tier="fast")


async def test_reads_holding_and_input_ranges_from_shared_unit():
    unit = SequenceUnit([[10, 11], [20]])
    client = SolarBridgeModbusClient(unit)

    values = await client.async_read(
        [
            ReadRange(start=100, count=2, function=3, tier="fast"),
            ReadRange(start=200, count=1, function=4, tier="fast"),
        ]
    )

    assert values == {100: 10, 101: 11, 200: 20}
    assert unit.calls == [(3, 100, 2), (4, 200, 1)]


async def test_exponential_backoff_boundary_retry_and_success_reset():
    unit = SequenceUnit(
        [
            ModbusConnectionError("first"),
            ModbusConnectionError("second"),
            ModbusConnectionError("third"),
            [1],
        ]
    )
    client = SolarBridgeModbusClient(unit)
    now = 100.0

    with patch("custom_components.solarbridge.modbus.monotonic", side_effect=lambda: now):
        with pytest.raises(ModbusConnectionError, match="first"):
            await client.async_read([RANGE])
        assert (client._retry_at, client._backoff) == (101.0, 2.0)

        now = 101.0
        with pytest.raises(ModbusConnectionError, match="second"):
            await client.async_read([RANGE])
        assert (client._retry_at, client._backoff) == (103.0, 4.0)

        now = 103.0
        with pytest.raises(ModbusConnectionError, match="third"):
            await client.async_read([RANGE])
        assert (client._retry_at, client._backoff) == (107.0, 8.0)

        now = 107.0
        assert await client.async_read([RANGE]) == {79: 1}

    assert len(unit.calls) == 4
    assert (client._retry_at, client._backoff) == (0.0, 1.0)


async def test_near_boundary_backoff_skips_unit_without_displaying_zero():
    unit = SequenceUnit([ModbusConnectionError("offline"), [1]])
    client = SolarBridgeModbusClient(unit)
    now = 100.0

    with patch("custom_components.solarbridge.modbus.monotonic", side_effect=lambda: now):
        with pytest.raises(ModbusConnectionError, match="offline"):
            await client.async_read([RANGE])

        now = 100.96
        with pytest.raises(ReconnectBackoffActive) as raised:
            await client.async_read([RANGE])
        assert raised.value.remaining == pytest.approx(0.04)
        assert str(raised.value) == "Reconnect backoff active for 0.1s"
        assert "0.0s" not in str(raised.value)
        assert len(unit.calls) == 1

        now = 101.0
        assert await client.async_read([RANGE]) == {79: 1}

    assert len(unit.calls) == 2


async def test_third_consecutive_timeout_disconnects_wedged_shared_connection():
    unit = SequenceUnit([ModbusTimeoutError("timeout") for _ in range(3)])
    client = SolarBridgeModbusClient(unit)
    now = 100.0

    with patch("custom_components.solarbridge.modbus.monotonic", side_effect=lambda: now):
        for retry_at in (101.0, 103.0, 107.0):
            with pytest.raises(ModbusTimeoutError):
                await client.async_read([RANGE])
            now = retry_at

    unit.disconnect.assert_awaited_once_with()


async def test_success_resets_timeout_disconnect_threshold():
    unit = SequenceUnit(
        [
            ModbusTimeoutError("first"),
            ModbusTimeoutError("second"),
            [1],
            ModbusTimeoutError("third"),
        ]
    )
    client = SolarBridgeModbusClient(unit)
    now = 100.0

    with patch("custom_components.solarbridge.modbus.monotonic", side_effect=lambda: now):
        for retry_at in (101.0, 103.0):
            with pytest.raises(ModbusTimeoutError):
                await client.async_read([RANGE])
            now = retry_at
        assert await client.async_read([RANGE]) == {79: 1}
        with pytest.raises(ModbusTimeoutError):
            await client.async_read([RANGE])

    unit.disconnect.assert_not_awaited()
