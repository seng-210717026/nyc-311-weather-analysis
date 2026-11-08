"""Read-only M3 data-quality validation and STOP-check self-tests."""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from db import DEFAULT_DB_PATH
from clean_config import (
    PRECIPITATION_UPPER_FENCE_MM,
    WIND_SPEED_UPPER_FENCE_KMH,
)

# A borough with more than this share of missing coordinates gets a WARN.
# This is an analytical usability alert, not a rule for deleting records.
MISSING_COORDINATE_WARN_THRESHOLD = 0.10

# A snapshot older than this many days gets a freshness WARN.
MAX_SOURCE_AGE_DAYS = 7

WMO_CODES = {
    0, 1, 2, 3, 45, 48,
    51, 53, 55, 56, 57,
    61, 63, 65, 66, 67,
    71, 73, 75, 77,
    80, 81, 82, 85, 86,
    95, 96, 99,
}


def check_service_request_row_count(con):
    raw = con.execute(
        "SELECT COUNT(*) FROM service_requests"
    ).fetchone()[0]
    clean = con.execute(
        "SELECT COUNT(*) FROM service_requests_clean"
    ).fetchone()[0]

    status = "PASS" if raw == clean else "STOP"
    return status, f"raw={raw:,}; clean={clean:,}; equal={raw == clean}"


def check_weather_row_count(con):
    raw = con.execute(
        "SELECT COUNT(*) FROM weather_observations"
    ).fetchone()[0]
    clean = con.execute(
        "SELECT COUNT(*) FROM weather_observations_clean"
    ).fetchone()[0]

    status = "PASS" if raw == clean else "STOP"
    return status, f"raw={raw:,}; clean={clean:,}; equal={raw == clean}"


def check_foreign_keys(con):
    errors = con.execute("PRAGMA foreign_key_check").fetchall()

    if errors:
        return "STOP", f"{len(errors):,} foreign-key violation(s); examples={errors[:3]}"

    return "PASS", "PRAGMA foreign_key_check returned zero rows"


def check_service_request_values(con):
    bad = con.execute("""
        SELECT COUNT(*)
        FROM service_requests_clean
        WHERE
            -- A valid creation timestamp must be retained exactly.
            (
                created_at_utc_flag = 'ok'
                AND (
                    created_at_utc IS NULL
                    OR created_at_utc_raw IS NOT created_at_utc
                )
            )
            OR (
                created_at_utc_flag != 'ok'
                AND created_at_utc IS NOT NULL
            )

            -- Non-OK optional timestamps must not contain invented values.
            OR (
                closed_at_utc_flag = 'ok'
                AND (
                    closed_at_utc IS NULL
                    OR closed_at_utc_raw IS NOT closed_at_utc
                )
            )
            OR (
                closed_at_utc_flag != 'ok'
                AND closed_at_utc IS NOT NULL
            )
            OR (
                closed_at_utc IS NOT NULL
                AND created_at_utc IS NOT NULL
                AND julianday(closed_at_utc) < julianday(created_at_utc)
            )

            OR (
                due_at_utc_flag = 'ok'
                AND (
                    due_at_utc IS NULL
                    OR due_at_utc_raw IS NOT due_at_utc
                )
            )
            OR (
                due_at_utc_flag != 'ok'
                AND due_at_utc IS NOT NULL
            )
            OR (
                due_at_utc IS NOT NULL
                AND created_at_utc IS NOT NULL
                AND julianday(due_at_utc) < julianday(created_at_utc)
            )

            OR (
                resolution_action_updated_at_utc_flag = 'ok'
                AND (
                    resolution_action_updated_at_utc IS NULL
                    OR resolution_action_updated_at_utc_raw
                       IS NOT resolution_action_updated_at_utc
                )
            )
            OR (
                resolution_action_updated_at_utc_flag != 'ok'
                AND resolution_action_updated_at_utc IS NOT NULL
            )
            OR (
                resolution_action_updated_at_utc IS NOT NULL
                AND created_at_utc IS NOT NULL
                AND julianday(resolution_action_updated_at_utc)
                    < julianday(created_at_utc)
            )

            -- Coordinates must retain valid raw values or remain NULL.
            OR (
                latitude_flag = 'ok'
                AND (
                    latitude IS NULL
                    OR latitude_raw IS NOT latitude
                )
            )
            OR (
                latitude_flag != 'ok'
                AND latitude IS NOT NULL
            )
            OR (
                latitude IS NOT NULL
                AND latitude NOT BETWEEN -90 AND 90
            )

            OR (
                longitude_flag = 'ok'
                AND (
                    longitude IS NULL
                    OR longitude_raw IS NOT longitude
                )
            )
            OR (
                longitude_flag != 'ok'
                AND longitude IS NOT NULL
            )
            OR (
                longitude IS NOT NULL
                AND longitude NOT BETWEEN -180 AND 180
            )
    """).fetchone()[0]

    if bad:
        return "STOP", f"{bad:,} request row(s) violate timestamp or coordinate rules"

    return "PASS", "timestamps, chronology, raw-to-clean values and coordinate ranges are valid"


