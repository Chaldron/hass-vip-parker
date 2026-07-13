#!/usr/bin/env python3
"""
vip_parker.py — a small, dependency-free client + CLI for the VIP Parker API.

The full API contract lives in VIP_PARKER_API.md. This module is a thin reference
client used for read-only exploration and as the basis for the Home Assistant
integration. (The one-off "probe" that confirmed the open questions has been
removed now that its findings are recorded in the docs — see A.8 / A.11 there.)

It persists the session (access + refresh token) to a local file so you don't
re-login while developing, and auto-refreshes the access token on expiry. It will
NOT summon your car: POST CarRequest/Add is hard-guarded.

Stdlib only — no pip install. Python 3.8+.

    python3 vip_parker.py login --phone 5551234567 --country +1   # login + save session
    python3 vip_parker.py get VipCar                               # read-only GET (auto-refresh)
    python3 vip_parker.py get VipLocation/Areas/<locationId>      # e.g. pickup areas
    python3 vip_parker.py refresh                                  # force a token refresh
    python3 vip_parker.py get Account/Information --token "eyJ..." # one-off token (not saved)
"""
import argparse
import base64
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

BASE_URL = "https://vipparkerapi.smsvalet.com/api/v2/"
RAW_APP_KEY = "FGVDFC4C5NE1SDOCMLGNASK1C06ZVWC2W1ABPLWX4MTRUNB75IB0A0KAHWCZUGR3WHG1LLKNVTSBLRSGMZOW"
DEFAULT_SESSION = ".vip_parker_session.json"
_FORBIDDEN = ("CarRequest/Add",)  # state-changing endpoints this tool must never call


def unwrap(parsed):
    """Return the payload inside the {data: ...} envelope, or the object itself."""
    if isinstance(parsed, dict) and "data" in parsed:
        return parsed["data"]
    return parsed


class VipParker:
    def __init__(self, token=None, refresh_token=None, session_path=DEFAULT_SESSION):
        self.base_url = BASE_URL
        self.token = token
        self.refresh_token = refresh_token
        self.device_id = None
        self.vip_id = None
        self.phone = None
        self.country = None
        self.session_path = session_path
        self.api_key_b64 = base64.b64encode(RAW_APP_KEY.encode()).decode()
        self._ctx = ssl.create_default_context()  # no cert pinning; plain TLS

    # --- persistence -------------------------------------------------------
    def save(self, path=None):
        path = path or self.session_path
        with open(path, "w") as f:
            json.dump({
                "token": self.token, "refreshToken": self.refresh_token,
                "deviceId": self.device_id, "vipId": self.vip_id,
                "phone": self.phone, "country": self.country,
            }, f, indent=2)
        try:
            os.chmod(path, 0o600)  # tokens are secrets
        except OSError:
            pass
        print(f">> session saved to {path} (secret — keep it gitignored)")

    @classmethod
    def load(cls, path=DEFAULT_SESSION):
        if not path or not os.path.exists(path):
            return None
        with open(path) as f:
            b = json.load(f)
        c = cls(token=b.get("token"), refresh_token=b.get("refreshToken"), session_path=path)
        c.device_id, c.vip_id = b.get("deviceId"), b.get("vipId")
        c.phone, c.country = b.get("phone"), b.get("country")
        return c

    # --- low-level request -------------------------------------------------
    def _request(self, method, path, body=None, headers=None):
        if any(f.lower() in path.lower() for f in _FORBIDDEN):
            raise RuntimeError(f"refusing to call a state-changing endpoint: {path}")
        url = self.base_url + path.lstrip("/")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/json")
        req.add_header("Accept-Language", "en-US")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, context=self._ctx, timeout=30) as r:
                return r.status, r.read().decode("utf-8", "replace"), None
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            status = e.code
        try:
            return status, raw, json.loads(raw)
        except ValueError:
            return status, raw, None

    def _parse(self, status, raw):
        try:
            return status, raw, json.loads(raw)
        except ValueError:
            return status, raw, None

    @staticmethod
    def _is_unauth(status, parsed):
        if status == 401:
            return True
        err = (parsed or {}).get("error") if isinstance(parsed, dict) else None
        return isinstance(err, dict) and err.get("errorCode") == 4001  # UNAUTHORIZED_ACCESS

    def get(self, path, _allow_refresh=True):
        """Read-only GET with the access token; auto-refreshes once on 4001/401."""
        if not self.token:
            raise RuntimeError("no token; log in first")
        status, raw, _ = self._request("GET", path, headers={"Authorization": f"Bearer {self.token}"})
        status, raw, parsed = self._parse(status, raw)
        if _allow_refresh and self.refresh_token and self._is_unauth(status, parsed):
            print(">> access token rejected; refreshing ...")
            if self.refresh():
                return self.get(path, _allow_refresh=False)
        return status, raw, parsed

    # --- auth --------------------------------------------------------------
    def send_code(self, phone, country):
        s, raw, _ = self._request(
            "POST", "Account/SendAuthorizationCode",
            body={"phoneNumber": phone, "countryCode": country},
            headers={"ApiKey": self.api_key_b64})
        if s >= 400:
            raise RuntimeError(f"SendAuthorizationCode failed (HTTP {s}): {raw[:300]}")

    def verify_code(self, phone, country, code, os_type=2, app_version="4.4.0",
                    os_version="15", culture="en-US"):
        body = {
            "phoneNumber": phone, "countryCode": country, "authorizationCode": code,
            "cultureName": culture, "pushNotificationToken": "",
            "appVersion": app_version, "osVersion": os_version, "osType": os_type}
        s, raw, _ = self._request(
            "POST", "Account/VerifyAuthorizationCode", body=body,
            headers={"ApiKey": self.api_key_b64})
        if s >= 400:
            raise RuntimeError(f"VerifyAuthorizationCode failed (HTTP {s}): {raw[:300]}")
        data = unwrap(json.loads(raw)) or {}
        self._apply_tokens(data.get("jwtToken"))
        self.device_id = data.get("deviceId")
        self.vip_id = data.get("vipId")
        self.phone, self.country = phone, country
        return data

    def _apply_tokens(self, jwt_token):
        """jwtToken is { accessToken, refreshToken } (may also arrive as a bare string)."""
        if isinstance(jwt_token, str):
            self.token = jwt_token
        elif isinstance(jwt_token, dict):
            self.token = jwt_token.get("accessToken") or jwt_token.get("token") or self.token
            self.refresh_token = jwt_token.get("refreshToken") or self.refresh_token

    def refresh(self):
        """POST Account/RefreshToken. Tries the refresh token first, then the access token."""
        for bearer in (self.refresh_token, self.token):
            if not bearer:
                continue
            s, raw, _ = self._request(
                "POST", "Account/RefreshToken", headers={"Authorization": f"Bearer {bearer}"})
            s, raw, parsed = self._parse(s, raw)
            data = unwrap(parsed)
            if s < 400 and isinstance(data, dict) and data.get("accessToken"):
                self.token = data["accessToken"]
                self.refresh_token = data.get("refreshToken") or self.refresh_token
                self.save()
                return True
        return False

    def login_interactive(self, phone, country, **kw):
        print(f">> sending SMS code to {country} {phone} ...")
        self.send_code(phone, country)
        code = input(">> enter the SMS code you received: ").strip()
        data = self.verify_code(phone, country, code, **kw)
        print(f">> logged in: vipId={data.get('vipId')} deviceId={data.get('deviceId')}")
        return data


