import csv
import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

START_DATE = date.fromisoformat(
    os.environ.get("START_DATE", "2025-10-12")
)
END_DATE = date.fromisoformat(
    os.environ.get("END_DATE", "2026-10-11")
)
LOCAL_TZ = ZoneInfo("America/New_York")

BOROUGHS = [
    "Bronx",
    "Brooklyn",
    "Manhattan",
    "Queens",
    "Staten Island",
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

RAW_DIR = Path("data/raw/weather")
OUT_DIR = Path("data/processed")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def average(values):
    values = [float(v) for v in values if v is not None]
    return round(mean(values), 3) if values else None


def minimum(values):
    values = [float(v) for v in values if v is not None]
    return round(min(values), 3) if values else None


def maximum(values):
    values = [float(v) for v in values if v is not None]
    return round(max(values), 3) if values else None


def total(values):
    values = [float(v) for v in values if v is not None]
    return round(sum(values), 3) if values else None


def dominant(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return Counter(values).most_common(1)[0][0]


def circular_mean_degrees(values):
    values = [float(v) for v in values if v is not None]
    if not values:
        return None

    radians = [math.radians(v) for v in values]
    sin_mean = sum(math.sin(v) for v in radians) / len(radians)
    cos_mean = sum(math.cos(v) for v in radians) / len(radians)

    if abs(sin_mean) < 1e-12 and abs(cos_mean) < 1e-12:
        return None

    result = math.degrees(math.atan2(sin_mean, cos_mean)) % 360
    return round(result, 3)


def write_csv(path, rows, columns):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved: {path} ({len(rows):,} rows)")


# Filename timestamps are sortable and match load.py snapshot selection.
raw_files = sorted(
    RAW_DIR.glob("*_weather_unix.json"),
    key=lambda p: p.name,
)

if not raw_files:
    raise SystemExit(
        "No *_weather_unix.json file found in data/raw/weather."
    )

raw_path = raw_files[-1]
print(f"Reading raw file: {raw_path}")

with raw_path.open(encoding="utf-8") as f:
    payload = json.load(f)

locations = payload if isinstance(payload, list) else [payload]

if len(locations) != len(BOROUGHS):
    raise SystemExit(
        f"Expected {len(BOROUGHS)} boroughs, got {len(locations)}."
    )

expected_dates = [
    (START_DATE + timedelta(days=i)).isoformat()
    for i in range((END_DATE - START_DATE).days + 1)
]

hourly_rows = []

for borough, location in zip(BOROUGHS, locations):
    hourly = location.get("hourly", {})
    raw_times = hourly.get("time", [])

    if not raw_times:
        raise SystemExit(f"No timestamps found for {borough}.")

    for variable in VARIABLES:
        values = hourly.get(variable)
        if not isinstance(values, list) or len(values) != len(raw_times):
            raise SystemExit(
                f"Invalid array length: borough={borough}, "
                f"variable={variable}"
            )

    epochs = [int(t) for t in raw_times]

    if len(set(epochs)) != len(epochs):
        raise SystemExit(f"Duplicate UTC timestamps in {borough}.")

    if any(b - a != 3600 for a, b in zip(epochs, epochs[1:])):
        raise SystemExit(
            f"Unexpected timestamp gap in {borough}; "
            "hourly data was not exported."
        )

    borough_rows = []

    for i, epoch in enumerate(epochs):
        utc_dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
        local_dt = utc_dt.astimezone(LOCAL_TZ)

        row = {
            "borough": borough,
            "timestamp_utc": utc_dt.isoformat(timespec="seconds"),
            "local_datetime": local_dt.isoformat(timespec="seconds"),
            "local_date": local_dt.date().isoformat(),
            "local_hour": local_dt.strftime("%H"),
            "utc_offset": local_dt.strftime("%z"),
            "temperature_2m_c": hourly["temperature_2m"][i],
            "relative_humidity_2m_pct":
                hourly["relative_humidity_2m"][i],
            "precipitation_mm": hourly["precipitation"][i],
            "weather_code": hourly["weather_code"][i],
            "wind_speed_10m_kmh": hourly["wind_speed_10m"][i],
            "wind_direction_10m_degrees":
                hourly["wind_direction_10m"][i],
            "cloud_cover_pct": hourly["cloud_cover"][i],
        }
        borough_rows.append(row)

    found_dates = sorted({r["local_date"] for r in borough_rows})

    if found_dates != expected_dates:
        raise SystemExit(
            f"Date coverage mismatch for {borough}: "
            f"{found_dates[0]} to {found_dates[-1]}, "
            f"{len(found_dates)} distinct dates."
        )

    print(
        f"{borough}: {len(borough_rows):,} observations; "
        f"{found_dates[0]} to {found_dates[-1]}"
    )
    hourly_rows.extend(borough_rows)


hourly_columns = [
    "borough",
    "timestamp_utc",
    "local_datetime",
    "local_date",
    "local_hour",
    "utc_offset",
    "temperature_2m_c",
    "relative_humidity_2m_pct",
    "precipitation_mm",
    "weather_code",
    "wind_speed_10m_kmh",
    "wind_direction_10m_degrees",
    "cloud_cover_pct",
]

daily_groups = defaultdict(list)
city_groups = defaultdict(list)

for row in hourly_rows:
    daily_groups[(row["borough"], row["local_date"])].append(row)
    city_groups[row["local_date"]].append(row)


daily_by_borough = []

for borough in BOROUGHS:
    for day in expected_dates:
        rows = daily_groups[(borough, day)]

        temps = [r["temperature_2m_c"] for r in rows]
        humidity = [r["relative_humidity_2m_pct"] for r in rows]
        rain = [r["precipitation_mm"] for r in rows]
        codes = [r["weather_code"] for r in rows]
        wind = [r["wind_speed_10m_kmh"] for r in rows]
        direction = [r["wind_direction_10m_degrees"] for r in rows]
        clouds = [r["cloud_cover_pct"] for r in rows]

        daily_by_borough.append({
            "borough": borough,
            "date": day,
            "hourly_observations": len(rows),
            "temperature_min_c": minimum(temps),
            "temperature_mean_c": average(temps),
            "temperature_max_c": maximum(temps),
            "relative_humidity_mean_pct": average(humidity),
            "precipitation_total_mm": total(rain),
            "precipitation_hours": sum(
                1 for v in rain if v is not None and float(v) > 0
            ),
            "weather_code_mode": dominant(codes),
            "wind_speed_mean_kmh": average(wind),
            "wind_speed_max_kmh": maximum(wind),
            "wind_direction_mean_degrees":
                circular_mean_degrees(direction),
            "cloud_cover_mean_pct": average(clouds),
        })

daily_columns = list(daily_by_borough[0].keys())


daily_index = {
    (row["borough"], row["date"]): row
    for row in daily_by_borough
}

city_daily = []

for day in expected_dates:
    rows = city_groups[day]
    borough_daily = [
        daily_index[(borough, day)]
        for borough in BOROUGHS
    ]

    temps = [r["temperature_2m_c"] for r in rows]
    humidity = [r["relative_humidity_2m_pct"] for r in rows]
    rain = [r["precipitation_mm"] for r in rows]
    codes = [r["weather_code"] for r in rows]
    wind = [r["wind_speed_10m_kmh"] for r in rows]
    direction = [r["wind_direction_10m_degrees"] for r in rows]
    clouds = [r["cloud_cover_pct"] for r in rows]

    borough_rain = [
        r["precipitation_total_mm"]
        for r in borough_daily
        if r["precipitation_total_mm"] is not None
    ]

    city_daily.append({
        "date": day,
        "boroughs_represented": len(BOROUGHS),
        "distinct_utc_hours": len({r["timestamp_utc"] for r in rows}),
        "borough_hourly_observations": len(rows),
        "temperature_min_c": minimum(temps),
        "temperature_mean_c": average(temps),
        "temperature_max_c": maximum(temps),
        "relative_humidity_mean_pct": average(humidity),
        "precipitation_mean_borough_total_mm": average(borough_rain),
        "precipitation_max_borough_total_mm": maximum(borough_rain),
        "weather_code_mode": dominant(codes),
        "wind_speed_mean_kmh": average(wind),
        "wind_speed_max_kmh": maximum(wind),
        "wind_direction_mean_degrees":
            circular_mean_degrees(direction),
        "cloud_cover_mean_pct": average(clouds),
    })

city_columns = list(city_daily[0].keys())

# Verify expected 23-hour and 25-hour local DST dates.
for borough in BOROUGHS:
    counts = {
        day: len(daily_groups[(borough, day)])
        for day in expected_dates
    }
    print(
        f"{borough} DST check: "
        f"2025-11-02={counts.get('2025-11-02')} hours; "
        f"2026-03-08={counts.get('2026-03-08')} hours"
    )

write_csv(
    OUT_DIR / "weather_hourly_by_borough.csv",
    hourly_rows,
    hourly_columns,
)
write_csv(
    OUT_DIR / "weather_daily_by_borough.csv",
    daily_by_borough,
    daily_columns,
)
write_csv(
    OUT_DIR / "weather_daily_citywide.csv",
    city_daily,
    city_columns,
)

print("\nProcessing completed.")
print(f"Hourly rows: {len(hourly_rows):,}")
print(f"Daily borough rows: {len(daily_by_borough):,}")
print(f"Daily citywide rows: {len(city_daily):,}")
print("Note: citywide summaries are estimates from five representative points.")
