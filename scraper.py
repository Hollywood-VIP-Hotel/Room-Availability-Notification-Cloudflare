import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


# -------------------------------------------------------------
# Notification time windows (Pacific Time)
# 30-minute windows centered on each target hour
# -------------------------------------------------------------
TARGET_WINDOWS = {
    7:  "7am",
    9:  "9am",
    10: "10am",
    11: "11am",
    12: "12pm",
    13: "1pm",
    14: "2pm",
    15: "3pm",
    16: "4pm",
    17: "5pm",
    18: "6pm",
    19: "7pm",
    20: "8pm",
    21: "9pm",
    22: "10pm",
    23: "11pm",
}

WINDOW_SPAN_MIN = 15  # 15 minutes before & after


def get_current_window_label():
    """Return the label ('8am', '12pm', etc.) if inside an allowed window; otherwise None."""
    pst_now = datetime.now(ZoneInfo("America/Los_Angeles"))

    for hour, label in TARGET_WINDOWS.items():
        center = pst_now.replace(hour=hour, minute=0, second=0, microsecond=0)
        early = center - timedelta(minutes=WINDOW_SPAN_MIN)
        late = center + timedelta(minutes=WINDOW_SPAN_MIN)

        if early <= pst_now <= late:
            return label

    return None


# -------------------------------------------------------------
# Only run inside designated time windows
# -------------------------------------------------------------
window_label = get_current_window_label()

if window_label is None:
    print("[INFO] Current time is not inside any notification window. Exiting.")
    exit()

print(f"[INFO] Inside allowed window: {window_label}")


# -------------------------------------------------------------
# eZee Centrix API call (replaces Selenium scraping)
# -------------------------------------------------------------
API_URL = "https://live.ipms247.com/pmsinterface/getdataAPI.php"

HOTEL_CODE = os.environ.get("EZEE_HOTEL_CODE")
AUTH_CODE = os.environ.get("EZEE_AUTH_CODE")

if not HOTEL_CODE or not AUTH_CODE:
    print("[ERROR] Missing EZEE_HOTEL_CODE or EZEE_AUTH_CODE environment variable.")
    exit(1)


def fetch_inventory(from_date: str, to_date: str) -> str:
    body = f"""<RES_Request>
    <Request_Type>Inventory</Request_Type>
    <Authentication>
        <HotelCode>{HOTEL_CODE}</HotelCode>
        <AuthCode>{AUTH_CODE}</AuthCode>
    </Authentication>
    <FromDate>{from_date}</FromDate>
    <ToDate>{to_date}</ToDate>
</RES_Request>"""

    resp = requests.post(
        API_URL,
        data=body,
        headers={"Content-Type": "application/xml"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.text


def parse_total_availability(xml_text: str) -> int:
    """Sum Availability across all RoomType entries in the response."""
    root = ET.fromstring(xml_text)

    error_el = root.find("Errors")
    if error_el is not None:
        code = error_el.findtext("ErrorCode")
        message = error_el.findtext("ErrorMessage")
        raise RuntimeError(f"eZee API error {code}: {message}")

    total = 0
    for rt in root.findall(".//RoomType"):
        total += int(rt.findtext("Availability", default="0"))

    return total


try:
    print("[INFO] Calling eZee Centrix API...")

    today = datetime.now(ZoneInfo("America/Los_Angeles")).date()
    from_date = today.isoformat()
    to_date = today.isoformat()  # same-day snapshot, matching the old scraper's "right now" numbers

    xml_response = fetch_inventory(from_date, to_date)
    total = parse_total_availability(xml_response)

    print(f"[SUCCESS] FINAL ROOM AVAILABILITY: {total}")

except Exception as e:
    print("[ERROR] Failed to fetch/parse inventory:", e)
    exit(1)


# -------------------------------------------------------------
# Send to Make webhook (includes window label) — unchanged
# -------------------------------------------------------------
webhook_url = os.environ.get("MAKE_WEBHOOK_URL")

if not webhook_url:
    print("[ERROR] Missing MAKE_WEBHOOK_URL environment variable.")
    exit(1)

payload = {
    "value1": f"{total} rooms available",
    "window": window_label  # <-- KEY for Make.com dedup
}

print("[INFO] Sending to Make webhook...")

try:
    response = requests.post(webhook_url, json=payload, timeout=15)
    if response.status_code in (200, 202):
        print("[SUCCESS] Notification sent to Make webhook!")
    else:
        print(f"[ERROR] Webhook error {response.status_code}: {response.text}")
except Exception as e:
    print(f"[ERROR] Failed to send webhook: {e}")
