from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, STATUS_LABELS


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(VipParkerStatusSensor(coordinator, vip_car_id) for vip_car_id in coordinator.data)


class VipParkerStatusSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "request_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(STATUS_LABELS.values())

    def __init__(self, coordinator, vip_car_id):
        super().__init__(coordinator)
        self._id = vip_car_id
        car = coordinator.data[vip_car_id]
        self._attr_unique_id = f"{vip_car_id}_status"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(vip_car_id))},
            name=car.get("description") or f"Vehicle {vip_car_id}",
            manufacturer=car.get("make"),
        )

    @property
    def _car(self):
        return self.coordinator.data.get(self._id)

    @property
    def available(self):
        return super().available and self._car is not None

    @property
    def native_value(self):
        return STATUS_LABELS.get(self._car["requestStatus"]) if self._car else None

    @property
    def extra_state_attributes(self):
        car = self._car or {}
        return {
            "car_id": car.get("carId"),
            "location": car.get("locationName"),
            "ticket": car.get("ticketNumber"),
            "area_id": car.get("areaId"),
        }
