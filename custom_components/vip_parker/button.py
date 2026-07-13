from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for vip_car_id in coordinator.data:
        entities.append(VipParkerRequestButton(coordinator, vip_car_id))
        entities.append(VipParkerCancelButton(coordinator, vip_car_id))
    async_add_entities(entities)


class _VipParkerButton(CoordinatorEntity, ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, vip_car_id):
        super().__init__(coordinator)
        self._id = vip_car_id
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, str(vip_car_id))})

    @property
    def _car(self):
        return self.coordinator.data.get(self._id)

    @property
    def available(self):
        return super().available and self._car is not None


class VipParkerRequestButton(_VipParkerButton):
    _attr_name = "Request vehicle"
    _attr_icon = "mdi:car-arrow-left"

    def __init__(self, coordinator, vip_car_id):
        super().__init__(coordinator, vip_car_id)
        self._attr_unique_id = f"{vip_car_id}_request"

    async def async_press(self):
        car = self._car
        await self.coordinator.api.async_request_car(car["carId"], car["areaId"])
        await self.coordinator.async_request_refresh()


class VipParkerCancelButton(_VipParkerButton):
    _attr_name = "Cancel request"
    _attr_icon = "mdi:close-circle"

    def __init__(self, coordinator, vip_car_id):
        super().__init__(coordinator, vip_car_id)
        self._attr_unique_id = f"{vip_car_id}_cancel"

    async def async_press(self):
        await self.coordinator.api.async_cancel_request(self._car["carId"])
        await self.coordinator.async_request_refresh()