def check_weather_values(con):
    placeholders = ",".join("?" for _ in WMO_CODES)

    query = f"""
        SELECT COUNT(*)
        FROM weather_observations_clean
        WHERE
            -- Values that are valid or merely unusual must be retained.
            (
                temperature_2m_c_flag IN ('ok', 'unusual_low', 'unusual_high')
                AND temperature_2m_c_raw IS NOT temperature_2m_c
            )
            OR (
                relative_humidity_2m_pct_flag
                    IN ('ok', 'unusual_low', 'unusual_high')
                AND relative_humidity_2m_pct_raw
                    IS NOT relative_humidity_2m_pct
            )
            OR (
                relative_humidity_2m_pct_flag = 'invalid_range'
                AND relative_humidity_2m_pct IS NOT NULL
            )
            OR (
                precipitation_mm_flag IN ('ok', 'unusual_high')
                AND precipitation_mm_raw IS NOT precipitation_mm
            )
            OR (
                precipitation_mm_flag = 'invalid_negative'
                AND precipitation_mm IS NOT NULL
            )
            OR (
                weather_code_flag = 'ok'
                AND (
                    weather_code IS NULL
                    OR weather_code_raw IS NOT weather_code
                )
            )
            OR (
                weather_code_flag = 'invalid_code'
                AND weather_code IS NOT NULL
            )
            OR (
                wind_speed_10m_kmh_flag IN ('ok', 'unusual_high')
                AND wind_speed_10m_kmh_raw IS NOT wind_speed_10m_kmh
            )
            OR (
                wind_speed_10m_kmh_flag = 'invalid_negative'
                AND wind_speed_10m_kmh IS NOT NULL
            )
            OR (
                wind_direction_10m_degrees_flag = 'ok'
                AND wind_direction_10m_degrees_raw
                    IS NOT wind_direction_10m_degrees
            )
            OR (
                wind_direction_10m_degrees_flag = 'invalid_range'
                AND wind_direction_10m_degrees IS NOT NULL
            )
            OR (
                cloud_cover_pct_flag = 'ok'
                AND cloud_cover_pct_raw IS NOT cloud_cover_pct
            )
            OR (
                cloud_cover_pct_flag = 'invalid_range'
                AND cloud_cover_pct IS NOT NULL
            )

            -- A missing measurement must have a NULL cleaned value.
            OR (
                temperature_2m_c_flag = 'missing_not_reported'
                AND temperature_2m_c IS NOT NULL
            )
            OR (
                relative_humidity_2m_pct_flag = 'missing_not_reported'
                AND relative_humidity_2m_pct IS NOT NULL
            )
            OR (
                precipitation_mm_flag = 'missing_not_reported'
                AND precipitation_mm IS NOT NULL
            )
            OR (
                weather_code_flag = 'missing_not_reported'
                AND weather_code IS NOT NULL
            )
            OR (
                wind_speed_10m_kmh_flag = 'missing_not_reported'
                AND wind_speed_10m_kmh IS NOT NULL
            )
            OR (
                wind_direction_10m_degrees_flag = 'missing_not_reported'
                AND wind_direction_10m_degrees IS NOT NULL
            )
            OR (
                cloud_cover_pct_flag = 'missing_not_reported'
                AND cloud_cover_pct IS NOT NULL
            )

            -- Physical/domain checks.
            OR (
                relative_humidity_2m_pct IS NOT NULL
                AND relative_humidity_2m_pct NOT BETWEEN 0 AND 100
            )
            OR (
                precipitation_mm IS NOT NULL
                AND precipitation_mm < 0
            )
            OR (
                weather_code IS NOT NULL
                AND weather_code NOT IN ({placeholders})
            )
            OR (
                wind_speed_10m_kmh IS NOT NULL
                AND wind_speed_10m_kmh < 0
            )
            OR (
                wind_direction_10m_degrees IS NOT NULL
                AND wind_direction_10m_degrees NOT BETWEEN 0 AND 360
            )
            OR (
                cloud_cover_pct IS NOT NULL
                AND cloud_cover_pct NOT BETWEEN 0 AND 100
            )
    """

    bad = con.execute(query, tuple(sorted(WMO_CODES))).fetchone()[0]

    if bad:
        return "STOP", f"{bad:,} weather row(s) violate value, domain or raw-to-clean rules"

    # Confirm borough-specific IQR flags agree with the exact configured fences.
    cursor = con.execute("""
        SELECT
            b.borough_name,
            w.precipitation_mm,
            w.precipitation_mm_flag,
            w.wind_speed_10m_kmh,
            w.wind_speed_10m_kmh_flag
        FROM weather_observations_clean AS w
        JOIN weather_locations AS wl
          ON wl.weather_location_id = w.weather_location_id
        JOIN boroughs AS b
          ON b.borough_id = wl.borough_id
    """)

    threshold_mismatches = 0

    for borough, rain, rain_flag, wind, wind_flag in cursor:
        borough_key = borough.strip().upper()

        rain_fence = PRECIPITATION_UPPER_FENCE_MM.get(borough_key)
        wind_fence = WIND_SPEED_UPPER_FENCE_KMH.get(borough_key)

        if rain_fence is None or wind_fence is None:
            threshold_mismatches += 1
            continue

        expected_rain_flag = (
            rain is not None and rain > rain_fence
        )
        expected_wind_flag = (
            wind is not None and wind > wind_fence
        )

        if expected_rain_flag != (rain_flag == "unusual_high"):
            threshold_mismatches += 1

        if expected_wind_flag != (wind_flag == "unusual_high"):
            threshold_mismatches += 1

    if threshold_mismatches:
        return (
            "STOP",
            f"{threshold_mismatches:,} precipitation/wind anomaly flag(s) "
            "do not match the configured IQR fences",
        )

    return "PASS", (
        "weather domains, raw-to-clean values and borough-specific IQR flags are valid"
    )


