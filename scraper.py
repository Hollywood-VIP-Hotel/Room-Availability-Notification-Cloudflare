import os
import time
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# -------------------------------------------------------------
# Notification time windows (Pacific Time)
# 30-minute windows centered on each target hour
# -------------------------------------------------------------
TARGET_WINDOWS = {
    8:  "8am",
    12: "12pm",
    15: "3pm",
    18: "6pm",
    21: "9pm",
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
# Selenium & scraping logic (unchanged)
# -------------------------------------------------------------
URL = "https://live.ipms247.com/booking/book-rooms-hollywoodviphotel"

options = Options()
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--no-sandbox")
options.add_argument(
    "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

driver = webdriver.Chrome(options=options)
wait = WebDriverWait(driver, 30)


try:
    print("[INFO] Loading page...")
    driver.get(URL)

    print("[INFO] Waiting for booking engine container (#eZ_BookingRooms)...")
    wait.until(EC.presence_of_element_located((By.ID, "eZ_BookingRooms")))

    time.sleep(3)

except Exception as e:
    print("[ERROR] Could not load initial page or container:", e)
    driver.quit()
    exit(1)


def get_stable_value(css_selector):
    print(f"[INFO] Checking for element {css_selector}...")

    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, css_selector)))
    except:
        print(f"[WARN] Element {css_selector} not found — treating as 0")
        return 0

    stable_count = 0
    last_value = None

    for _ in range(30):
        try:
            text = driver.find_element(By.CSS_SELECTOR, css_selector).text.strip()

            if text.isdigit():
                if last_value is None:
                    last_value = text
                elif text == last_value:
                    stable_count += 1
                    if stable_count >= 2:
                        return int(text)
                else:
                    stable_count = 0
                    last_value = text
        except:
            pass

        time.sleep(1)

    return int(last_value or 0)


num1 = get_stable_value("#leftroom_0")
num2 = get_stable_value("#leftroom_4")
num3 = get_stable_value("#leftroom_6")
total = num1 + num2 + num3

print(f"[SUCCESS] FINAL ROOM AVAILABILITY: {num1} + {num2} + {num3} = {total}")

driver.quit()


# -------------------------------------------------------------
# Send to Make webhook (includes window label)
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
