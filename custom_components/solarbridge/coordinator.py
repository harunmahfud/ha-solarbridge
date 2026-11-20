"""Tiered SolarBridge polling coordinator."""

from __future__ import annotations

import logging
from datetime import timedelta
from time import monotonic
from typing import Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import SLOW_POLL_INTERVAL
from .decoder import decode_profile
from .modbus import ReconnectBackoffActive, SolarBridgeModbusClient
from .profile import read_ranges

_LOGGER = logging.getLogger(__name__)


class SolarBridgeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll fast data every cycle and slow data once a minute."""

    def __init__(self, hass, client: SolarBridgeModbusClient, profile: dict[str, Any], interval: int) -> None:
        super().__init__(hass, _LOGGER, name="SolarBridge", update_interval=timedelta(seconds=interval))
        self.client = client
        self.profile = profile
        self._slow_due = 0.0

    async def _async_update_data(self) -> dict[str, Any]:
        tier = "slow" if monotonic() >= self._slow_due else None
        try:
            values = await self.client.async_read(read_ranges(self.profile, "fast"))
            data = dict(self.data or {})
            data.update(decode_profile(self.profile, values, "fast"))
            if tier:
                slow_values = await self.client.async_read(read_ranges(self.profile, "slow"))
                data.update(decode_profile(self.profile, slow_values, "slow"))
                self._slow_due = monotonic() + SLOW_POLL_INTERVAL
            return data
        except ReconnectBackoffActive as err:
            _LOGGER.debug("SolarBridge poll deferred: %s", err)
            raise UpdateFailed(f"Modbus polling deferred: {err}", retry_after=err.remaining) from err
        except Exception as err:
            # Returning cached data would mark the poll successful and hide external changes.
            raise UpdateFailed(f"Modbus polling failed: {err}") from err