# --- CLI -------------------------------------------------------------------
def _client_from_args(args, allow_login=True):
    if getattr(args, "token", None):
        return VipParker(token=args.token, session_path=args.session)
    c = VipParker.load(args.session)
    if c and c.token:
        print(f">> using saved session {args.session} (vipId={c.vip_id})")
        return c
    if not allow_login:
        raise SystemExit(f"no token and no saved session at {args.session}; run `login` first")
    c = VipParker(session_path=args.session)
    phone = args.phone or input("phone number: ").strip()
    c.login_interactive(phone, args.country, os_type=args.os_type)
    if not args.no_save:
        c.save()
    return c


def main(argv=None):
    p = argparse.ArgumentParser(description="VIP Parker reference client / CLI (read-only)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--token", help="existing Bearer access token (one-off; not saved)")
        sp.add_argument("--phone", help="phone number for OTP login")
        sp.add_argument("--country", default="+1", help="country code, default +1")
        sp.add_argument("--os-type", type=int, default=2, help="osType login field (default 2)")
        sp.add_argument("--session", default=DEFAULT_SESSION, help="session file path")
        sp.add_argument("--no-save", action="store_true", help="don't persist the session on login")

    for name, help_ in [("login", "OTP login and save the session"),
                        ("refresh", "force an access-token refresh")]:
        common(sub.add_parser(name, help=help_))
    g = sub.add_parser("get", help="read-only GET of an API path")
    g.add_argument("path", help="e.g. VipCar or Account/Information")
    common(g)

    args = p.parse_args(argv)

    if args.cmd == "login":
        c = _client_from_args(args)
        print("\naccess token (secret):\n" + (c.token or "(none)"))
        return 0
    if args.cmd == "refresh":
        c = _client_from_args(args, allow_login=False)
        print("refreshed" if c.refresh() else "refresh failed (re-login with `login`)")
        return 0
    if args.cmd == "get":
        c = _client_from_args(args)
        s, raw, parsed = c.get(args.path)
        print(f"HTTP {s}")
        print(json.dumps(parsed, indent=2) if parsed is not None else raw)
        return 0


if __name__ == "__main__":
    sys.exit(main())
