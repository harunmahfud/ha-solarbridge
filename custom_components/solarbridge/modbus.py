"""SolarBridge reads over a Home Assistant-managed Modbus unit."""

from __future__ import annotations

import logging
from math import ceil
from time import monotonic

from modbus_connection import ModbusConnectionError, ModbusError, ModbusTimeoutError, ModbusUnit

from .profile import ReadRange

_LOGGER = logging.getLogger(__name__)


class ReconnectBackoffActive(ModbusConnectionError):
    """A read was deferred until the reconnect backoff expires."""

    def __init__(self, remaining: float) -> None:
        self.remaining = remaining
        displayed = ceil(remaining * 10) / 10
        super().__init__(f"Reconnect backoff active for {displayed:.1f}s")


class SolarBridgeModbusClient:
    """Read SolarBridge ranges with reconnect throttling."""

    def __init__(self, unit: ModbusUnit) -> None:
        self._unit = unit
        self._backoff = 1.0
        self._retry_at = 0.0
        self._timeouts = 0

    async def async_read(self, ranges: list[ReadRange]) -> dict[int, int]:
        """Read ranges serially over Home Assistant's shared connection."""
        remaining = self._retry_at - monotonic()
        if remaining > 0:
            raise ReconnectBackoffActive(remaining)
        values: dict[int, int] = {}
        try:
            for request in ranges:
                method = (
                    self._unit.read_holding_registers
                    if request.function == 3
                    else self._unit.read_input_registers
                )
                registers = await method(request.start, request.count)
                _LOGGER.debug(
                    "FC%02d range=%s-%s raw=%s",
                    request.function,
                    request.start,
                    request.start + request.count - 1,
                    registers,
                )
                values.update({request.start + offset: value for offset, value in enumerate(registers)})
        except ModbusError as err:
            self._retry_at = monotonic() + self._backoff
            self._backoff = min(self._backoff * 2, 60.0)
            if isinstance(err, ModbusTimeoutError):
                self._timeouts += 1
                if self._timeouts >= 3:
                    await self._unit.disconnect()
            else:
                self._timeouts = 0
            raise
        self._backoff = 1.0
        self._retry_at = 0.0
        self._timeouts = 0
        return values
