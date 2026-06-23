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
num2 = get_stable_value("#leftroom_1")
num3 = get_stable_value("#leftroom_2")
total = num1 + num2 + num3

print(f"[SUCCESS] FINAL ROOM AVAILABILITY: {num1} + {num2} + {num3} = {total}")
