import logging
from datetime import timedelta

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AuthError, VipParkerError
from .const import ACTIVE_STATUSES, DOMAIN, POLL_ACTIVE_SECONDS, POLL_IDLE_SECONDS

_LOGGER = logging.getLogger(__name__)


class VipParkerCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, api):
        super().__init__(
            hass, _LOGGER, name=DOMAIN,
            update_interval=timedelta(seconds=POLL_IDLE_SECONDS),
        )
        self.api = api

    async def _async_update_data(self):
        try:
            cars = await self.api.async_get_cars()
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
