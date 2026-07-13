import logging
from datetime import timedelta

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AuthError, VipParkerError
from .const import DOMAIN, SCAN_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)


class VipParkerCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, api):
        super().__init__(
            hass, _LOGGER, name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.api = api

    async def _async_update_data(self):
        try:
            cars = await self.api.async_get_cars()
        except AuthError as err:
            raise ConfigEntryAuthFailed from err
        except VipParkerError as err:
            raise UpdateFailed(str(err)) from err
        return {car["vipCarId"]: car for car in cars}
