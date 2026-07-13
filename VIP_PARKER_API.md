# VIP Parker API — single source of truth

Reverse-engineered private API for the **VIP Parker** app (product **SMS Valet**, vendor **TEZ
Technology**), the monthly-parker companion for SMS Valet ticketless valet. This document is the
canonical reference for building integrations (Home Assistant, scripts, etc.) against your **own**
account, and it doubles as a **runbook**: Part B/C explain exactly how the API below was extracted so
you (or a coding agent) can re-derive it when the app ships an update.

> **For coding agents:** if asked to "update the API" or "check for new endpoints", go to
> [Part C — Updating this doc](#part-c--updating-this-doc-when-the-app-changes). The whole extraction is
> automated by [`extract_api.sh`](./extract_api.sh); run it, read `report/`, and diff against Part A.

## Provenance (what this snapshot was built from)
| | |
|---|---|
| App / package | VIP Parker · `com.smsvalet.test` |
| Version | **4.4.0** (versionCode `1090400091`) |
| SDK | minSdk 28, target/compile 35 |
| APK SHA-256 | `ef03f59f96d55c5ea379edcf0605e6e77fe149d09a77636c84be394bcebf1b5b` (19,262,153 bytes) |
| APK source | APKPure direct download |
| Analyzed | 2026-07-13, statically (no live traffic) |
| Toolchain | podman → `eclipse-temurin:21-jdk` container · apktool 2.9.3 · jadx 1.5.0 |
| Purpose | Personal interoperability with the author's own account |

## Contents
- [Part A — API reference](#part-a--api-reference)
- [Part B — How this was extracted (methodology + runbook)](#part-b--how-this-was-extracted-methodology--runbook)
- [Part C — Updating this doc when the app changes](#part-c--updating-this-doc-when-the-app-changes)
- [Part D — Decompilation notes & obfuscation map](#part-d--decompilation-notes--obfuscation-map)

---

# Part A — API reference

## A.1 Base URL
```
https://vipparkerapi.smsvalet.com/api/v2/
```
Confirmed: the Retrofit client is built with base `f678b + "v2/"` where `f678b` is
`https://vipparkerapi.smsvalet.com/api/`. Non-prod hosts exist (`test1vipparkerapi.smsvalet.com`,
`stage1vipparkerapi.smsvalet.com`), each with its own app key. All paths in the tables below are
relative to this base.

**No certificate pinning.** The Android `network_security_config.xml` contains only a `debug-overrides`
block and there are no `sha256/…` pins anywhere in the code, so a trusted-CA MITM proxy would also work —
but decompilation already produced the full contract, so interception isn't needed.

## A.2 Auth model
Two credentials:

1. **App key** — identical in every install (not user-specific; extracted from the public APK, not a secret). Raw value:
   ```
   FGVDFC4C5NE1SDOCMLGNASK1C06ZVWC2W1ABPLWX4MTRUNB75IB0A0KAHWCZUGR3WHG1LLKNVTSBLRSGMZOW
   ```
   Sent **only on the login endpoints** as header **`ApiKey`**, and the value is
   **Base64-encoded (NO_WRAP)** before sending → `ApiKey: base64(rawKey)`.
   (Confirmed in the header interceptor: `Base64.encodeToString(key.getBytes(), 2)`.)

2. **Per-user JWT** — obtained via phone OTP, sent on every other endpoint as
   **`Authorization: Bearer <jwtToken>`** (added by an OkHttp interceptor).

### Login flow *(token shapes confirmed against the live server)*
1. `POST Account/SendAuthorizationCode` (header `ApiKey`) → sends an SMS code.
2. `POST Account/VerifyAuthorizationCode` (header `ApiKey`) →
   `{ deviceId, vipId, jwtToken: { accessToken, refreshToken } }`.
   Use **`jwtToken.accessToken`** as the Bearer token; keep `refreshToken` for step 3.
3. `POST Account/RefreshToken` with `Authorization: Bearer <refreshToken>` →
   `{ accessToken, refreshToken }` to renew the access token.

### Common headers
| Header | When | Value |
|---|---|---|
| `Authorization` | authenticated calls | `Bearer <jwtToken>` |
| `ApiKey` | login calls only | `base64(appKey)` |
| `Content-Type` | requests with a body | `application/json` |
| `Accept-Language` | several GETs | culture, e.g. `en-US` |

### Response envelope
Every response is wrapped: `{ "data": <T>, "error": { "errorCode": <code>, "message": <string> } }`.
On success read `data`; on failure `error.errorCode` is one of the codes in
[A.6](#a6-server-error-codes). `—` in the tables means empty body.

## A.3 Endpoints

### Login — no-token interface, header `ApiKey: base64(appKey)`
| Verb | Path | Request body | Response `data` |
|------|------|--------------|-----------------|
| POST | Account/SendAuthorizationCode | `{ phoneNumber, countryCode }` | — |
| POST | Account/VerifyAuthorizationCode | `{ phoneNumber, countryCode, authorizationCode, cultureName, pushNotificationToken, appVersion, osVersion, osType }` | `{ deviceId, vipId, jwtToken: { accessToken, refreshToken } }` |
| POST | Account/RefreshToken | *(header `Authorization`)* | `{ accessToken, refreshToken }` |
| DELETE | VipDevice | *(header `Authorization`)* | — |

### Cars & requests — Bearer auth *(the core of a Home Assistant integration)*
| Verb | Path | Request body | Response `data` |
|------|------|--------------|-----------------|
| GET | **VipCar** | — | `[ { vipCarId, carId, ticketNumber, nfcTag, requestStatus, description, make, autoRequestDate, areaId, locationId, locationName } ]` |
| GET | VipCar/{vipCarId} | — | `{ plate, values, drivers }` |
| DELETE | VipCar/{vipCarId} | — | — |
| POST | CarDriver/Add/{vipCarId} | `{ phoneNumber, countryCode, firstName, lastName }` | driverId (Long) |
| **POST** | **CarRequest/Add/{carId}** | `{ areaId, requestTime }` | — |
| **DELETE** | **CarRequest/{carId}** | — | — |
| GET | CarRequest/Areas/{carId}/{locationId} | — | `[ { areaId, name } ]` |

- **Request your car now:** `POST CarRequest/Add/{carId}` with `areaId` (a pickup area, from
  `CarRequest/Areas` or `VipLocation/Areas`) and `requestTime`. The car object's `autoRequestDate`
  implies scheduled requests are supported; the exact "now" encoding of `requestTime` is the one field
  worth confirming from a single live call.
- **Current status:** `GET VipCar` → each car's `requestStatus` (see [A.5](#a5-request-status-codes)).
  This is the field to poll for "is my car ready."

### Locations — Bearer auth
| Verb | Path | Request body | Response `data` |
|------|------|--------------|-----------------|
| GET | VipLocation/Assignable | — | `[ { locationId, locationName, address, logo, isResidentialValidationsEnabled, isCouponsPurchaseEnabled, isUnlimitedCouponsPurchase, remainingCouponsToPurchase, isSelectDeliveryAreaEnabled, currencyFormatType, currencySymbol, locale, tipConfiguration } ]` |
| GET | VipLocation/Areas/{locationId} | — | `[ { areaId, name, isActive } ]` |
| POST | VipLocation/{locationId} | — | `{ locationId, isLocationAlertEnabled, currentCouponBalance, couponName, singleCouponValue }` |
| PUT | VipLocation/{locationId} | `{ isLocationAlertEnabled }` | — |
| DELETE | VipLocation/{locationId} | — | — |

### Account & device — Bearer auth
| Verb | Path | Request body | Response `data` |
|------|------|--------------|-----------------|
| GET | Account/Information | — | `{ phoneNumber, countryCode, email, isCarRequestBlacklisted, isCreditCardBlacklisted, accountLocations }` |
| GET | Account/History *(Accept-Language)* | — | `{ validations, parkings, tippings }` |
| PUT | Account | `{ email }` | — |
| PUT | VipDevice | `{ cultureName, appVersion, osVersion, pushNotificationToken }` | — |

### Valet chat — Bearer auth
| Verb | Path | Request body | Response `data` |
|------|------|--------------|-----------------|
| GET | Message/{carId} | — | `[ { employee, message, messageDateUtc } ]` |
| POST | Message/Send/{carId} | `{ message }` | `{ employee, message, messageDateUtc }` |

### Guest validation — Bearer auth
| Verb | Path | Response `data` |
|------|------|-----------------|
| GET | Validation/TicketsToValidate/{searchQuery}/{searchParamType} | ticket list |
| POST | Validation/ValidateTicket/{carId}/{couponCount} | — |
| POST | Validation/SendReceipt/{locationId} | — |

### Payments / tips — Bearer auth
| Verb | Path | Response `data` |
|------|------|-----------------|
| GET | CreditCard | `[ { profileId, cardNumber, expiryMonth, expiryYear, cardType, name, isDefault } ]` |
| POST | CreditCard/Add | profileId (String) |
| DELETE | CreditCard/{creditCardProfileId} | — |
| POST | CreditCard/Transaction | transactionId (Long) |
| GET | CreditCard/PaymentSummary/{locationId}/{couponCount} | summary |
| POST | CreditCard/Tip/Car | id (Long) |
| POST | CreditCard/Tip/Location | id (Long) |
| GET | CreditCard/Tip/Summary/{locationId}/{tipAmount} | summary |
| POST | CreditCard/Tip/SendReceipt/{tipId} | — |
| POST | Parking/SendReceipt/{carId} | — |

*(35 endpoints total: 12 GET, 15 POST, 3 PUT, 5 DELETE.)*

## A.4 Live status
Status changes are delivered by **Firebase Cloud Messaging push** (the app registers a
`pushNotificationToken`), after which it re-fetches over REST. There's no simple public stream to
subscribe to without emulating an FCM device, so **for Home Assistant, poll `GET VipCar`** (e.g. every
30–60 s while a request is active) and read `requestStatus`.

Firebase client config (embedded in the app; identifiers, not user secrets):
project `com-tezhq-vipparker` · RTDB `https://com-tezhq-vipparker.firebaseio.com` ·
sender/project number `248336931572` · Web API key `AIzaSyAjaaYKQrElRH6NQ2v1jBmq6OvocXo9T1A` ·
storage `com-tezhq-vipparker.appspot.com` ·
OAuth web client `248336931572-soa0i2a5cv3j194ql3bq1r673qk20irb.apps.googleusercontent.com`.

## A.5 Request status codes
`requestStatus` on each VipCar — a JSON **number** (live-verified: `1` = `CAR_PARKED`):

| Code | Constant | Meaning |
|------|----------|---------|
| 0 | CAR_NOT_PARKED | not in the garage |
| 1 | CAR_PARKED | parked / at rest |
| 2 | CAR_REQUESTED | you requested it |
| 3 | CAR_ON_THE_WAY | valet is bringing it |
| 4 | CAR_READY | ready in the waiting area |

## A.6 Server error codes
`error.errorCode` values in the response envelope (confirmed **numeric** on the wire). Note the enum
`@SerializedName` precedes each constant, so the mapping is exactly as below —
`SERVER_COMMUNICATION_ERROR` has **no wire code** (it's the client-side fallback when the code is
unknown / the network failed). Live-verified points: `4006 = INCORRECT_PARAMETERS` ("Incorrect
parameter(s)") and `5000 = OTHER_ERROR` ("Other error").

| Code | Constant |
|------|----------|
| 4001 | UNAUTHORIZED_ACCESS *(token invalid/expired → refresh or re-login; triggers auto-refresh)* |
| 4002 | UNSUPPORTED_API_VERSION |
| 4003 | INVALID_ACCOUNT_EMAIL |
| 4004 | RESOURCE_NOT_FOUND |
| 4005 | INVALID_CREDIT_CARD_FORMAT |
| 4006 | INCORRECT_PARAMETERS |
| 4009 | RESOURCE_ALREADY_EXISTS |
| 4010 | VIP_BLACKLISTED |
| 4011 | COUPON_COUNT_LIMIT_EXCEEDED |
| 4012 | TRANSACTION_AMOUNT_LIMIT_EXCEEDED |
| 4013 | TRANSACTION_REJECTED |
| 4014 | AREA_INACTIVE |
| 4015 | VEHICLE_NOT_PARKED |
| 4016 | CONFIGURATION_MISMATCH |
| 5000 | OTHER_ERROR |
| — | SERVER_COMMUNICATION_ERROR *(no code; client-side fallback)* |

(Client-side error categories also exist: `NO_INTERNET_CONNECTION`, `SOCKET_TIMEOUT_EXCEPTION`,
`FORCE_LOGOUT`, `INVALID_RESPONSE`, etc.)

## A.7 curl sketch
```bash
BASE=https://vipparkerapi.smsvalet.com/api/v2
APIKEY=$(printf %s 'FGVDFC4C5NE1SDOCMLGNASK1C06ZVWC2W1ABPLWX4MTRUNB75IB0A0KAHWCZUGR3WHG1LLKNVTSBLRSGMZOW' | base64)

# 1) request an SMS code
curl -sX POST "$BASE/Account/SendAuthorizationCode" \
  -H "ApiKey: $APIKEY" -H 'Content-Type: application/json' \
  -d '{"phoneNumber":"5551234567","countryCode":"+1"}'

# 2) verify the code -> jwtToken
curl -sX POST "$BASE/Account/VerifyAuthorizationCode" \
  -H "ApiKey: $APIKEY" -H 'Content-Type: application/json' \
  -d '{"phoneNumber":"5551234567","countryCode":"+1","authorizationCode":"123456",
       "cultureName":"en-US","pushNotificationToken":"","appVersion":"","osVersion":"","osType":0}'
# -> { "data": { "deviceId":..., "vipId":..., "jwtToken":"eyJ..." } }

TOKEN=eyJ...   # jwtToken from step 2

# 3) list cars + current status
curl -s "$BASE/VipCar" -H "Authorization: Bearer $TOKEN" -H 'Accept-Language: en-US'

# 4) list pickup areas for a car, then request it
curl -s "$BASE/CarRequest/Areas/<carId>/<locationId>" -H "Authorization: Bearer $TOKEN"
curl -sX POST "$BASE/CarRequest/Add/<carId>" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"areaId":<areaId>,"requestTime":null}'

# 5) cancel
curl -sX DELETE "$BASE/CarRequest/<carId>" -H "Authorization: Bearer $TOKEN"
```

## A.8 Confirmed against the live server (read-only, 2026-07-13)
All of the below were verified with read-only GETs on a real account (`vip_parker.py get <path>` — see
[Part B](#part-b--how-this-was-extracted-methodology--runbook)); no state was changed.
- **countryCode** is stored/sent with the leading plus: `+1` (from `Account/Information`).
- **requestStatus** is a JSON **number** (`"requestStatus":1` = parked); **error.errorCode** is a number too.
- **osType `2`** (with `appVersion:"4.4.0"`, `osVersion:"15"`, `cultureName:"en-US"`) is accepted by
  `VerifyAuthorizationCode`.
- **Access token** = HS256 JWT, claims `{ DeviceId, TokenId, TokenType, VipId, exp }` — **no `iat`**.
  `exp` was ~24h after issuance. Renew with `POST Account/RefreshToken`.
- **Datetime format** across the API is ISO-8601 **local, no timezone, no fractional seconds**
  (`"2026-06-16T18:55:05"` — from `Account/History` `dateIn`/`dateOut`). See [A.11](#a11-data-conventions-live-confirmed).

**Only remaining unknown — the one thing that needs a real request (deliberately not probed):**
- **`requestTime`** exact value for an *immediate* `CarRequest/Add`. Given every other datetime in the API
  is ISO-8601 local, `requestTime` is almost certainly the same ISO-8601 local string for a scheduled
  request, with `null` (or an omitted field) meaning "now" — but the immediate-request wire value is not
  POST-verified. Capture it from the app, or the first time you actually summon your car.

## A.9 Object shapes (nested payloads + remaining request bodies)
All JSON keys below are the Gson `@SerializedName` values (the real wire keys).

### Remaining request bodies (payments / receipts)
| Endpoint | Body |
|---|---|
| POST CreditCard/Add | `{ creditCardNumber, expiryMonth, expiryYear }` *(raw PAN → tokenized server-side)* |
| POST CreditCard/Transaction | `{ locationId, creditCardProfileId, cvv, couponCount, actionId }` |
| POST CreditCard/Tip/Car | `{ carId, tipAmount, creditCardProfileId, cvv, actionId }` |
| POST CreditCard/Tip/Location | `{ locationId, areaId, tipAmount, creditCardProfileId, cvv, actionId }` |
| POST CreditCard/Tip/SendReceipt/{tipId} | `{ email }` |
| POST Parking/SendReceipt/{carId} | `{ email }` |
| POST Validation/SendReceipt/{locationId} | `{ transactionId, email }` |

*(`actionId` appears to be a client-supplied idempotency/nonce token for payment actions.)*

### Nested response objects  *(live-confirmed 2026-07-13 unless noted)*
- **VipCar/{vipCarId}** `{ plate, values: [ { name, value } ], drivers: [ { driverId, phoneNumber, countryCode, firstName, lastName, isMainDriver } ] }` — `values` are display attribute pairs (e.g. `{name:"Make",value:"Honda"}`, `{name:"Color",value:"Gray"}`); `drivers` is omitted when empty.
- **Account/Information** `accountLocations` element = `{ locationId, isLocationAlertEnabled, singleCouponValue, couponName, currentCouponBalance }`
- **Account/History** `{ validations: [Validation], parkings: [Parking], tippings: [Tipping] }` where
  - Validation = `{ carId, transactionId, date, phoneNumber, countryCode, tezCard, creditCard, validationCount, locationId, locationName, chargedAmount, validationAmount }`
  - Parking = `{ locationId, locationName, carId, dateIn, totalTime, chargedAmount, tipAmount, dateOut, description, driver, creditCards }`
  - Tipping = `{ locationId, locationName, date, chargedAmount, creditCard, tipAmount, tipId, areaName }`
- **VipLocation/Assignable** `tipConfiguration` = `{ customTip, predefinedTips: [ { amount, isSelected } ] }`
- **CreditCard/Tip/Summary** `{ convenienceFee, tipAmount }` · **CreditCard/PaymentSummary** `{ convenienceFee, validationTotal }`
- **Validation/TicketsToValidate** item = `{ carId, locationId, phoneNumber, countryCode, tezCard, ticketNumber, parkingFee, parkingTime, timeIn }`
- **error** object = `{ errorCode, message }` (errorCode per [A.6](#a6-server-error-codes))

## A.10 Coverage / what is NOT here
- **Complete:** all **35 REST endpoints** — the entire Retrofit surface (only two interfaces exist:
  authenticated + no-token login), the single backend host `vipparkerapi.smsvalet.com`, every request
  and response field including nested objects, both enums, and all server error codes. There is no
  second REST API and no un-mapped endpoint.
- **Described but not wire-mapped:** the **Firebase side-channel** — FCM push (status-change
  notifications) and any Realtime Database presence. It isn't reproduced to a request/response contract
  because it isn't needed (REST covers every action + status) and can't be exercised without emulating
  an FCM device. Poll `GET VipCar` instead ([A.4](#a4-live-status)).
- **One value format** left for a real request — see [A.8](#a8-confirmed-against-the-live-server-read-only-2026-07-13).

## A.11 Data conventions (live-confirmed 2026-07-13)
Verified with read-only GETs on a real account (see [A.8](#a8-confirmed-against-the-live-server-read-only-2026-07-13)).
- **Datetimes**: ISO-8601 **local, no timezone/offset, no fractional seconds** — `"2026-06-16T18:55:05"`
  (`dateIn`, `dateOut`; `autoRequestDate` and the request's `requestTime` use the same shape).
- **Money**: pre-formatted **currency strings**, not numbers — `"$0.00"` (`chargedAmount`, `tipAmount`, …).
- **Durations**: human display strings — `"12h 21m"`, `"5d 14h 27m"` (`totalTime`).
- **Empty vs absent**: empty collections come back as `[]`; empty/unset objects may be **omitted**
  entirely (e.g. a car with no drivers returns `{ plate, values }` with no `drivers` key).
- **Sentinels**: "unlimited" is encoded as `999999999` (`remainingCouponsToPurchase`).
- **Server key typo**: the wire sends `isUnlimitedCuponsPurchase` (missing an "o"); the app's model
  expects `isUnlimitedCouponsPurchase`, so that flag silently fails to bind in the app. Use the server
  spelling.
- **Pickup areas**: source the `areaId` for `CarRequest/Add` from `GET VipLocation/Areas/{locationId}`
  (`{ areaId, name, isActive }`). `GET CarRequest/Areas/{carId}/{locationId}` returned `[]` while the car
  was parked, so treat `VipLocation/Areas` as canonical. Where `isSelectDeliveryAreaEnabled` is false
  there is a single fixed area.

---

# Part B — How this was extracted (methodology + runbook)

Everything runs **inside a podman container** (`eclipse-temurin:21-jdk`), so the host only needs
`podman`. On macOS, podman already runs its containers inside a Linux VM, which provides the isolation.

## B.1 Automated re-run — `extract_api.sh`
```bash
podman machine start            # if the VM is stopped (the script also does this)
./extract_api.sh                # writes ./vipparker-extract/
#   ./extract_api.sh /some/dir  # or choose an output dir
```
The script (all steps idempotent — re-runs reuse existing artifacts):
1. Ensures the podman VM is up.
2. Downloads the current APK from APKPure's direct endpoint
   (`https://d.apkpure.com/b/APK/com.smsvalet.test?version=latest`).
3. Fetches apktool + jadx into `tools/` (cached).
4. `apktool d` → `smali-out/` (smali + resources + manifest);
   `jadx` → `jadx-out/sources/` (readable Java).
5. Greps out and writes `report/`:
   - `00-provenance.txt` — version, sha256, size
   - `10-base-urls.txt`, `11-candidate-api-keys.txt`
   - `12-pinning.txt` — network-security-config + `sha256/` pin scan → pinning verdict
   - `13-firebase.txt` — Firebase/Google client config
   - `14-hosts.txt` — every host referenced in code
   - `20-endpoints-raw.txt` — `(verb-annotation-class, path)` pairs per interface
   - `21-verb-class-freq.txt` — how often each verb-annotation class appears
   - `22-interface-smali-files.txt` — which smali files hold the API interface(s)
   - `30-enums.txt` — status / error enums
6. Prints a summary.

Then interpret `report/` using Part C + Part D and update Part A.

## B.2 Manual steps (when the script needs adjusting)
Same pipeline, by hand. `$OUT` is a scratch dir; all heavy work is in the container.
```bash
OUT=~/vipparker-extract; mkdir -p "$OUT"
podman machine start
podman run --rm -v "$OUT":/work docker.io/library/eclipse-temurin:21-jdk bash -c '
  set -e; cd /work
  # APK (jar = JDK, avoids needing unzip/file)
  curl -fL -A "Mozilla/5.0" -o app.apk "https://d.apkpure.com/b/APK/com.smsvalet.test?version=latest"
  jar tf app.apk | head                                             # sanity: valid zip
  # tools
  curl -fsSL -o apktool.jar https://github.com/iBotPeaches/Apktool/releases/download/v2.9.3/apktool_2.9.3.jar
  curl -fsSL -o jadx.zip   https://github.com/skylot/jadx/releases/download/v1.5.0/jadx-1.5.0.zip
  mkdir jadx && (cd jadx && jar xf ../jadx.zip) && chmod +x jadx/bin/jadx
  # decode
  java -jar apktool.jar d -f -o smali-out app.apk                   # smali + res + manifest
  JAVA_OPTS=-Xmx2g jadx/bin/jadx -j 3 --no-res --no-debug-info -d jadx-out app.apk || true
'
```
Key greps (run on the host against `$OUT`), in the order that builds Part A:
```bash
cd "$OUT"
# base URL + app key (Config class)
grep -rn 'smsvalet.com/api' jadx-out/sources
grep -rhoE '"[A-Z0-9]{40,}"' jadx-out/sources | sort -u
# pinning
cat smali-out/res/xml/network_security_config.xml
grep -rnoE 'sha256/[A-Za-z0-9+/=]{20,}' jadx-out/sources || echo "no pins"
# firebase
grep -E 'google_api_key|firebase_database_url|project_id|gcm_defaultSenderId' smali-out/res/values/strings.xml
# the API interface(s): files with PascalCase/slashed annotation values on abstract methods
grep -rlE 'value = "[A-Z][A-Za-z0-9]+(/[A-Za-z0-9{}._-]+)*"' smali-out/smali | xargs grep -lE '\.method public abstract'
# then read that interface in jadx (readable, shows verbs + body/return types), e.g.:
#   less jadx-out/sources/c5/a.java
# request/response field names come from the model classes' @SerializedName strings:
grep -rhoE '@[a-z0-9]+\.[a-z]\("[a-zA-Z_][a-zA-Z0-9_]*"\)' jadx-out/sources/H5   # request DTOs
grep -rhoE '@[a-z0-9]+\.[a-z]\("[a-zA-Z_][a-zA-Z0-9_]*"\)' jadx-out/sources/w5   # response DTOs
# enums (status / error): find enum files whose constants carry @SerializedName codes
grep -rlE 'CAR_|_ERROR|Status' jadx-out/sources | xargs grep -lE '\$VALUES'
```

---

# Part C — Updating this doc when the app changes

When VIP Parker ships an update and you want new endpoints/fields folded in:

1. **Re-extract:** `./extract_api.sh ~/vipparker-extract-<newversion>`.
2. **Bump provenance:** copy `report/00-provenance.txt` into Part A's provenance table (version, sha256,
   date). If the version is unchanged from this doc, stop — nothing to do.
3. **Diff the endpoints:** compare `report/20-endpoints-raw.txt` (paths column) against Part A's tables.
   ```bash
   # canonical list of paths this doc already documents vs. freshly extracted:
   sed -E 's/\*\*//g' VIP_PARKER_API.md | grep -oE '\| (GET|POST|PUT|DELETE) \| [A-Za-z0-9/{}]+' | awk '{print $4}' | sort -u > /tmp/doc-paths
   grep -vE '^##' report/20-endpoints-raw.txt | awk -F'\t' 'NF==2{print $2}' | sort -u > /tmp/new-paths
   diff /tmp/doc-paths /tmp/new-paths     # '>' = new endpoint to add, '<' = removed
   ```
4. **Resolve verbs:** map the renamed verb-annotation classes in `report/21-verb-class-freq.txt` to
   GET/POST/PUT/DELETE (see Part D — the mapping changes per build; re-derive it, don't trust the old
   letters). For each new path, read the interface in `jadx-out/sources/` to get its verb, request-body
   type, and response type, then add a row to the right Part A table.
5. **Fill field names:** for any new request/response model, grep its `@SerializedName` strings
   (Part B.2) and list the JSON keys.
6. **Check enums & errors:** re-read `report/30-enums.txt`; add any new `requestStatus` values (A.5) or
   error codes (A.6). Get numeric codes from the enum's `@SerializedName("…")` annotations.
7. **Re-verify invariants that integrations depend on:** base URL (`/api/v2/`), the `ApiKey` header is
   still base64-encoded, still no cert pinning (`report/12-pinning.txt`), auth still phone-OTP → Bearer.
   Call out in the changelog if any of these changed — they break existing integrations.
8. **Update the curl sketch / any client** if the auth flow or required body fields changed.

Prompt you can hand an agent:
> "Re-run `extract_api.sh` in this repo, then update `VIP_PARKER_API.md`: bump the provenance block,
> diff the extracted endpoints against Part A and add any new ones (with verb, request body, and
> response fields resolved from the jadx sources), refresh the status/error enums, and confirm the
> base URL, base64-ApiKey, no-pinning, and OTP→Bearer invariants still hold. Follow Part C."

---

# Part D — Decompilation notes & obfuscation map

The app is minified with **R8**, which matters for re-extraction:

- **Everything is repackaged and renamed per build.** The obfuscated names below are the *v4.4.0*
  snapshot — **expect them to change on updates.** Key on stable signals instead: literal strings,
  `@SerializedName` values, and path-like annotation values.
- **Retrofit itself is repackaged**, so its `retrofit2.http.*` annotations don't appear by those names —
  they're renamed (v4.4.0: package `m6`). There are no `retrofit2/http` strings in the bytecode; that's
  expected, not a dead end.
- **jadx sometimes fails to render interface annotations**, but **smali always preserves them**. When
  the endpoint list looks empty in jadx, decode to smali and read the `.annotation runtime` blocks.
  In smali, **parameter (`.param`) annotations are emitted before the method-level verb annotation**, so
  the extractor must skip `.param` blocks (the script does this).
- **Mapping renamed annotation classes to verbs (v4.4.0 snapshot):**
  `m6/f`=`@GET`, `m6/o`=`@POST`, `m6/n`=`@PUT`, `m6/b`=`@DELETE`, `m6/s`=`@Path`, `m6/a`=`@Body`,
  `m6/i`=`@Header`/`@Headers`. To re-derive on a new build without guessing:
  - `@Path` = the param-annotation class whose values match the `{token}` names in paths.
  - `@Header` = the class whose values are header names (`Authorization`, `ApiKey`, `Accept-Language`).
  - The method-level classes carrying the path strings are the verbs; a verb used with a `@Body` param
    is POST/PUT (PUT for idempotent resource updates like `Account`, `VipDevice`; POST for actions like
    `…/Add`, `…/Send`, `…/Transaction`), a verb with no body returning a model is GET, and a no-body verb
    on a `…/{id}` path returning empty is DELETE. Cross-check one obvious endpoint if unsure.
- **Gson `@SerializedName` is renamed** (v4.4.0: `@c3.c("jsonKey")`). Field names themselves are
  obfuscated, so the `@SerializedName` string is the real JSON key — always read those, not field names.
- **Base64 gotcha:** the `ApiKey` header is `Base64.encodeToString(rawKey.getBytes(), 2)` (NO_WRAP), not
  the raw key.
- **macOS case-insensitive filesystem:** jadx emits `C5/a.java` and `c5/a.java` as distinct classes;
  on macOS they can collide/appear merged. Prefer reading the **smali** path (`smali-out/smali/C5/…`) when
  case matters, or run jadx inside the (case-sensitive) Linux container as we do.

## D.1 v4.4.0 file/name index (starting points for a fresh read)
| Role | Obfuscated location (jadx `sources/…`) |
|---|---|
| Config: base URL `f678b`, app key `f679c`, `.c()`=+`v2/` | `E5/a.java` |
| API interface (authenticated) + nested no-token interface | `c5/a.java` (`C5/a` + `C5/a$a` in smali) |
| Header interceptor (Bearer + base64 ApiKey) | `c5/a.java` |
| Retrofit runtime (repackaged) / its http annotations | `j6/*` / `m6/*` |
| Gson `@SerializedName` | `c3/c` |
| Request DTOs | `H5/*` |
| Response DTOs | `w5/*` |
| Remote enums: `EnumC1721e`=RequestStatus (0–4), `EnumC1720d`=error (4001–5000) | `x5/*` |
| UI enums (mirror of remote) | `z5/*` |
| Firebase config | `smali-out/res/values/strings.xml` |
| Network security config | `smali-out/res/xml/network_security_config.xml` |
