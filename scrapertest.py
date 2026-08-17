import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo


# -------------------------------------------------------------
# TEST VERSION: no time-window gate, extra logging.
# Run manually (workflow_dispatch) to verify the API + Make.com
# pipeline end-to-end without waiting for the Cloudflare cron.
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

    print("[INFO] Request body:")
    print(body)

    resp = requests.post(
        API_URL,
        data=body,
        headers={"Content-Type": "application/xml"},
        timeout=15,
    )

    print(f"[INFO] HTTP status: {resp.status_code}")
    print("[INFO] Raw response:")
    print(resp.text)

    resp.raise_for_status()
    return resp.text


def parse_inventory(xml_text: str):
    """Return (total, breakdown_list) or raise on API-level error."""
    root = ET.fromstring(xml_text)

    error_el = root.find("Errors")
    if error_el is not None:
        code = error_el.findtext("ErrorCode")
        message = error_el.findtext("ErrorMessage")
        raise RuntimeError(f"eZee API error {code}: {message}")

    breakdown = []
    total = 0
    for rt in root.findall(".//RoomType"):
        room_type_id = rt.findtext("RoomTypeID")
        availability = int(rt.findtext("Availability", default="0"))
        breakdown.append((room_type_id, availability))
        total += availability

    return total, breakdown


try:
    print("[INFO] Calling eZee Centrix API (TEST RUN)...")

    today = datetime.now(ZoneInfo("America/Los_Angeles")).date()
    from_date = today.isoformat()
    to_date = today.isoformat()

    xml_response = fetch_inventory(from_date, to_date)
    total, breakdown = parse_inventory(xml_response)

    print("[INFO] Per-room-type breakdown:")
    for room_type_id, availability in breakdown:
        print(f"    RoomTypeID {room_type_id}: {availability}")

    print(f"[SUCCESS] FINAL ROOM AVAILABILITY: {total}")

except Exception as e:
    print("[ERROR] Failed to fetch/parse inventory:", e)
    exit(1)


# -------------------------------------------------------------
# Send to Make webhook — same payload shape as production,
# tagged as a manual test so you can tell it apart in Make.com
# -------------------------------------------------------------
webhook_url = os.environ.get("MAKE_WEBHOOK_URL")

if not webhook_url:
    print("[ERROR] Missing MAKE_WEBHOOK_URL environment variable.")
    exit(1)

payload = {
    "value1": f"{total} rooms available",
    "window": "manual-test"  # distinct label so it won't collide with real dedup keys
}

print("[INFO] Sending to Make webhook...")
print(f"[INFO] Payload: {payload}")

try:
    response = requests.post(webhook_url, json=payload, timeout=15)
    if response.status_code in (200, 202):
        print("[SUCCESS] Notification sent to Make webhook!")
    else:
        print(f"[ERROR] Webhook error {response.status_code}: {response.text}")
except Exception as e:
    print(f"[ERROR] Failed to send webhook: {e}")
