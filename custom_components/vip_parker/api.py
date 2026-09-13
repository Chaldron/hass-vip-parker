import asyncio
import base64
import json

from aiohttp import ClientError, ClientSession

from .const import APP_KEY, BASE_URL, DEVICE_PROFILE


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
        self._refresh_lock = asyncio.Lock()

    async def _http(self, method, path, *, body=None, headers=None):
        """One HTTP round-trip with defensive JSON parsing.

        Returns (status, parsed_json_or_None). A non-JSON body (gateway or
        rate-limit page) yields data=None rather than raising; transport errors
        become a retryable VipParkerError instead of an unhandled crash.
        """
        try:
            async with self._session.request(method, BASE_URL + path, json=body, headers=headers or {}) as resp:
                status = resp.status
                text = await resp.text()
        except (ClientError, asyncio.TimeoutError) as err:
            raise VipParkerError(f"network error calling {path}: {err}") from err
        data = None
        if text:
            try:
                data = json.loads(text)
            except ValueError:
                data = None
        return status, data

    async def _call(self, method, path, *, body=None, auth=True, retry=True):
        headers = {"Accept-Language": "en-US"}
        if auth:
            headers["Authorization"] = f"Bearer {self.access_token}"
        else:
            headers["ApiKey"] = self._app_key
        status, data = await self._http(method, path, body=body, headers=headers)
        error = data.get("error") if isinstance(data, dict) else None

        if auth and _is_unauth(status, error):
            # Access token expired: refresh once, then retry once. A genuinely
            # dead refresh token surfaces as AuthError (-> reauth); a transient
            # refresh failure surfaces as VipParkerError (-> retry next cycle).
            if retry and self.refresh_token:
                await self._async_refresh()
                return await self._call(method, path, body=body, auth=auth, retry=False)
            raise AuthError("unauthorized")

        if error:
            raise VipParkerError(error.get("message"), error.get("errorCode"))
        if status >= 400:
            # 5xx, 429, or an unparseable error page: retryable, not a crash.
            raise VipParkerError(f"unexpected response from {path} (HTTP {status})")
        return data.get("data") if isinstance(data, dict) else None

    async def _async_refresh(self):
        """Renew the access token, single-flight.

        Returns True once a valid access token is in place. Raises AuthError if
        the refresh token itself is rejected (needs reauth) or VipParkerError on
        a transient failure (retry next cycle). The lock plus the token re-check
        keep two concurrent 401s from each spending the rotating refresh token --
        reusing an already-rotated token can make the server revoke the session.
        """
        token_before = self.access_token
        async with self._refresh_lock:
            if self.access_token != token_before:
                return True  # another caller already refreshed while we waited

            headers = {"Authorization": f"Bearer {self.refresh_token}"}
            status, data = await self._http("POST", "Account/RefreshToken", headers=headers)
            token = data.get("data") if isinstance(data, dict) else None
            if status < 400 and token and token.get("accessToken"):
                self.access_token = token["accessToken"]
                self.refresh_token = token.get("refreshToken", self.refresh_token)
                if self._on_tokens:
                    self._on_tokens(self.access_token, self.refresh_token)
                return True

            error = data.get("error") if isinstance(data, dict) else None
            if _is_unauth(status, error):
                raise AuthError("refresh token rejected")
            raise VipParkerError(f"token refresh failed (HTTP {status})")

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
                "osType": 2, **DEVICE_PROFILE,
            },
        )
        token = data["jwtToken"]
        self.access_token = token["accessToken"]
        self.refresh_token = token["refreshToken"]
        return data

    async def async_register_device(self):
        await self._call("PUT", "VipDevice", body=dict(DEVICE_PROFILE))

    async def async_get_cars(self):
        return await self._call("GET", "VipCar") or []

    async def async_request_car(self, car_id, area_id):
        # requestTime null = now; the immediate-request format is the one field not statically verified (see VIP_PARKER_API.md A.8)
        await self._call("POST", f"CarRequest/Add/{car_id}", body={"areaId": area_id, "requestTime": None})

    async def async_cancel_request(self, car_id):
        await self._call("DELETE", f"CarRequest/{car_id}")