def check_missing_coordinates_by_borough(con):
    rows = con.execute("""
        SELECT
            b.borough_name,
            COUNT(*) AS total_rows,
            SUM(
                CASE
                    WHEN c.latitude IS NULL OR c.longitude IS NULL THEN 1
                    ELSE 0
                END
            ) AS missing_rows
        FROM service_requests_clean AS c
        JOIN boroughs AS b ON b.borough_id = c.borough_id
        GROUP BY b.borough_name
        ORDER BY b.borough_name
    """).fetchall()

    warnings = []

    for borough, total, missing in rows:
        share = missing / total if total else 0

        if share > MISSING_COORDINATE_WARN_THRESHOLD:
            warnings.append(
                f"{borough}: {share:.2%} ({missing:,}/{total:,})"
            )

    if warnings:
        return "WARN", (
            f"coordinate missingness exceeds "
            f"{MISSING_COORDINATE_WARN_THRESHOLD:.0%} in: "
            + "; ".join(warnings)
        )

    return "PASS", (
        f"all boroughs are at or below "
        f"{MISSING_COORDINATE_WARN_THRESHOLD:.0%} missing coordinates"
    )


def check_coverage_freshness(con):
    rows = con.execute("""
        SELECT
            b.borough_name,
            MAX(c.created_local_date)
        FROM service_requests_clean AS c
        JOIN boroughs AS b ON b.borough_id = c.borough_id
        GROUP BY b.borough_name
        ORDER BY b.borough_name
    """).fetchall()

    if not rows:
        return "STOP", "no borough has service-request coverage"

    today = datetime.now(ZoneInfo("America/New_York")).date()
    warnings = []
    summaries = []

    for borough, latest in rows:
        if latest is None:
            warnings.append(f"{borough}: no dated requests")
            continue

        latest_date = datetime.strptime(latest, "%Y-%m-%d").date()
        age_days = (today - latest_date).days
        summaries.append(f"{borough}={latest} ({age_days} days old)")

        if age_days > MAX_SOURCE_AGE_DAYS:
            warnings.append(f"{borough}: {age_days} days old")

    if warnings:
        return "WARN", (
            f"latest date by borough: {'; '.join(summaries)}; "
            f"freshness threshold={MAX_SOURCE_AGE_DAYS} days; "
            f"stale/missing: {'; '.join(warnings)}"
        )

    return "PASS", "; ".join(summaries)


