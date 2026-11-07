"""Test that each STOP check makes the validator process exit non-zero."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "sql" / "clean_schema.sql"
VALIDATOR = ROOT / "src" / "validate.py"

PARENT_SCHEMA = """
CREATE TABLE agencies (
    agency_id INTEGER PRIMARY KEY
) STRICT;

CREATE TABLE boroughs (
    borough_id INTEGER PRIMARY KEY,
    borough_name TEXT NOT NULL UNIQUE
) STRICT;

CREATE TABLE complaint_types (
    complaint_type_id INTEGER PRIMARY KEY
) STRICT;

CREATE TABLE request_statuses (
    status_id INTEGER PRIMARY KEY
) STRICT;

CREATE TABLE submission_channels (
    channel_id INTEGER PRIMARY KEY
) STRICT;

CREATE TABLE weather_locations (
    weather_location_id INTEGER PRIMARY KEY,
    borough_id INTEGER NOT NULL UNIQUE
        REFERENCES boroughs(borough_id)
) STRICT;

CREATE TABLE service_requests (
    unique_key TEXT PRIMARY KEY NOT NULL
) STRICT;

CREATE TABLE weather_observations (
    weather_location_id INTEGER NOT NULL
        REFERENCES weather_locations(weather_location_id),
    observed_at_utc TEXT NOT NULL,
    PRIMARY KEY (weather_location_id, observed_at_utc)
) STRICT;
"""


def insert_dict(con, table, values):
    columns = list(values)
    names = ", ".join(f'"{name}"' for name in columns)
    placeholders = ", ".join("?" for _ in columns)

    con.execute(
        f'INSERT INTO "{table}" ({names}) VALUES ({placeholders})',
        tuple(values[name] for name in columns),
    )


def create_valid_database(db_path: Path):
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")

    try:
        con.executescript(PARENT_SCHEMA)

        # Add the actual M3 cleaned and mapping table definitions.
        con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

        con.execute("INSERT INTO agencies VALUES (1)")
        con.execute("INSERT INTO boroughs VALUES (1, 'BRONX')")
        con.execute("INSERT INTO complaint_types VALUES (1)")
        con.execute("INSERT INTO request_statuses VALUES (1)")
        con.execute("INSERT INTO submission_channels VALUES (1)")
        con.execute("INSERT INTO weather_locations VALUES (1, 1)")

        con.execute(
            "INSERT INTO service_requests VALUES (?)",
            ("REQ-1",),
        )

        con.execute(
            """
            INSERT INTO weather_observations
                (weather_location_id, observed_at_utc)
            VALUES (?, ?)
            """,
            (1, "2026-01-01T15:00:00Z"),
        )

        request = {
            "unique_key": "REQ-1",
            "agency_id": 1,
            "borough_id": 1,
            "complaint_type_id": 1,
            "status_id": 1,
            "channel_id": 1,
            "created_date_source": "2026-01-01T10:00:00",
            "created_local_date": "2026-01-01",
            "created_local_hour": 10,
            "created_at_utc_raw": "2026-01-01T15:00:00Z",
            "created_at_utc": "2026-01-01T15:00:00Z",
            "created_at_utc_flag": "ok",
            "closed_date_source": None,
            "closed_at_utc_raw": None,
            "closed_at_utc": None,
            "closed_at_utc_flag": "missing_not_reported",
            "due_date_source": "2026-01-02T10:00:00",
            "due_at_utc_raw": "2026-01-02T15:00:00Z",
            "due_at_utc": "2026-01-02T15:00:00Z",
            "due_at_utc_flag": "ok",
            "resolution_action_updated_date_source": None,
            "resolution_action_updated_at_utc_raw": None,
            "resolution_action_updated_at_utc": None,
            "resolution_action_updated_at_utc_flag": "missing_not_reported",
            "latitude_raw": 40.7,
            "latitude": 40.7,
            "latitude_flag": "ok",
            "longitude_raw": -73.9,
            "longitude": -73.9,
            "longitude_flag": "ok",
            "retrieved_at": "2026-11-07T12:00:00Z",
        }
        insert_dict(con, "service_requests_clean", request)

        weather = {
            "weather_location_id": 1,
            "observed_at_utc": "2026-01-01T15:00:00Z",
            "temperature_2m_c_raw": 10.0,
            "temperature_2m_c": 10.0,
            "temperature_2m_c_flag": "ok",
            "relative_humidity_2m_pct_raw": 50.0,
            "relative_humidity_2m_pct": 50.0,
            "relative_humidity_2m_pct_flag": "ok",
            "precipitation_mm_raw": 0.0,
            "precipitation_mm": 0.0,
            "precipitation_mm_flag": "ok",
            "weather_code_raw": 0,
            "weather_code": 0,
            "weather_code_flag": "ok",
            "wind_speed_10m_kmh_raw": 5.0,
            "wind_speed_10m_kmh": 5.0,
            "wind_speed_10m_kmh_flag": "ok",
            "wind_direction_10m_degrees_raw": 180.0,
            "wind_direction_10m_degrees": 180.0,
            "wind_direction_10m_degrees_flag": "ok",
            "cloud_cover_pct_raw": 30.0,
            "cloud_cover_pct": 30.0,
            "cloud_cover_pct_flag": "ok",
            "retrieved_at": "2026-11-07T12:00:00Z",
        }
        insert_dict(con, "weather_observations_clean", weather)

        con.commit()

    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def mutate_request_row_count(db_path):
    with sqlite3.connect(db_path) as con:
        con.execute("DELETE FROM service_requests_clean")


def mutate_weather_row_count(db_path):
    with sqlite3.connect(db_path) as con:
        con.execute("DELETE FROM weather_observations_clean")


def mutate_foreign_key(db_path):
    con = sqlite3.connect(db_path)
    try:
        con.execute("PRAGMA foreign_keys = OFF")
        con.execute(
            "UPDATE service_requests_clean SET agency_id = 999 WHERE unique_key = 'REQ-1'"
        )
        con.commit()
    finally:
        con.close()


def mutate_service_value(db_path):
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            UPDATE service_requests_clean
            SET created_at_utc = '2026-01-01T14:00:00Z'
            WHERE unique_key = 'REQ-1'
            """
        )


