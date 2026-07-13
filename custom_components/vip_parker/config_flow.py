import voluptuous as vol

from homeassistant.config_entries import ConfigFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import VipParkerApi, VipParkerError
from .const import DOMAIN


class VipParkerConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _async_send_code(self, user_input):
        self._phone = user_input["phone"]
        self._country = user_input["country"]
        self._api = VipParkerApi(async_get_clientsession(self.hass))
        await self._api.async_send_code(self._phone, self._country)

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                await self._async_send_code(user_input)
            except VipParkerError:
                errors["base"] = "send_failed"
            else:
                return await self.async_step_code()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required("phone"): str, vol.Required("country", default="+1"): str}
            ),
            errors=errors,
        )

    async def async_step_code(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                data = await self._api.async_verify_code(self._phone, self._country, user_input["code"])
            except VipParkerError:
                errors["base"] = "invalid_code"
            else:
                await self.async_set_unique_id(str(data["vipId"]))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"VIP Parker ({self._phone})",
                    data={
                        "access_token": self._api.access_token,
                        "refresh_token": self._api.refresh_token,
                        "vip_id": data["vipId"],
                        "phone": self._phone,
                        "country": self._country,
                    },
                )
        return self.async_show_form(
            step_id="code",
            data_schema=vol.Schema({vol.Required("code"): str}),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                await self._async_send_code(user_input)
            except VipParkerError:
                errors["base"] = "send_failed"
            else:
                return await self.async_step_reauth_code()

        # entries created before the phone was stored have nothing to prefill
        entry_data = self._get_reauth_entry().data
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required("phone", default=entry_data.get("phone", "")): str,
                    vol.Required("country", default=entry_data.get("country", "+1")): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth_code(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                data = await self._api.async_verify_code(self._phone, self._country, user_input["code"])
            except VipParkerError:
                errors["base"] = "invalid_code"
            else:
                # signing in as a different VIP account would orphan every entity
                await self.async_set_unique_id(str(data["vipId"]))
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data_updates={
                        "access_token": self._api.access_token,
                        "refresh_token": self._api.refresh_token,
                        "phone": self._phone,
                        "country": self._country,
                    },
                )
        return self.async_show_form(
            step_id="reauth_code",
            data_schema=vol.Schema({vol.Required("code"): str}),
            errors=errors,
        )