def check_project_specific_issues(con):
    row = con.execute("""
        SELECT
            COUNT(*) AS total_rows,
            SUM(CASE WHEN b.borough_name = 'UNSPECIFIED' THEN 1 ELSE 0 END),
            SUM(CASE WHEN c.created_at_utc_flag != 'ok' THEN 1 ELSE 0 END),
            SUM(
                CASE
                    WHEN c.due_at_utc_flag = 'missing_not_reported' THEN 1
                    ELSE 0
                END
            )
        FROM service_requests_clean AS c
        JOIN boroughs AS b ON b.borough_id = c.borough_id
    """).fetchone()

    total, unspecified, unresolved_created, missing_due = row

    unspecified = unspecified or 0
    unresolved_created = unresolved_created or 0
    missing_due = missing_due or 0
    due_share = missing_due / total if total else 0

    details = (
        f"UNSPECIFIED borough={unspecified:,}; "
        f"unresolved creation UTC={unresolved_created:,}; "
        f"missing due date={due_share:.2%} ({missing_due:,}/{total:,})"
    )

    if unspecified or unresolved_created or due_share > 0.95:
        return "WARN", (
            details
            + "; these records/fields limit borough-hour weather joins "
              "or due-date analysis"
        )

    return "PASS", details


def live_checks(con):
    return [
        ("STOP", "Service-request row count", check_service_request_row_count(con)),
        ("STOP", "Weather-observation row count", check_weather_row_count(con)),
        ("STOP", "Foreign-key integrity", check_foreign_keys(con)),
        ("STOP", "Service-request cleaned values", check_service_request_values(con)),
        ("STOP", "Weather cleaned values", check_weather_values(con)),
        ("WARN", "Coordinate missingness by borough", check_missing_coordinates_by_borough(con)),
        ("WARN", "Coverage freshness", check_coverage_freshness(con)),
        ("WARN", "Project-specific data limitations", check_project_specific_issues(con)),
    ]


def expect_stop(label, setup_sql, checker):
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys = ON")

    try:
        setup_sql(con)
        status, detail = checker(con)

        if status != "STOP":
            raise AssertionError(
                f"{label}: expected STOP, got {status}. Detail: {detail}"
            )

        print(f"PASS: {label} correctly returned STOP")

    finally:
        con.close()


