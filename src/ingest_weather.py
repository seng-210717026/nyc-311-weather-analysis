import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

API_URL = os.environ.get(
    "WEATHER_BASE_URL",
    "https://archive-api.open-meteo.com/v1/archive",
)

START_DATE = os.environ.get("START_DATE", "2025-10-12")
END_DATE = os.environ.get("END_DATE", "2026-10-11")
TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT_SECONDS", "120"))

TIMEZONE = "America/New_York"
NY_TZ = ZoneInfo(TIMEZONE)

BOROUGHS = [
    ("Bronx", 40.8448, -73.8648),
    ("Brooklyn", 40.6782, -73.9442),
    ("Manhattan", 40.7831, -73.9712),
    ("Queens", 40.7282, -73.7949),
    ("Staten Island", 40.5795, -74.1502),
]

VARIABLES = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "weather_code",
    "wind_speed_10m",
    "wind_direction_10m",
    "cloud_cover",
]

run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
raw_dir = Path("data/raw/weather")
raw_dir.mkdir(parents=True, exist_ok=True)

raw_path = raw_dir / f"{run_id}_weather_unix.json"

params = {
    "latitude": ",".join(str(point[1]) for point in BOROUGHS),
    "longitude": ",".join(str(point[2]) for point in BOROUGHS),
    "start_date": START_DATE,
    "end_date": END_DATE,
    "hourly": ",".join(VARIABLES),
    "timezone": TIMEZONE,
    "timeformat": "unixtime",
    "temperature_unit": "celsius",
    "wind_speed_unit": "kmh",
    "precipitation_unit": "mm",
}

print("Starting corrected Open-Meteo ingestion...")
print(f"Date range: {START_DATE} to {END_DATE}")
print(f"Timezone conversion: {TIMEZONE}")
print(f"Requested boroughs: {len(BOROUGHS)}")
print(f"Hourly variables: {', '.join(VARIABLES)}")

response = None

for attempt in range(1, 6):
    try:
        response = requests.get(
            API_URL,
            params=params,
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        break
    except requests.RequestException as exc:
        if attempt == 5:
            raise SystemExit(f"Open-Meteo request failed: {exc}")
        wait = min(2 ** attempt, 30)
        print(
            f"Request failed ({attempt}/5): {exc}. "
            f"Retrying in {wait}s."
        )
        time.sleep(wait)

# Preserve the original API response as a separate raw file.
with raw_path.open("xb") as f:
    f.write(response.content)

print(f"Raw response saved: {raw_path}")

try:
    payload = response.json()
except ValueError as exc:
    raise SystemExit("The API response is not valid JSON.") from exc

if isinstance(payload, dict) and payload.get("error"):
    raise SystemExit(f"Open-Meteo API error: {payload}")

responses = payload if isinstance(payload, list) else [payload]

if len(responses) != len(BOROUGHS):
    raise SystemExit(
        f"Expected {len(BOROUGHS)} location responses, "
        f"received {len(responses)}."
    )

for (borough, _, _), item in zip(BOROUGHS, responses):
    hourly = item.get("hourly", {})
    times = hourly.get("time", [])

    if not times:
        raise SystemExit(f"No hourly timestamps returned for {borough}.")

    for variable in VARIABLES:
        values = hourly.get(variable)
        if not isinstance(values, list) or len(values) != len(times):
            raise SystemExit(
                f"Invalid array length for {borough}: {variable}"
            )

    first_local = datetime.fromtimestamp(
        int(times[0]), timezone.utc
    ).astimezone(NY_TZ)

    last_local = datetime.fromtimestamp(
        int(times[-1]), timezone.utc
    ).astimezone(NY_TZ)

    print(
        f"{borough}: {len(times):,} hourly rows; "
        f"{first_local.isoformat()} to {last_local.isoformat()}"
    )

print("Corrected raw weather download completed.")
print("Next step: convert the raw response into hourly and daily CSV files.")
