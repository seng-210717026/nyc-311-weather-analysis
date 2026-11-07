"""Build the M3 cleaned layer from the M2 SQLite tables.

M2 source tables are read-only inputs. All M3 DDL, mapping loads, deletes,
and inserts are executed in one transaction.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from db import connect
from clean_config import (
    BATCH_SIZE,
    PRECIPITATION_UPPER_FENCE_MM,
    WIND_SPEED_UPPER_FENCE_KMH,
)


SCHEMA_PATH = PROJECT_ROOT / "sql" / "clean_schema.sql"
MAPPING_DIR = PROJECT_ROOT / "data" / "mappings"

SERVICE_TABLE = "service_requests_clean"
WEATHER_TABLE = "weather_observations_clean"

CATEGORY_CSV = MAPPING_DIR / "category_alias_map.csv"
IDENTITY_CSV = MAPPING_DIR / "identity_alias_map.csv"

CATEGORY_COLUMNS = [
    "entity_type",
    "source_label",
    "canonical_label",
    "decided_by",
    "decided_at",
    "note",
]

IDENTITY_COLUMNS = [
    "entity_type",
    "source_id",
    "canonical_source_id",
    "decided_by",
    "decided_at",
    "note",
]

# Full WMO weather interpretation code domain used by Open-Meteo.
WMO_CODES = {
    0, 1, 2, 3, 45, 48,
    51, 53, 55, 56, 57,
    61, 63, 65, 66, 67,
    71, 73, 75, 77,
    80, 81, 82, 85, 86,
    95, 96, 99,
}

TIMESTAMP_FIELDS = [
    ("created_at_utc", "created_timestamp_status", False),
    ("closed_at_utc", "closed_timestamp_status", True),
    ("due_at_utc", "due_timestamp_status", True),
    (
        "resolution_action_updated_at_utc",
        "resolution_updated_timestamp_status",
        True,
    ),
]

COORDINATE_FIELDS = ["latitude", "longitude"]

WEATHER_FIELDS = [
    "temperature_2m_c",
    "relative_humidity_2m_pct",
    "precipitation_mm",
    "weather_code",
    "wind_speed_10m_kmh",
    "wind_direction_10m_degrees",
    "cloud_cover_pct",
]

WEATHER_RANGES = {
    "relative_humidity_2m_pct": (0, 100),
    "precipitation_mm": (0, None),
    "wind_speed_10m_kmh": (0, None),
    "wind_direction_10m_degrees": (0, 360),
    "cloud_cover_pct": (0, 100),
}

FLAG_ALIASES = {
    "ok": ("ok", "valid"),
    "missing": ("missing_not_reported", "missing"),
    "ambiguous": ("ambiguous_local_time", "ambiguous"),
    "nonexistent": ("nonexistent_local_time", "nonexistent"),
    "before_created": (
        "invalid_before_created",
        "before_created",
        "invalid_chronology",
    ),
    "invalid_range": ("invalid_range", "out_of_range", "invalid"),
    "invalid_negative": ("invalid_negative", "invalid_range", "out_of_range", "invalid"),
    "invalid_code": (
        "invalid_code",
        "invalid_domain",
        "unknown_code",
        "unsupported_code",
    ),
    "unusual_high": ("unusual_high", "high_outlier", "outlier_high"),
}


def quote_identifier(name: str) -> str:
    """Quote a fixed SQL identifier."""
    return '"' + name.replace('"', '""') + '"'


def table_columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [
        row[1]
        for row in con.execute(
            f"PRAGMA table_info({quote_identifier(table)})"
        )
    ]


def apply_schema_transactionally(con: sqlite3.Connection) -> None:
    """Execute the schema file statement-by-statement inside this transaction."""
    if not SCHEMA_PATH.is_file():
        raise FileNotFoundError(f"Missing schema file: {SCHEMA_PATH}")

    sql_text = SCHEMA_PATH.read_text(encoding="utf-8")
    buffer = ""

    for line in sql_text.splitlines(keepends=True):
        buffer += line

        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            buffer = ""

            if not statement:
                continue

            # db.connect() already enables foreign keys before BEGIN.
            if statement.upper().startswith("PRAGMA "):
                continue

            con.execute(statement)

    if buffer.strip():
        raise RuntimeError("The end of clean_schema.sql contains an incomplete SQL statement.")


def allowed_flags(
    con: sqlite3.Connection,
    table: str,
    flag_column: str,
) -> set[str]:
    """Read the flag's permitted values from its CHECK constraint."""
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()

    if row is None or row[0] is None:
        raise RuntimeError(f"Cannot inspect flag constraint for {table}.{flag_column}")

    pattern = (
        rf"\b{re.escape(flag_column)}\s+TEXT\s+NOT NULL\s+"
        rf"CHECK\s*\(\s*{re.escape(flag_column)}\s+IN\s*\((.*?)\)\s*\)"
    )
    match = re.search(pattern, row[0], flags=re.IGNORECASE | re.DOTALL)

    if not match:
        raise RuntimeError(
            f"Could not find an enumerated CHECK constraint for "
            f"{table}.{flag_column}"
        )

    values = set(re.findall(r"'([^']+)'", match.group(1)))

    if not values:
        raise RuntimeError(f"No allowed flag values found for {table}.{flag_column}")

    return values