def run_self_tests():
    """Demonstrate that every STOP check rejects an intentionally bad fixture."""

    def setup_request_count(con):
        con.executescript("""
            CREATE TABLE service_requests (unique_key TEXT PRIMARY KEY);
            CREATE TABLE service_requests_clean (unique_key TEXT PRIMARY KEY);
            INSERT INTO service_requests VALUES ('REQ-1');
        """)

    def setup_weather_count(con):
        con.executescript("""
            CREATE TABLE weather_observations (
                weather_location_id INTEGER,
                observed_at_utc TEXT
            );
            CREATE TABLE weather_observations_clean (
                weather_location_id INTEGER,
                observed_at_utc TEXT
            );
            INSERT INTO weather_observations VALUES (1, '2026-01-01T00:00:00Z');
        """)

    def setup_foreign_key(con):
        con.execute("PRAGMA foreign_keys = OFF")
        con.executescript("""
            CREATE TABLE parent_entity (id INTEGER PRIMARY KEY);
            CREATE TABLE child_entity (
                parent_id INTEGER REFERENCES parent_entity(id)
            );
            INSERT INTO child_entity VALUES (999);
        """)
        con.execute("PRAGMA foreign_keys = ON")

    def setup_service_values(con):
        con.executescript("""
            CREATE TABLE service_requests_clean (
                created_at_utc_raw TEXT,
                created_at_utc TEXT,
                created_at_utc_flag TEXT,
                closed_at_utc_raw TEXT,
                closed_at_utc TEXT,
                closed_at_utc_flag TEXT,
                due_at_utc_raw TEXT,
                due_at_utc TEXT,
                due_at_utc_flag TEXT,
                resolution_action_updated_at_utc_raw TEXT,
                resolution_action_updated_at_utc TEXT,
                resolution_action_updated_at_utc_flag TEXT,
                latitude_raw REAL,
                latitude REAL,
                latitude_flag TEXT,
                longitude_raw REAL,
                longitude REAL,
                longitude_flag TEXT
            );

            INSERT INTO service_requests_clean VALUES (
                '2026-01-01T10:00:00Z',
                NULL,
                'ok',
                NULL, NULL, 'missing_not_reported',
                NULL, NULL, 'missing_not_reported',
                NULL, NULL, 'missing_not_reported',
                NULL, NULL, 'missing_not_reported',
                NULL, NULL, 'missing_not_reported'
            );
        """)

    def setup_weather_values(con):
        con.executescript("""
            CREATE TABLE weather_observations_clean (
                temperature_2m_c_raw REAL,
                temperature_2m_c REAL,
                temperature_2m_c_flag TEXT,
                relative_humidity_2m_pct_raw REAL,
                relative_humidity_2m_pct REAL,
                relative_humidity_2m_pct_flag TEXT,
                precipitation_mm_raw REAL,
                precipitation_mm REAL,
                precipitation_mm_flag TEXT,
                weather_code_raw INTEGER,
                weather_code INTEGER,
                weather_code_flag TEXT,
                wind_speed_10m_kmh_raw REAL,
                wind_speed_10m_kmh REAL,
                wind_speed_10m_kmh_flag TEXT,
                wind_direction_10m_degrees_raw REAL,
                wind_direction_10m_degrees REAL,
                wind_direction_10m_degrees_flag TEXT,
                cloud_cover_pct_raw REAL,
                cloud_cover_pct REAL,
                cloud_cover_pct_flag TEXT
            );

            INSERT INTO weather_observations_clean VALUES (
                10, 10, 'ok',
                50, 50, 'ok',
                -1, -1, 'ok',
                0, 0, 'ok',
                5, 5, 'ok',
                180, 180, 'ok',
                50, 50, 'ok'
            );
        """)

    tests = [
        (
            "Service-request row-count STOP",
            setup_request_count,
            check_service_request_row_count,
        ),
        (
            "Weather-observation row-count STOP",
            setup_weather_count,
            check_weather_row_count,
        ),
        (
            "Foreign-key STOP",
            setup_foreign_key,
            check_foreign_keys,
        ),
        (
            "Service-request impossible-value STOP",
            setup_service_values,
            check_service_request_values,
        ),
        (
            "Weather impossible-value STOP",
            setup_weather_values,
            check_weather_values,
        ),
    ]

    print("M3 STOP-CHECK SELF-TESTS")
    print("-" * 65)

    for label, setup, checker in tests:
        expect_stop(label, setup, checker)

    print("\nALL STOP-CHECK SELF-TESTS PASSED")


def run_live_validation(db_path=DEFAULT_DB_PATH):
    db_path = Path(db_path)

    if not db_path.is_file():
        raise FileNotFoundError(
            f"Database not found: {db_path}"
        )

    # Read-only URI prevents accidental changes during validation.
    uri = db_path.resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.execute("PRAGMA foreign_keys = ON")

    try:
        print("M3 DATA QUALITY VALIDATION")
        print(f"Database: {db_path}")
        print("-" * 75)

        results = live_checks(con)
        stop_failures = 0
        warning_count = 0

        for severity, label, (status, detail) in results:
            print(f"[{status}] {label}: {detail}")

            if severity == "STOP" and status == "STOP":
                stop_failures += 1

            if status == "WARN":
                warning_count += 1

        print("-" * 75)

        if stop_failures:
            print(f"VALIDATION FAILED: {stop_failures} STOP check(s) failed.")
            return 1

        print(
            f"VALIDATION PASSED: all STOP checks passed; "
            f"WARN checks={warning_count}."
        )
        return 0

    finally:
        con.close()


if __name__ == "__main__":
    try:
        if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
            run_self_tests()
            sys.exit(0)

        if len(sys.argv) == 3 and sys.argv[1] == "--db":
            sys.exit(run_live_validation(Path(sys.argv[2])))

        if len(sys.argv) > 1:
            print("Usage: python3 src/validate.py [--self-test] [--db PATH]")
            sys.exit(2)

        sys.exit(run_live_validation())

    except Exception as exc:
        print(f"VALIDATION ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
