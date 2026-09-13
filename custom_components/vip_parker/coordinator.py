import logging
from datetime import timedelta

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AuthError, VipParkerError
from .const import (
    ACTIVE_STATUSES,
    DEVICE_REGISTER_SECONDS,
    DOMAIN,
    POLL_ACTIVE_SECONDS,
    POLL_IDLE_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


class VipParkerCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, api):
        super().__init__(
            hass, _LOGGER, name=DOMAIN,
            update_interval=timedelta(seconds=POLL_IDLE_SECONDS),
        )
        self.api = api
        self._device_registered_at = None

    async def _async_update_data(self):
        try:
            cars = await self.api.async_get_cars()
            now = dt_util.utcnow()
            if (
                self._device_registered_at is None
                or (now - self._device_registered_at).total_seconds() >= DEVICE_REGISTER_SECONDS
            ):
                await self.api.async_register_device()
                self._device_registered_at = now
        except AuthError as err:
            raise ConfigEntryAuthFailed from err
        except VipParkerError as err:
            raise UpdateFailed(str(err)) from err
        data = {car["vipCarId"]: car for car in cars}
        # Poll fast only while a request is active; fall back to idle otherwise.
        # Button presses already force an immediate refresh, so requests made
        # from HA switch to the fast cadence right away.
        active = any(car.get("requestStatus") in ACTIVE_STATUSES for car in data.values())
        self.update_interval = timedelta(
            seconds=POLL_ACTIVE_SECONDS if active else POLL_IDLE_SECONDS
        )
        return data