def choose_flag(
    con: sqlite3.Connection,
    table: str,
    flag_column: str,
    category: str,
) -> str:
    permitted = allowed_flags(con, table, flag_column)

    for candidate in FLAG_ALIASES[category]:
        if candidate in permitted:
            return candidate

    raise RuntimeError(
        f"{table}.{flag_column} does not allow a flag for {category}. "
        f"Allowed values: {sorted(permitted)}"
    )


def parse_utc(value: str) -> datetime:
    """Parse the normalized UTC timestamp stored by M2."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def insert_sql(table: str, columns: list[str]) -> str:
    quoted = ", ".join(quote_identifier(column) for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    return (
        f"INSERT INTO {quote_identifier(table)} ({quoted}) "
        f"VALUES ({placeholders})"
    )


def destination_values(
    source: dict,
    destination_columns: list[str],
) -> dict:
    """Copy unchanged M2 fields and raw values into matching M3 columns."""
    values = {}

    for column in destination_columns:
        if column in source:
            values[column] = source[column]
        elif column.endswith("_raw") and column[:-4] in source:
            values[column] = source[column[:-4]]
        elif column.endswith("_clean") and column[:-6] in source:
            values[column] = source[column[:-6]]

    return values


def set_clean_value(
    values: dict,
    destination_columns: list[str],
    field: str,
    clean_value,
    flag_value: str,
) -> None:
    """Set the cleaned value and its flag, supporting either naming style."""
    clean_column = (
        field if field in destination_columns else f"{field}_clean"
    )
    raw_column = f"{field}_raw"
    flag_column = f"{field}_flag"

    required = [raw_column, clean_column, flag_column]
    missing = [column for column in required if column not in destination_columns]

    if missing:
        raise RuntimeError(
            f"Missing required M3 columns for {field}: {missing}"
        )

    values[clean_column] = clean_value
    values[flag_column] = flag_value


def validate_required_values(
    table: str,
    destination_columns: list[str],
    values: dict,
) -> list[str]:
    """Reject a target schema column that cannot be populated safely."""
    missing = [
        column
        for column in destination_columns
        if column not in values
    ]

    if missing:
        raise RuntimeError(
            f"Could not derive values for {table} columns: {missing}"
        )

    return destination_columns


def clean_service_request(
    con: sqlite3.Connection,
    source: dict,
    destination_columns: list[str],
) -> tuple[dict, dict]:
    values = destination_values(source, destination_columns)
    flags = {}

    created_raw = source["created_at_utc"]

    for field, status_field, check_chronology in TIMESTAMP_FIELDS:
        raw_value = source[field]
        status = source[status_field]
        flag_column = f"{field}_flag"

        if status == "missing":
            clean_value = None
            category = "missing"

        elif status == "ambiguous_local_time":
            clean_value = None
            category = "ambiguous"

        elif status == "nonexistent_local_time":
            clean_value = None
            category = "nonexistent"

        elif status == "normalized":
            if raw_value is None:
                raise RuntimeError(
                    f"{source['unique_key']}: {field} is NULL but status is normalized"
                )

            clean_value = raw_value
            category = "ok"

            if check_chronology and created_raw is not None:
                if parse_utc(raw_value) < parse_utc(created_raw):
                    clean_value = None
                    category = "before_created"

        else:
            raise RuntimeError(
                f"Unexpected {status_field} value: {status!r}"
            )

        flag_value = choose_flag(
            con, SERVICE_TABLE, flag_column, category
        )
        set_clean_value(
            values, destination_columns, field, clean_value, flag_value
        )
        flags[flag_column] = flag_value

    for field in COORDINATE_FIELDS:
        raw_value = source[field]
        flag_column = f"{field}_flag"

        if raw_value is None:
            clean_value = None
            category = "missing"
        elif not math.isfinite(float(raw_value)):
            clean_value = None
            category = "invalid_range"
        elif field == "latitude" and not -90 <= raw_value <= 90:
            clean_value = None
            category = "invalid_range"
        elif field == "longitude" and not -180 <= raw_value <= 180:
            clean_value = None
            category = "invalid_range"
        else:
            clean_value = raw_value
            category = "ok"

        flag_value = choose_flag(
            con, SERVICE_TABLE, flag_column, category
        )
        set_clean_value(
            values, destination_columns, field, clean_value, flag_value
        )
        flags[flag_column] = flag_value

    validate_required_values(SERVICE_TABLE, destination_columns, values)
    return values, flags


def clean_weather_observation(
    con: sqlite3.Connection,
    source: dict,
    destination_columns: list[str],
    borough_name: str,
) -> tuple[dict, dict]:
    values = destination_values(source, destination_columns)
    flags = {}

    borough_key = borough_name.strip().upper()

    for field in WEATHER_FIELDS:
        raw_value = source[field]
        flag_column = f"{field}_flag"

        if raw_value is None:
            clean_value = None
            category = "missing"

        elif field == "weather_code":
            if int(raw_value) not in WMO_CODES:
                clean_value = None
                category = "invalid_code"
            else:
                clean_value = raw_value
                category = "ok"

        else:
            numeric_value = float(raw_value)

            if not math.isfinite(numeric_value):
                clean_value = None
                category = "invalid_range"

            elif (
                field in {"precipitation_mm", "wind_speed_10m_kmh"}
                and numeric_value < 0
            ):
                clean_value = None
                category = "invalid_negative"

            elif field in WEATHER_RANGES:
                lower, upper = WEATHER_RANGES[field]
                invalid_lower = lower is not None and numeric_value < lower
                invalid_upper = upper is not None and numeric_value > upper

                if invalid_lower or invalid_upper:
                    clean_value = None
                    category = "invalid_range"
                else:
                    clean_value = raw_value
                    category = "ok"
            else:
                clean_value = raw_value
                category = "ok"

        # Robust IQR fences are anomaly flags only: retain the original value.
        if clean_value is not None and field == "precipitation_mm":
            fence = PRECIPITATION_UPPER_FENCE_MM.get(borough_key)
            if fence is None:
                raise RuntimeError(
                    f"No precipitation threshold configured for {borough_name!r}"
                )
            if float(clean_value) > fence:
                category = "unusual_high"

        if clean_value is not None and field == "wind_speed_10m_kmh":
            fence = WIND_SPEED_UPPER_FENCE_KMH.get(borough_key)
            if fence is None:
                raise RuntimeError(
                    f"No wind threshold configured for {borough_name!r}"
                )
            if float(clean_value) > fence:
                category = "unusual_high"

        flag_value = choose_flag(
            con, WEATHER_TABLE, flag_column, category
        )
        set_clean_value(
            values, destination_columns, field, clean_value, flag_value
        )
        flags[flag_column] = flag_value

    validate_required_values(WEATHER_TABLE, destination_columns, values)
    return values, flags


def load_mapping_csv(
    con: sqlite3.Connection,
    table: str,
    path: Path,
    expected_columns: list[str],
) -> int:
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing mapping CSV: {path}. Create the required header-only file first."
        )

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        if reader.fieldnames != expected_columns:
            raise RuntimeError(
                f"{path.name} header must be exactly: {','.join(expected_columns)}"
            )

        rows = []
        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise RuntimeError(
                    f"Unexpected extra CSV fields in {path.name}, line {line_number}"
                )

            if any(row.get(column) is None for column in expected_columns):
                raise RuntimeError(
                    f"Missing CSV field in {path.name}, line {line_number}"
                )

            rows.append(tuple(row[column] for column in expected_columns))

    if rows:
        columns = ", ".join(quote_identifier(c) for c in expected_columns)
        placeholders = ", ".join("?" for _ in expected_columns)
        con.executemany(
            f"INSERT INTO {quote_identifier(table)} ({columns}) "
            f"VALUES ({placeholders})",
            rows,
        )

    return len(rows)


def count_unmatched_mappings(con: sqlite3.Connection) -> tuple[int, int]:
    """Count mapping labels/IDs that do not resolve to existing M2 entities."""
    category_lookup = {
        "agency_code": ("agencies", ("agency_code",)),
        "agency_name": ("agencies", ("agency_name",)),
        "borough_name": ("boroughs", ("borough_name",)),
        "complaint_type": (
            "complaint_types",
            ("complaint_type", "complaint_type_name"),
        ),
        "status_name": (
            "request_statuses",
            ("status_name", "request_status"),
        ),
        "channel_name": (
            "submission_channels",
            ("channel_name", "submission_channel"),
        ),
        "location_code": ("weather_locations", ("location_code",)),
    }

    category_unmatched = 0

    category_rows = con.execute(
        "SELECT entity_type, source_label, canonical_label "
        "FROM category_alias_map"
    ).fetchall()

    for entity_type, source_label, canonical_label in category_rows:
        if entity_type not in category_lookup:
            raise RuntimeError(
                f"Unsupported category mapping type: {entity_type}"
            )

        table, candidates = category_lookup[entity_type]
        available = set(table_columns(con, table))
        column = next((c for c in candidates if c in available), None)

        if column is None:
            raise RuntimeError(
                f"Cannot find the label column for mapping type {entity_type}"
            )

        existing = {
            str(row[0])
            for row in con.execute(
                f"SELECT {quote_identifier(column)} FROM {quote_identifier(table)}"
            )
        }

        if str(source_label) not in existing or str(canonical_label) not in existing:
            category_unmatched += 1

    identity_lookup = {
        "request_service": ("service_requests", "unique_key"),
        "agency": ("agencies", "agency_id"),
        "borough": ("boroughs", "borough_id"),
        "complaint_type": ("complaint_types", "complaint_type_id"),
        "request_status": ("request_statuses", "status_id"),
        "submission_channel": ("submission_channels", "channel_id"),
        "weather_location": ("weather_locations", "weather_location_id"),
    }

    identity_unmatched = 0

    identity_rows = con.execute(
        "SELECT entity_type, source_id, canonical_source_id "
        "FROM identity_alias_map"
    ).fetchall()

    for entity_type, source_id, canonical_source_id in identity_rows:
        if entity_type not in identity_lookup:
            raise RuntimeError(
                f"Unsupported identity mapping type: {entity_type}"
            )

        table, key_column = identity_lookup[entity_type]
        existing = {
            str(row[0])
            for row in con.execute(
                f"SELECT {quote_identifier(key_column)} "
                f"FROM {quote_identifier(table)}"
            )
        }

        if (
            str(source_id) not in existing
            or str(canonical_source_id) not in existing
        ):
            identity_unmatched += 1

    return category_unmatched, identity_unmatched


def process_service_requests(
    con: sqlite3.Connection,
    flag_counts: dict,
) -> int:
    columns = table_columns(con, SERVICE_TABLE)
    cursor = con.execute("SELECT * FROM service_requests")
    statement = insert_sql(SERVICE_TABLE, columns)

    processed = 0
    batch = []

    while True:
        source_rows = cursor.fetchmany(BATCH_SIZE)
        if not source_rows:
            break

        for row in source_rows:
            source = dict(row)
            values, flags = clean_service_request(con, source, columns)
            batch.append(tuple(values[column] for column in columns))

            for flag_column, flag_value in flags.items():
                flag_counts[(SERVICE_TABLE, flag_column)][flag_value] += 1

        con.executemany(statement, batch)
        processed += len(batch)
        batch.clear()

        if processed % 500_000 == 0:
            print(f"Service requests processed: {processed:,}")

    return processed


def process_weather_observations(
    con: sqlite3.Connection,
    flag_counts: dict,
) -> int:
    columns = table_columns(con, WEATHER_TABLE)
    statement = insert_sql(WEATHER_TABLE, columns)

    borough_by_location = {
        row["weather_location_id"]: row["borough_name"]
        for row in con.execute(
            """
            SELECT wl.weather_location_id, b.borough_name
            FROM weather_locations AS wl
            JOIN boroughs AS b ON b.borough_id = wl.borough_id
            """
        )
    }

    cursor = con.execute("SELECT * FROM weather_observations")
    processed = 0
    batch = []

    while True:
        source_rows = cursor.fetchmany(BATCH_SIZE)
        if not source_rows:
            break

        for row in source_rows:
            source = dict(row)
            location_id = source["weather_location_id"]

            if location_id not in borough_by_location:
                raise RuntimeError(
                    f"No borough found for weather location {location_id}"
                )

            borough_name = borough_by_location[location_id]
            values, flags = clean_weather_observation(
                con, source, columns, borough_name
            )

            batch.append(tuple(values[column] for column in columns))

            for flag_column, flag_value in flags.items():
                flag_counts[(WEATHER_TABLE, flag_column)][flag_value] += 1

        con.executemany(statement, batch)
        processed += len(batch)
        batch.clear()

    return processed


def run(db_path: str | Path | None = None) -> None:
    con = connect(db_path)
    con.row_factory = sqlite3.Row
    flag_counts = defaultdict(Counter)

    try:
        if con.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise RuntimeError("SQLite foreign-key enforcement is not enabled.")

        # One transaction covers schema creation, mapping loads, and clean rebuild.
        con.execute("BEGIN IMMEDIATE")

        # Recreate this M3 output table transactionally so updated flag
        # constraints in clean_schema.sql also apply to an existing database.
        # This does not modify any M2 source table.
        con.execute("DROP TABLE IF EXISTS weather_observations_clean")

        apply_schema_transactionally(con)

        required_tables = [
            "service_requests",
            "weather_observations",
            "boroughs",
            "weather_locations",
            SERVICE_TABLE,
            WEATHER_TABLE,
            "category_alias_map",
            "identity_alias_map",
        ]

        existing_tables = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing_tables = [
            table for table in required_tables
            if table not in existing_tables
        ]

        if missing_tables:
            raise RuntimeError(f"Required tables are missing: {missing_tables}")

        raw_request_count = con.execute(
            "SELECT COUNT(*) FROM service_requests"
        ).fetchone()[0]
        raw_weather_count = con.execute(
            "SELECT COUNT(*) FROM weather_observations"
        ).fetchone()[0]

        # Only M3 output and mapping tables are cleared. M2 source tables are untouched.
        con.execute("DELETE FROM service_requests_clean")
        con.execute("DELETE FROM weather_observations_clean")
        con.execute("DELETE FROM category_alias_map")
        con.execute("DELETE FROM identity_alias_map")

        category_mappings = load_mapping_csv(
            con,
            "category_alias_map",
            CATEGORY_CSV,
            CATEGORY_COLUMNS,
        )
        identity_mappings = load_mapping_csv(
            con,
            "identity_alias_map",
            IDENTITY_CSV,
            IDENTITY_COLUMNS,
        )

        request_count = process_service_requests(con, flag_counts)
        weather_count = process_weather_observations(con, flag_counts)

        clean_request_count = con.execute(
            "SELECT COUNT(*) FROM service_requests_clean"
        ).fetchone()[0]
        clean_weather_count = con.execute(
            "SELECT COUNT(*) FROM weather_observations_clean"
        ).fetchone()[0]

        if raw_request_count != clean_request_count:
            raise RuntimeError(
                f"Request row-count mismatch: raw={raw_request_count}, "
                f"clean={clean_request_count}"
            )

        if raw_weather_count != clean_weather_count:
            raise RuntimeError(
                f"Weather row-count mismatch: raw={raw_weather_count}, "
                f"clean={clean_weather_count}"
            )

        fk_errors = con.execute("PRAGMA foreign_key_check").fetchall()
        if fk_errors:
            raise RuntimeError(
                f"Foreign-key check failed; first errors: {fk_errors[:10]}"
            )

        category_unmatched, identity_unmatched = count_unmatched_mappings(con)

        # No category or identity alias has been approved in the profiling stage.
        # Header-only mapping files are therefore intentional.
        con.commit()

        print("\nM3 CLEANING COMPLETED")
        print(f"Service requests: {request_count:,}")
        print(f"Weather observations: {weather_count:,}")
        print(
            "Mapping rows loaded: "
            f"category={category_mappings}, identity={identity_mappings}"
        )
        print(
            "Unmatched mapping entries: "
            f"category={category_unmatched}, identity={identity_unmatched}"
        )

        print("\nFLAG COUNTS")
        for (table, flag_column), counts in sorted(flag_counts.items()):
            summary = ", ".join(
                f"{flag}={count:,}" for flag, count in sorted(counts.items())
            )
            print(f"{table}.{flag_column}: {summary}")

        print("\nForeign key check: PASS")
        print("Raw M2 tables were not modified.")
        print("Transaction committed.")

    except Exception:
        if con.in_transaction:
            con.rollback()
        raise

    finally:
        con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build the M3 cleaned layer from M2 SQLite tables."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Optional SQLite database path (defaults to the project database).",
    )
    args = parser.parse_args()

    try:
        run(args.db)
    except Exception as exc:
        print(f"\nM3 CLEANING FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
