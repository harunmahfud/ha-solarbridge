"""Tiered SolarBridge polling coordinator."""

from __future__ import annotations

import logging
from datetime import timedelta
from time import monotonic
from typing import Any

from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import FAILURE_THRESHOLD, SLOW_POLL_INTERVAL
from .decoder import decode_profile
from .modbus import ReconnectBackoffActive, SolarBridgeModbusClient
from .profile import read_ranges

_LOGGER = logging.getLogger(__name__)


class SolarBridgeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll fast data every cycle and slow data once a minute."""

    def __init__(self, hass, client: SolarBridgeModbusClient, profile: dict[str, Any], interval: int) -> None:
        super().__init__(
            hass, _LOGGER, name="SolarBridge", update_interval=timedelta(seconds=interval), always_update=False
        )
        self.client = client
        self.profile = profile
        self._slow_due = 0.0
        self._failures = 0
        self._deferred_while_unavailable = False

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
            self._failures = 0
            return data
        except ReconnectBackoffActive as err:
            _LOGGER.debug("SolarBridge poll deferred: %s", err)
            if self.data is None:
                raise ConfigEntryNotReady(str(err)) from err
            if not self.last_update_success:
                # HA treats returning cached data as recovery. Skip its recovery log,
                # then restore unavailability before it considers notifying listeners.
                self._deferred_while_unavailable = True
                self.last_update_success = True
            return self.data
        except Exception as err:
            self._failures += 1
            if self._failures >= FAILURE_THRESHOLD:
                raise UpdateFailed(f"Modbus polling failed {self._failures} consecutive times: {err}") from err
            if self.data is None:
                raise ConfigEntryNotReady(str(err)) from err
            _LOGGER.warning("SolarBridge poll failed (%s/%s): %s", self._failures, FAILURE_THRESHOLD, err)
            return self.data

    @callback
    def _async_refresh_finished(self) -> None:
        if self._deferred_while_unavailable:
            self._deferred_while_unavailable = False
            self.last_update_success = False