def mutate_weather_value(db_path):
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            UPDATE weather_observations_clean
            SET weather_code = 999
            WHERE weather_location_id = 1
            """
        )


TESTS = [
    (
        "Service-request row-count STOP",
        "[STOP] Service-request row count:",
        mutate_request_row_count,
    ),
    (
        "Weather-observation row-count STOP",
        "[STOP] Weather-observation row count:",
        mutate_weather_row_count,
    ),
    (
        "Foreign-key integrity STOP",
        "[STOP] Foreign-key integrity:",
        mutate_foreign_key,
    ),
    (
        "Service-request impossible-value STOP",
        "[STOP] Service-request cleaned values:",
        mutate_service_value,
    ),
    (
        "Weather impossible-value STOP",
        "[STOP] Weather cleaned values:",
        mutate_weather_value,
    ),
]


def run_one_test(label, expected_marker, mutation, temp_dir):
    db_path = temp_dir / f"{mutation.__name__}.sqlite"
    create_valid_database(db_path)

    mutation(db_path)

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--db", str(db_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 1:
        raise AssertionError(
            f"{label}: expected exit code 1, got {result.returncode}\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    if expected_marker not in result.stdout:
        raise AssertionError(
            f"{label}: expected STOP marker was not printed.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    print(f"PASS: {label}; exit code={result.returncode}")


def main():
    print("M3 STOP PROCESS EXIT-CODE TESTS")
    print("-" * 75)

    with tempfile.TemporaryDirectory(prefix="m3_validate_stop_") as folder:
        temp_dir = Path(folder)

        for label, marker, mutation in TESTS:
            run_one_test(label, marker, mutation, temp_dir)

    print("-" * 75)
    print("ALL FIVE STOP TESTS EXITED WITH CODE 1.")
    print("Temporary test databases were removed.")


if __name__ == "__main__":
    main()
