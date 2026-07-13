from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import VipParkerApi
from .const import DOMAIN
from .coordinator import VipParkerCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    def save_tokens(access, refresh):
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, "access_token": access, "refresh_token": refresh}
        )

    api = VipParkerApi(
        async_get_clientsession(hass),
        entry.data["access_token"],
        entry.data["refresh_token"],
        save_tokens,
    )
    coordinator = VipParkerCoordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
