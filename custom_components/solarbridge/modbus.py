"""Serialized, reconnecting Modbus TCP transport."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from math import ceil
from time import monotonic
from typing import Any

from pymodbus.client import ModbusTcpClient

from .profile import ReadRange

_LOGGER = logging.getLogger(__name__)


class ModbusConnectionError(Exception):
    """Transport connection failed."""


class ReconnectBackoffActive(ModbusConnectionError):
    """A read was deferred until the reconnect backoff expires."""

    def __init__(self, remaining: float) -> None:
        self.remaining = remaining
        displayed = ceil(remaining * 10) / 10
        super().__init__(f"Reconnect backoff active for {displayed:.1f}s")


class ModbusResponseError(Exception):
    """The server returned an invalid Modbus response."""


class SolarBridgeModbusClient:
    """One serial execution lane and reconnect state per inverter."""

    def __init__(self, host: str, port: int, unit_id: int, executor: Callable[..., Any]) -> None:
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self._executor = executor
        self._lock = asyncio.Lock()
        self._backoff = 1.0
        self._retry_at = 0.0

    async def async_read(self, ranges: list[ReadRange]) -> dict[int, int]:
        """Read ranges serially; a new client means DNS is resolved on every reconnect."""
        async with self._lock:
            remaining = self._retry_at - monotonic()
            if remaining > 0:
                raise ReconnectBackoffActive(remaining)
            try:
                values = await self._executor(self._read_sync, ranges)
            except Exception:
                self._retry_at = monotonic() + self._backoff
                self._backoff = min(self._backoff * 2, 60.0)
                raise
            self._backoff = 1.0
            self._retry_at = 0.0
            return values

    def _read_sync(self, ranges: list[ReadRange]) -> dict[int, int]:
        client = ModbusTcpClient(host=self.host, port=self.port, timeout=5)
        if not client.connect():
            client.close()
            raise ModbusConnectionError(f"Unable to connect to {self.host}:{self.port}")
        values: dict[int, int] = {}
        try:
            for request in ranges:
                method = client.read_holding_registers if request.function == 3 else client.read_input_registers
                id_keyword = "device_id" if "device_id" in inspect.signature(method).parameters else "slave"
                response = method(request.start, count=request.count, **{id_keyword: self.unit_id})
                if response.isError() or len(getattr(response, "registers", [])) != request.count:
                    raise ModbusResponseError(
                        f"Unit {self.unit_id} rejected FC{request.function:02d} registers "
                        f"{request.start}-{request.start + request.count - 1}: {response}"
                    )
                _LOGGER.debug(
                    "FC%02d unit=%s range=%s-%s raw=%s",
                    request.function,
                    self.unit_id,
                    request.start,
                    request.start + request.count - 1,
                    response.registers,
                )
                values.update({request.start + offset: value for offset, value in enumerate(response.registers)})
        finally:
            client.close()
        return values
