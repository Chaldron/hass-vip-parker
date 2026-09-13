DOMAIN = "vip_parker"
BASE_URL = "https://vipparkerapi.smsvalet.com/api/v2/"
APP_KEY = "FGVDFC4C5NE1SDOCMLGNASK1C06ZVWC2W1ABPLWX4MTRUNB75IB0A0KAHWCZUGR3WHG1LLKNVTSBLRSGMZOW"
# Poll slowly while nothing is happening; poll fast only while a request is in
# flight, so an arrival shows up promptly without hammering the API otherwise.
POLL_IDLE_SECONDS = 300
POLL_ACTIVE_SECONDS = 30
ACTIVE_STATUSES = (2, 3)  # requestStatus codes: requested, on_the_way

# The device identity the real app reports at login and on every launch
# (PATCH VipDevice). Sessions that never re-register get revoked server-side
# after ~5 days, so the coordinator re-registers once a day.
DEVICE_PROFILE = {
    "cultureName": "en-US",
    "appVersion": "4.4.0",
    "osVersion": "15",
    "pushNotificationToken": "",
}
DEVICE_REGISTER_SECONDS = 24 * 3600

STATUS_LABELS = {0: "not_parked", 1: "parked", 2: "requested", 3: "on_the_way", 4: "ready"}
