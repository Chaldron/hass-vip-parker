import base64

from aiohttp import ClientSession

from .const import APP_KEY, BASE_URL


class VipParkerError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class AuthError(VipParkerError):
    pass


def _is_unauth(status, error):
    return status == 401 or (isinstance(error, dict) and error.get("errorCode") == 4001)


class VipParkerApi:
    def __init__(self, session: ClientSession, access_token=None, refresh_token=None, on_tokens=None):
        self._session = session
        self.access_token = access_token
        self.refresh_token = refresh_token
        self._on_tokens = on_tokens
        self._app_key = base64.b64encode(APP_KEY.encode()).decode()  # login sends the key base64-encoded

    async def _call(self, method, path, *, body=None, auth=True, retry=True):
        headers = {"Accept-Language": "en-US"}
        if auth:
            headers["Authorization"] = f"Bearer {self.access_token}"
        else:
            headers["ApiKey"] = self._app_key
        async with self._session.request(method, BASE_URL + path, json=body, headers=headers) as resp:
            data = await resp.json(content_type=None)
            status = resp.status
        error = (data or {}).get("error")
        if auth and _is_unauth(status, error):
            if retry and self.refresh_token and await self.async_refresh():
                return await self._call(method, path, body=body, auth=auth, retry=False)
            raise AuthError("unauthorized")
        if error:
            raise VipParkerError(error.get("message"), error.get("errorCode"))
        return (data or {}).get("data")

    async def async_send_code(self, phone, country):
        await self._call(
            "POST", "Account/SendAuthorizationCode", auth=False,
            body={"phoneNumber": phone, "countryCode": country},
        )

    async def async_verify_code(self, phone, country, code):
        data = await self._call(
            "POST", "Account/VerifyAuthorizationCode", auth=False,
            body={
                "phoneNumber": phone, "countryCode": country, "authorizationCode": code,
                "cultureName": "en-US", "pushNotificationToken": "",
                "appVersion": "4.4.0", "osVersion": "15", "osType": 2,
            },
        )
        token = data["jwtToken"]
        self.access_token = token["accessToken"]
        self.refresh_token = token["refreshToken"]
        return data

    async def async_refresh(self):
        headers = {"Authorization": f"Bearer {self.refresh_token}"}
        async with self._session.post(BASE_URL + "Account/RefreshToken", headers=headers) as resp:
            data = await resp.json(content_type=None)
            status = resp.status
        token = (data or {}).get("data")
        if status < 400 and token and token.get("accessToken"):
            self.access_token = token["accessToken"]
            self.refresh_token = token.get("refreshToken", self.refresh_token)
            if self._on_tokens:
                self._on_tokens(self.access_token, self.refresh_token)
            return True
        return False

    async def async_get_cars(self):
        return await self._call("GET", "VipCar") or []

    async def async_request_car(self, car_id, area_id):
        # requestTime null = now; the immediate-request format is the one field not statically verified (see VIP_PARKER_API.md A.8)
        await self._call("POST", f"CarRequest/Add/{car_id}", body={"areaId": area_id, "requestTime": None})

    async def async_cancel_request(self, car_id):
        await self._call("DELETE", f"CarRequest/{car_id}")
