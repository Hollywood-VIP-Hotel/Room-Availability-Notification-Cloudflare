import os
import json
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

# Only these RoomTypeIDs are confirmed, active categories.
# ID ending in ...0001 is unidentified/stale per Yanolja support (2026-08) and
# is deliberately excluded so it can never silently affect the total again.
KNOWN_ROOM_TYPE_IDS = {
    os.environ.get("EZEE_ROOM_TYPE_ID_1"),
    os.environ.get("EZEE_ROOM_TYPE_ID_2"),
    os.environ.get("EZEE_ROOM_TYPE_ID_3"),
}

if not HOTEL_CODE or not AUTH_CODE:
    print("[ERROR] Missing EZEE_HOTEL_CODE or EZEE_AUTH_CODE environment variable.")
    exit(1)

if None in KNOWN_ROOM_TYPE_IDS or len(KNOWN_ROOM_TYPE_IDS) != 3:
    print("[ERROR] Missing one or more EZEE_ROOM_TYPE_ID_1/2/3 environment variables.")
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


def parse_inventory(response_text: str):
    """Return (total, breakdown_list) for known RoomTypeIDs only; raises on API-level error.

    The API normally returns XML, but some error conditions (e.g. auth
    failures) come back as a JSON body instead, e.g.:
        {"Errors": {"ErrorCode": "611", "ErrorMessage": "..."}}
    Check for that first so these surface as a clear error rather than
    an opaque XML parse failure.
    """
    stripped = response_text.strip()

    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            raise RuntimeError(f"eZee API returned an unrecognized non-XML response: {stripped[:300]}")

        error = data.get("Errors")
        if error:
            code = error.get("ErrorCode")
            message = error.get("ErrorMessage")
            raise RuntimeError(f"eZee API error {code}: {message}")

        raise RuntimeError(f"eZee API returned unexpected JSON: {stripped[:300]}")

    root = ET.fromstring(response_text)

    error_el = root.find("Errors")
    if error_el is not None:
        code = error_el.findtext("ErrorCode")
        message = error_el.findtext("ErrorMessage")
        raise RuntimeError(f"eZee API error {code}: {message}")

    # The response can include multiple <Source> blocks (e.g. one per
    # sales channel: OTA pool, direct website widget, etc.) that report
    # the same underlying inventory. Only read the first Source to avoid
    # double-counting the same rooms multiple times.
    sources = root.findall(".//Source")
    if not sources:
        return 0, []

    if len(sources) > 1:
        source_names = [s.get("name", "unnamed") for s in sources]
        print(f"[WARN] Multiple <Source> blocks found: {source_names}. "
              f"Using only the first one ('{source_names[0]}') to avoid double-counting.")

    breakdown = []
    seen_ids = set()
    total = 0
    for rt in sources[0].findall(".//RoomType"):
        room_type_id = rt.findtext("RoomTypeID")
        availability = int(rt.findtext("Availability", default="0"))
        seen_ids.add(room_type_id)

        is_known = room_type_id in KNOWN_ROOM_TYPE_IDS
        breakdown.append((room_type_id, availability, is_known))

        if is_known:
            total += availability

    unexpected = seen_ids - KNOWN_ROOM_TYPE_IDS
    if unexpected:
        print(f"[WARN] Ignored unrecognized RoomTypeID(s) not in the known list: {unexpected}")

    missing = KNOWN_ROOM_TYPE_IDS - seen_ids
    if missing:
        print(f"[WARN] Expected RoomTypeID(s) not found in response: {missing}")

    return total, breakdown


try:
    print("[INFO] Calling eZee Centrix API (TEST RUN)...")

    today = datetime.now(ZoneInfo("America/Los_Angeles")).date()
    from_date = today.isoformat()
    to_date = today.isoformat()

    xml_response = fetch_inventory(from_date, to_date)
    total, breakdown = parse_inventory(xml_response)

    print("[INFO] Per-room-type breakdown:")
    for room_type_id, availability, is_known in breakdown:
        tag = "counted" if is_known else "IGNORED (unrecognized)"
        print(f"    RoomTypeID {room_type_id}: {availability}  [{tag}]")

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
