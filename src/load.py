"""Transactional loader for NYC 311 and Open-Meteo raw JSON data."""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from src.db import connect
except ModuleNotFoundError:
    from db import connect


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RAW_DIR = ROOT / "data" / "raw"
DEFAULT_DB_PATH = ROOT / "data" / "nyc311_weather.db"
SCHEMA_PATH = ROOT / "sql" / "schema.sql"

NY_TZ = ZoneInfo("America/New_York")
UTC = timezone.utc

START_DATE = date(2025, 10, 12)
END_DATE = date(2026, 10, 11)

BOROUGHS = [
    ("Bronx", 40.8448, -73.8648),
    ("Brooklyn", 40.6782, -73.9442),
    ("Manhattan", 40.7831, -73.9712),
    ("Queens", 40.7282, -73.7949),
    ("Staten Island", 40.5795, -74.1502),
]

NYC_FILENAME_RE = re.compile(
    r"^(?P<timestamp>\d{8}T\d{6}(?:_\d{6})?Z)_offset_\d+\.json$"
)
WEATHER_FILENAME_RE = re.compile(
    r"^(?P<timestamp>\d{8}T\d{6}Z)_weather_unix\.json$"
)

WEATHER_VARIABLES = [
    ("temperature_2m", "temperature_2m_c"),
    ("relative_humidity_2m", "relative_humidity_2m_pct"),
    ("precipitation", "precipitation_mm"),
    ("weather_code", "weather_code"),
    ("wind_speed_10m", "wind_speed_10m_kmh"),
    ("wind_direction_10m", "wind_direction_10m_degrees"),
    ("cloud_cover", "cloud_cover_pct"),
]

OPTIONAL_TEXT_FIELDS = [
    "descriptor",
    "descriptor_2",
    "location_type",
    "incident_zip",
    "incident_address",
    "street_name",
    "cross_street_1",
    "cross_street_2",
    "intersection_street_1",
    "intersection_street_2",
    "address_type",
    "city",
    "landmark",
    "community_board",
    "council_district",
    "police_precinct",
    "bbl",
    "park_facility_name",
    "park_borough",
    "facility_type",
    "resolution_description",
    "road_ramp",
    "bridge_highway_direction",
    "bridge_highway_name",
    "bridge_highway_segment",
    "taxi_company_borough",
    "taxi_pick_up_location",
    "vehicle_type",
]

NUMERIC_REQUEST_FIELDS = [
    "x_coordinate_state_plane",
    "y_coordinate_state_plane",
    "latitude",
    "longitude",
]

REQUEST_COLUMNS = [
    "unique_key",
    "created_date_source",
    "created_at_utc",
    "created_local_date",
    "created_local_hour",
    "created_timestamp_status",
    "agency_id",
    "borough_id",
    "complaint_type_id",
    "status_id",
    "channel_id",
    "closed_date_source",
    "closed_at_utc",
    "closed_timestamp_status",
    "due_date_source",
    "due_at_utc",
    "due_timestamp_status",
    "resolution_action_updated_date_source",
    "resolution_action_updated_at_utc",
    "resolution_updated_timestamp_status",
    *OPTIONAL_TEXT_FIELDS[:],
    "x_coordinate_state_plane",
    "y_coordinate_state_plane",
    "latitude",
    "longitude",
    "location_json",
    "retrieved_at",
]

# Fixed identifiers are defined in code; source values always use parameters.
DIMENSION_CONFIG = {
    "agencies": ("agency_id", "agency_code", ("agency_name",)),
    "boroughs": ("borough_id", "borough_name", ()),
    "complaint_types": (
        "complaint_type_id",
        "complaint_type",
        (),
    ),
    "request_statuses": ("status_id", "status_name", ()),
    "submission_channels": ("channel_id", "channel_name", ()),
}

COUNTED_TABLES = [
    "agencies",
    "boroughs",
    "complaint_types",
    "request_statuses",
    "submission_channels",
    "weather_locations",
    "service_requests",
    "weather_observations",
    "quarantine_records",
]

INDEX_STATEMENTS = [
    """
    CREATE INDEX IF NOT EXISTS idx_requests_borough_date_hour
    ON service_requests (
        borough_id, created_local_date, created_local_hour
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_requests_complaint_date
    ON service_requests (complaint_type_id, created_local_date)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_requests_created_utc
    ON service_requests (created_at_utc)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_requests_local_date
    ON service_requests (created_local_date)
    """,
]

QUARANTINE_SQL = """
    INSERT INTO quarantine_records (
        source_kind, source_file, source_row_number,
        source_record_key, reason_code, reason_detail,
        raw_record_json, retrieved_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT (
        source_kind, source_file, source_row_number, reason_code
    ) DO UPDATE SET
        source_record_key = excluded.source_record_key,
        reason_detail = excluded.reason_detail,
        raw_record_json = excluded.raw_record_json,
        retrieved_at = excluded.retrieved_at
    WHERE excluded.retrieved_at > quarantine_records.retrieved_at
"""


class LoadError(Exception):
    """Raised when a source file cannot be safely loaded."""


class RecordValidationError(Exception):
    """Raised when an individual source record cannot be normalized."""

    def __init__(self, reason_code: str, detail: str):
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail


def canonical_utc(value: datetime) -> str:
    """Format an aware datetime as ISO 8601 UTC with microseconds."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("canonical_utc requires a timezone-aware datetime.")

    return (
        value.astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def parse_retrieval_time(path: Path, source_kind: str) -> str:
    """Derive retrieval time from the preserved raw filename."""
    if source_kind == "nyc311":
        match = NYC_FILENAME_RE.fullmatch(path.name)
        formats = (
            "%Y%m%dT%H%M%S_%fZ",
            "%Y%m%dT%H%M%SZ",
        )
    elif source_kind == "weather":
        match = WEATHER_FILENAME_RE.fullmatch(path.name)
        formats = ("%Y%m%dT%H%M%SZ",)
    else:
        raise ValueError(f"Unsupported source kind: {source_kind}")

    if not match:
        raise LoadError(
            f"Cannot derive retrieval timestamp from filename: {path.name}"
        )

    stamp = match.group("timestamp")

    for fmt in formats:
        try:
            parsed = datetime.strptime(stamp, fmt).replace(tzinfo=UTC)
            return canonical_utc(parsed)
        except ValueError:
            continue

    raise LoadError(f"Invalid timestamp in source filename: {path.name}")


def normalize_source_timestamp(
    raw_value: object,
    field_name: str,
    stats: Counter,
    *,
    required: bool = False,
) -> dict:
    """Normalize a source timestamp while identifying DST edge cases."""
    if raw_value is None or (
        isinstance(raw_value, str) and not raw_value.strip()
    ):
        if required:
            raise RecordValidationError(
                f"missing_{field_name}",
                f"Required timestamp {field_name} is missing.",
            )

        stats[f"timestamp_{field_name}_missing"] += 1
        return {
            "source": None,
            "utc": None,
            "status": "missing",
            "local": None,
        }

    if not isinstance(raw_value, str):
        raise RecordValidationError(
            f"invalid_{field_name}",
            f"{field_name} must be a source timestamp string.",
        )

    source_text = raw_value
    parse_text = raw_value.strip()

    if parse_text.endswith("Z"):
        parse_text = parse_text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(parse_text)
    except ValueError as exc:
        raise RecordValidationError(
            f"invalid_{field_name}",
            f"Cannot parse {field_name}: {raw_value!r}",
        ) from exc

    # An explicit offset, if supplied, determines the instant.
    if parsed.tzinfo is not None and parsed.utcoffset() is not None:
        local = parsed.astimezone(NY_TZ)
        result = {
            "source": source_text,
            "utc": canonical_utc(parsed),
            "status": "normalized",
            "local": local,
        }
        stats[f"timestamp_{field_name}_normalized"] += 1
        return result

    # The NYC 311 source normally provides a local time without an offset.
    local_naive = parsed
    fold0 = local_naive.replace(tzinfo=NY_TZ, fold=0)
    fold1 = local_naive.replace(tzinfo=NY_TZ, fold=1)

    back0 = (
        fold0.astimezone(UTC)
        .astimezone(NY_TZ)
        .replace(tzinfo=None)
    )
    back1 = (
        fold1.astimezone(UTC)
        .astimezone(NY_TZ)
        .replace(tzinfo=None)
    )

    valid0 = back0 == local_naive
    valid1 = back1 == local_naive

    if (
        valid0
        and valid1
        and fold0.utcoffset() != fold1.utcoffset()
    ):
        status = "ambiguous_local_time"
        utc_value = None
        local_value = local_naive
    elif not valid0 and not valid1:
        status = "nonexistent_local_time"
        utc_value = None
        local_value = local_naive
    else:
        status = "normalized"
        utc_value = canonical_utc(fold0)
        local_value = local_naive

    stats[f"timestamp_{field_name}_{status}"] += 1

    return {
        "source": source_text,
        "utc": utc_value,
        "status": status,
        "local": local_value,
    }


def required_label(
    record: dict,
    field: str,
    *,
    uppercase: bool = True,
) -> str:
    """Read a required categorical field without inventing a value."""
    value = record.get(field)

    if not isinstance(value, str) or not value.strip():
        raise RecordValidationError(
            f"missing_required_field_{field}",
            f"Required field {field} is missing or is not text.",
        )

    result = value.strip()
    return result.upper() if uppercase else result


def optional_text(
    record: dict,
    field: str,
    stats: Counter,
) -> str | None:
    """Convert an optional source field to nullable text."""
    value = record.get(field)

    if value is None:
        return None

    if isinstance(value, str):
        result = value.strip()
        if not result:
            stats["empty_strings_converted_to_null"] += 1
            return None
        return result

    if isinstance(value, bool):
        stats["non_string_text_values_converted"] += 1
        return str(value)

    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise RecordValidationError(
                f"invalid_text_field_{field}",
                f"Non-finite value in text field {field}.",
            )
        stats["non_string_text_values_converted"] += 1
        return str(value)

    raise RecordValidationError(
        f"invalid_text_field_{field}",
        f"Unsupported value type in text field {field}.",
    )


def optional_number(
    record: dict,
    field: str,
    stats: Counter,
) -> float | None:
    """Convert an optional numeric source value and validate its range."""
    raw_value = record.get(field)

    if raw_value is None:
        stats[f"missing_numeric_{field}"] += 1
        return None

    if isinstance(raw_value, str):
        raw_text = raw_value.strip()
        if not raw_text:
            stats[f"missing_numeric_{field}"] += 1
            stats["empty_strings_converted_to_null"] += 1
            return None
        try:
            value = float(raw_text)
        except ValueError as exc:
            raise RecordValidationError(
                f"invalid_numeric_{field}",
                f"Cannot convert {field} value {raw_value!r} to a number.",
            ) from exc
        stats["numeric_strings_converted"] += 1

    elif isinstance(raw_value, bool):
        raise RecordValidationError(
            f"invalid_numeric_{field}",
            f"Boolean value found in numeric field {field}.",
        )

    elif isinstance(raw_value, (int, float)):
        value = float(raw_value)

    else:
        raise RecordValidationError(
            f"invalid_numeric_{field}",
            f"Unsupported value type in numeric field {field}.",
        )

    if not math.isfinite(value):
        raise RecordValidationError(
            f"non_finite_numeric_{field}",
            f"Non-finite number found in {field}.",
        )

    if field == "latitude" and not -90 <= value <= 90:
        raise RecordValidationError(
            f"out_of_range_{field}",
            f"Latitude outside [-90, 90]: {value}",
        )

    if field == "longitude" and not -180 <= value <= 180:
        raise RecordValidationError(
            f"out_of_range_{field}",
            f"Longitude outside [-180, 180]: {value}",
        )

    return value


def normalize_location(
    record: dict,
    stats: Counter,
) -> str | None:
    """Validate a GeoJSON Point and store its JSON representation."""
    value = record.get("location")

    if value is None:
        stats["missing_location_objects"] += 1
        return None

    if not isinstance(value, dict) or value.get("type") != "Point":
        raise RecordValidationError(
            "invalid_location_object",
            "The location field is not a GeoJSON Point object.",
        )

    coordinates = value.get("coordinates")

    if not isinstance(coordinates, list) or len(coordinates) != 2:
        raise RecordValidationError(
            "invalid_location_coordinates",
            "The location Point must have longitude and latitude.",
        )

    try:
        longitude = float(coordinates[0])
        latitude = float(coordinates[1])
    except (TypeError, ValueError) as exc:
        raise RecordValidationError(
            "invalid_location_coordinates",
            "The location Point coordinates are not numeric.",
        ) from exc

    if not (
        math.isfinite(longitude)
        and math.isfinite(latitude)
        and -180 <= longitude <= 180
        and -90 <= latitude <= 90
    ):
        raise RecordValidationError(
            "invalid_location_coordinates",
            "The location Point coordinates are outside valid ranges.",
        )

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise RecordValidationError(
            "invalid_location_json",
            "The location object cannot be encoded as strict JSON.",
        ) from exc

    return encoded


def load_dimension_caches(connection: sqlite3.Connection) -> dict:
    """Load the small reference tables into memory for efficient lookup."""
    caches = {}

    for table, (id_column, key_column, attribute_columns) in (
        DIMENSION_CONFIG.items()
    ):
        columns = [
            id_column,
            key_column,
            "retrieved_at",
        ]
        query = (
            f"SELECT {', '.join(columns)} "
            f"FROM {table}"
        )

        cache = {}
        for row in connection.execute(query):
            cache[row[key_column]] = {
                "id": row[id_column],
                "retrieved_at": row["retrieved_at"],
            }

        caches[table] = cache

    return caches


def get_dimension_id(
    connection: sqlite3.Connection,
    caches: dict,
    table: str,
    natural_key: str,
    attributes: dict,
    retrieved_at: str,
    stats: Counter,
) -> int:
    """Insert a new dimension member or update it from a newer snapshot."""
    id_column, key_column, _ = DIMENSION_CONFIG[table]
    cache = caches[table]
    current = cache.get(natural_key)

    if current is None:
        columns = [key_column, *attributes.keys(), "retrieved_at"]
        values = [natural_key, *attributes.values(), retrieved_at]
        placeholders = ", ".join("?" for _ in values)

        cursor = connection.execute(
            f"""
            INSERT INTO {table} ({", ".join(columns)})
            VALUES ({placeholders})
            """,
            values,
        )

        cache[natural_key] = {
            "id": cursor.lastrowid,
            "retrieved_at": retrieved_at,
        }
        stats[f"new_entities_{table}"] += 1
        return cursor.lastrowid

    if retrieved_at > current["retrieved_at"]:
        assignments = [
            f"{column} = ?"
            for column in attributes
        ]
        assignments.append("retrieved_at = ?")

        connection.execute(
            f"""
            UPDATE {table}
            SET {", ".join(assignments)}
            WHERE {id_column} = ?
              AND retrieved_at < ?
            """,
            [*attributes.values(), retrieved_at, current["id"], retrieved_at],
        )

        current["retrieved_at"] = retrieved_at
        stats[f"updated_entities_{table}"] += 1

    return current["id"]


def quarantine_record(
    connection: sqlite3.Connection,
    source_file: str,
    row_number: int,
    record: object,
    reason_code: str,
    reason_detail: str,
    retrieved_at: str,
) -> None:
    """Preserve a rejected record and its reason without aborting the batch."""
    source_key = None

    if isinstance(record, dict):
        value = record.get("unique_key")
        if isinstance(value, str) and value.strip():
            source_key = value.strip()

    encoded_record = json.dumps(
        record,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )

    connection.execute(
        QUARANTINE_SQL,
        (
            "nyc311",
            source_file,
            row_number,
            source_key,
            reason_code,
            reason_detail,
            encoded_record,
            retrieved_at,
        ),
    )


def prepare_service_request(
    record: dict,
    retrieved_at: str,
    connection: sqlite3.Connection,
    caches: dict,
    stats: Counter,
) -> tuple:
    """Validate and normalize one NYC 311 record."""
    unique_key = record.get("unique_key")

    if not isinstance(unique_key, str) or not unique_key.strip():
        raise RecordValidationError(
            "missing_unique_key",
            "The source record has no usable unique_key.",
        )

    unique_key = unique_key.strip()

    agency_code = required_label(record, "agency")
    agency_name = required_label(
        record,
        "agency_name",
        uppercase=False,
    )
    borough_name = required_label(record, "borough")
    complaint_type = required_label(record, "complaint_type")
    status_name = required_label(record, "status")
    channel_name = required_label(record, "open_data_channel_type")

    created = normalize_source_timestamp(
        record.get("created_date"),
        "created_date",
        stats,
        required=True,
    )

    if created["local"] is None:
        raise RecordValidationError(
            "invalid_created_date",
            "created_date has no usable local datetime.",
        )

    optional_dates = {}
    for source_field, prefix in [
        ("closed_date", "closed"),
        ("due_date", "due"),
        (
            "resolution_action_updated_date",
            "resolution_updated",
        ),
    ]:
        normalized = normalize_source_timestamp(
            record.get(source_field),
            source_field,
            stats,
        )

        # If a supplied timestamp cannot be parsed, preserve the entire
        # record in quarantine rather than inventing a replacement value.
        optional_dates[prefix] = normalized

    numeric_values = {
        field: optional_number(record, field, stats)
        for field in NUMERIC_REQUEST_FIELDS
    }

    location_json = normalize_location(record, stats)

    # Required labels and core values are normalized before dimension lookup.
    agency_id = get_dimension_id(
        connection,
        caches,
        "agencies",
        agency_code,
        {"agency_name": agency_name},
        retrieved_at,
        stats,
    )
    borough_id = get_dimension_id(
        connection,
        caches,
        "boroughs",
        borough_name,
        {},
        retrieved_at,
        stats,
    )
    complaint_type_id = get_dimension_id(
        connection,
        caches,
        "complaint_types",
        complaint_type,
        {},
        retrieved_at,
        stats,
    )
    status_id = get_dimension_id(
        connection,
        caches,
        "request_statuses",
        status_name,
        {},
        retrieved_at,
        stats,
    )
    channel_id = get_dimension_id(
        connection,
        caches,
        "submission_channels",
        channel_name,
        {},
        retrieved_at,
        stats,
    )

    row = {
        "unique_key": unique_key,
        "created_date_source": created["source"],
        "created_at_utc": created["utc"],
        "created_local_date": created["local"].date().isoformat(),
        "created_local_hour": created["local"].hour,
        "created_timestamp_status": created["status"],
        "agency_id": agency_id,
        "borough_id": borough_id,
        "complaint_type_id": complaint_type_id,
        "status_id": status_id,
        "channel_id": channel_id,
        "closed_date_source": optional_dates["closed"]["source"],
        "closed_at_utc": optional_dates["closed"]["utc"],
        "closed_timestamp_status": optional_dates["closed"]["status"],
        "due_date_source": optional_dates["due"]["source"],
        "due_at_utc": optional_dates["due"]["utc"],
        "due_timestamp_status": optional_dates["due"]["status"],
        "resolution_action_updated_date_source":
            optional_dates["resolution_updated"]["source"],
        "resolution_action_updated_at_utc":
            optional_dates["resolution_updated"]["utc"],
        "resolution_updated_timestamp_status":
            optional_dates["resolution_updated"]["status"],
        "x_coordinate_state_plane":
            numeric_values["x_coordinate_state_plane"],
        "y_coordinate_state_plane":
            numeric_values["y_coordinate_state_plane"],
        "latitude": numeric_values["latitude"],
        "longitude": numeric_values["longitude"],
        "location_json": location_json,
        "retrieved_at": retrieved_at,
    }

    for field in OPTIONAL_TEXT_FIELDS:
        row[field] = optional_text(record, field, stats)

    return tuple(row[column] for column in REQUEST_COLUMNS)


def build_request_upsert_sql() -> str:
    """Build a parameterized UPSERT using the fixed request column list."""
    placeholders = ", ".join("?" for _ in REQUEST_COLUMNS)
    updates = ", ".join(
        f"{column} = excluded.{column}"
        for column in REQUEST_COLUMNS
        if column != "unique_key"
    )

    return f"""
        INSERT INTO service_requests ({", ".join(REQUEST_COLUMNS)})
        VALUES ({placeholders})
        ON CONFLICT (unique_key) DO UPDATE SET
            {updates}
        WHERE excluded.retrieved_at > service_requests.retrieved_at
    """


def count_table_rows(connection: sqlite3.Connection) -> dict:
    """Return row counts for the project tables."""
    return {
        table: connection.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]
        for table in COUNTED_TABLES
    }


def list_nyc_files(nyc_dir: Path) -> list[tuple[Path, str]]:
    """Find raw NYC 311 pages and validate their retrieval filenames."""
    files = sorted(
        path
        for path in nyc_dir.glob("*.json")
        if path.name != ".cursor_checkpoint.json"
    )

    if not files:
        raise LoadError(f"No NYC 311 JSON page files found in {nyc_dir}.")

    result = []
    for path in files:
        retrieved_at = parse_retrieval_time(path, "nyc311")
        result.append((path, retrieved_at))

    return sorted(result, key=lambda item: (item[1], item[0].name))


def newest_weather_file(weather_dir: Path) -> tuple[Path, str]:
    """Select the newest Unix-timestamp weather response by filename time."""
    candidates = []

    for path in weather_dir.glob("*_weather_unix.json"):
        retrieved_at = parse_retrieval_time(path, "weather")
        candidates.append((path, retrieved_at))

    if not candidates:
        raise LoadError(
            f"No *_weather_unix.json raw file found in {weather_dir}."
        )

    return max(candidates, key=lambda item: (item[1], item[0].name))


def load_nyc_pages(
    connection: sqlite3.Connection,
    raw_root: Path,
    pages: list[tuple[Path, str]],
    caches: dict,
    stats: Counter,
) -> None:
    """Load NYC 311 pages in batches within the current transaction."""
    request_sql = build_request_upsert_sql()
    request_batch = []
    request_batch_size = 1000

    for path, retrieved_at in pages:
        try:
            with path.open(encoding="utf-8") as source:
                records = json.load(source)
        except (OSError, json.JSONDecodeError) as exc:
            raise LoadError(
                f"Cannot read valid JSON from {path}: {exc}"
            ) from exc

        if not isinstance(records, list):
            raise LoadError(
                f"Expected a JSON list in {path.name}; "
                f"got {type(records).__name__}."
            )

        stats["nyc_files_read"] += 1
        stats["nyc_records_seen"] += len(records)
        if not records:
            stats["empty_nyc_pages"] += 1

        relative_file = str(path.relative_to(raw_root))

        for row_number, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                quarantine_record(
                    connection,
                    relative_file,
                    row_number,
                    record,
                    "record_not_object",
                    "The JSON item is not an object.",
                    retrieved_at,
                )
                stats["records_quarantined"] += 1
                continue

            try:
                values = prepare_service_request(
                    record,
                    retrieved_at,
                    connection,
                    caches,
                    stats,
                )
            except RecordValidationError as exc:
                quarantine_record(
                    connection,
                    relative_file,
                    row_number,
                    record,
                    exc.reason_code,
                    exc.detail,
                    retrieved_at,
                )
                stats["records_quarantined"] += 1
                continue

            request_batch.append(values)

            if len(request_batch) >= request_batch_size:
                connection.executemany(request_sql, request_batch)
                stats["service_request_upsert_attempts"] += len(request_batch)
                request_batch.clear()

        if request_batch:
            connection.executemany(request_sql, request_batch)
            stats["service_request_upsert_attempts"] += len(request_batch)
            request_batch.clear()


def validate_weather_value(
    variable: str,
    value: object,
    borough: str,
) -> float | int | None:
    """Validate a single hourly weather value before it enters SQLite."""
    if value is None:
        return None

    if variable == "weather_code":
        if type(value) is not int:
            raise LoadError(
                f"{borough}: weather_code must be an integer, got {value!r}."
            )
        return value

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LoadError(
            f"{borough}: {variable} is not numeric: {value!r}."
        )

    number = float(value)

    if not math.isfinite(number):
        raise LoadError(
            f"{borough}: {variable} is non-finite: {value!r}."
        )

    if variable == "relative_humidity_2m" and not 0 <= number <= 100:
        raise LoadError(f"{borough}: humidity is out of range: {number}.")
    if variable == "precipitation" and number < 0:
        raise LoadError(f"{borough}: negative precipitation: {number}.")
    if variable == "wind_speed_10m" and number < 0:
        raise LoadError(f"{borough}: negative wind speed: {number}.")
    if variable == "wind_direction_10m" and not 0 <= number <= 360:
        raise LoadError(f"{borough}: wind direction is out of range: {number}.")
    if variable == "cloud_cover" and not 0 <= number <= 100:
        raise LoadError(f"{borough}: cloud cover is out of range: {number}.")

    return number


def load_weather_location_cache(
    connection: sqlite3.Connection,
) -> dict:
    """Load current weather-location members into memory."""
    rows = connection.execute(
        """
        SELECT weather_location_id, location_code, retrieved_at
        FROM weather_locations
        """
    )

    return {
        row["location_code"]: {
            "id": row["weather_location_id"],
            "retrieved_at": row["retrieved_at"],
        }
        for row in rows
    }


def get_weather_location_id(
    connection: sqlite3.Connection,
    cache: dict,
    location_code: str,
    borough_id: int,
    requested_latitude: float,
    requested_longitude: float,
    grid_latitude: float,
    grid_longitude: float,
    retrieved_at: str,
    stats: Counter,
) -> int:
    """Insert or update a weather location using the newest snapshot."""
    current = cache.get(location_code)

    if current is None:
        cursor = connection.execute(
            """
            INSERT INTO weather_locations (
                location_code, borough_id,
                requested_latitude, requested_longitude,
                grid_latitude, grid_longitude,
                timezone, retrieved_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                location_code,
                borough_id,
                requested_latitude,
                requested_longitude,
                grid_latitude,
                grid_longitude,
                "America/New_York",
                retrieved_at,
            ),
        )

        cache[location_code] = {
            "id": cursor.lastrowid,
            "retrieved_at": retrieved_at,
        }
        stats["new_entities_weather_locations"] += 1
        return cursor.lastrowid

    if retrieved_at > current["retrieved_at"]:
        connection.execute(
            """
            UPDATE weather_locations
            SET borough_id = ?,
                requested_latitude = ?,
                requested_longitude = ?,
                grid_latitude = ?,
                grid_longitude = ?,
                timezone = ?,
                retrieved_at = ?
            WHERE weather_location_id = ?
              AND retrieved_at < ?
            """,
            (
                borough_id,
                requested_latitude,
                requested_longitude,
                grid_latitude,
                grid_longitude,
                "America/New_York",
                retrieved_at,
                current["id"],
                retrieved_at,
            ),
        )
        current["retrieved_at"] = retrieved_at
        stats["updated_entities_weather_locations"] += 1

    return current["id"]


def build_weather_upsert_sql() -> str:
    """Build the weather UPSERT with a composite natural key."""
    columns = [
        "weather_location_id",
        "observed_at_utc",
        "temperature_2m_c",
        "relative_humidity_2m_pct",
        "precipitation_mm",
        "weather_code",
        "wind_speed_10m_kmh",
        "wind_direction_10m_degrees",
        "cloud_cover_pct",
        "retrieved_at",
    ]

    updates = ", ".join(
        f"{column} = excluded.{column}"
        for column in columns
        if column not in {"weather_location_id", "observed_at_utc"}
    )

    return f"""
        INSERT INTO weather_observations ({", ".join(columns)})
        VALUES ({", ".join("?" for _ in columns)})
        ON CONFLICT (weather_location_id, observed_at_utc)
        DO UPDATE SET {updates}
        WHERE excluded.retrieved_at > weather_observations.retrieved_at
    """


def load_weather_file(
    connection: sqlite3.Connection,
    path: Path,
    retrieved_at: str,
    raw_root: Path,
    caches: dict,
    stats: Counter,
) -> None:
    """Validate and load the selected hourly Open-Meteo snapshot."""
    try:
        with path.open(encoding="utf-8") as source:
            payload = json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise LoadError(
            f"Cannot read valid weather JSON from {path}: {exc}"
        ) from exc

    if not isinstance(payload, list) or len(payload) != len(BOROUGHS):
        raise LoadError(
            f"Expected {len(BOROUGHS)} weather locations in {path.name}."
        )

    expected_dates = {
        (START_DATE + timedelta(days=day)).isoformat()
        for day in range((END_DATE - START_DATE).days + 1)
    }

    connection.execute(
        """
        CREATE TEMP TABLE IF NOT EXISTS weather_load_seen (
            location_code TEXT PRIMARY KEY
        ) STRICT
        """
    )
    connection.execute("DELETE FROM weather_load_seen")

    weather_location_cache = load_weather_location_cache(connection)
    weather_sql = build_weather_upsert_sql()
    weather_batch = []
    batch_size = 1000

    for (borough, requested_lat, requested_lon), item in zip(
        BOROUGHS, payload
    ):
        if not isinstance(item, dict):
            raise LoadError(
                f"Weather response for {borough} is not a JSON object."
            )

        if item.get("timezone") != "America/New_York":
            raise LoadError(
                f"Unexpected timezone for {borough}: {item.get('timezone')!r}"
            )

        grid_lat = item.get("latitude")
        grid_lon = item.get("longitude")

        if (
            isinstance(grid_lat, bool)
            or not isinstance(grid_lat, (int, float))
            or not math.isfinite(float(grid_lat))
            or not -90 <= float(grid_lat) <= 90
        ):
            raise LoadError(f"Invalid weather grid latitude for {borough}.")

        if (
            isinstance(grid_lon, bool)
            or not isinstance(grid_lon, (int, float))
            or not math.isfinite(float(grid_lon))
            or not -180 <= float(grid_lon) <= 180
        ):
            raise LoadError(f"Invalid weather grid longitude for {borough}.")

        grid_lat = float(grid_lat)
        grid_lon = float(grid_lon)

        # Open-Meteo may return the snapped model-grid cell, not the
        # requested point's exact coordinates. This generous check detects
        # gross misordering without assuming the grid equals the request.
        if (
            abs(grid_lat - requested_lat) > 0.15
            or abs(grid_lon - requested_lon) > 0.15
        ):
            raise LoadError(
                f"Weather coordinates do not plausibly match {borough}. "
                "The response order may have changed."
            )

        hourly = item.get("hourly")
        if not isinstance(hourly, dict):
            raise LoadError(f"Missing hourly data for {borough}.")

        times = hourly.get("time")
        if not isinstance(times, list) or len(times) != 8760:
            raise LoadError(
                f"{borough}: expected 8,760 timestamps, "
                f"got {len(times) if isinstance(times, list) else 'invalid'}."
            )

        for raw_name, _ in WEATHER_VARIABLES:
            values = hourly.get(raw_name)
            if not isinstance(values, list) or len(values) != len(times):
                raise LoadError(
                    f"{borough}: missing or invalid array {raw_name}."
                )

        if any(type(timestamp) is not int for timestamp in times):
            raise LoadError(
                f"{borough}: timestamps must be integer Unix seconds."
            )

        if len(set(times)) != len(times):
            raise LoadError(f"{borough}: duplicate weather timestamps.")

        if any(
            later - earlier != 3600
            for earlier, later in zip(times, times[1:])
        ):
            raise LoadError(
                f"{borough}: weather timestamps are not hourly and consecutive."
            )

        if any(timestamp % 3600 != 0 for timestamp in times):
            raise LoadError(
                f"{borough}: a timestamp is not aligned to a UTC hour."
            )

        local_dates = {
            datetime.fromtimestamp(timestamp, UTC)
            .astimezone(NY_TZ)
            .date()
            .isoformat()
            for timestamp in times
        }

        if local_dates != expected_dates:
            raise LoadError(
                f"{borough}: weather dates do not match the approved period."
            )

        borough_id = get_dimension_id(
            connection,
            caches,
            "boroughs",
            borough.upper(),
            {},
            retrieved_at,
            stats,
        )

        location_code = borough.upper().replace(" ", "_")

        location_id = get_weather_location_id(
            connection,
            weather_location_cache,
            location_code,
            borough_id,
            requested_lat,
            requested_lon,
            grid_lat,
            grid_lon,
            retrieved_at,
            stats,
        )

        connection.execute(
            "INSERT INTO weather_load_seen (location_code) VALUES (?)",
            (location_code,),
        )

        for index, epoch in enumerate(times):
            observed_at = (
                datetime.fromtimestamp(epoch, UTC)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            )

            observation = {}
            for raw_name, db_name in WEATHER_VARIABLES:
                observation[db_name] = validate_weather_value(
                    raw_name,
                    hourly[raw_name][index],
                    borough,
                )

            weather_batch.append(
                (
                    location_id,
                    observed_at,
                    observation["temperature_2m_c"],
                    observation["relative_humidity_2m_pct"],
                    observation["precipitation_mm"],
                    observation["weather_code"],
                    observation["wind_speed_10m_kmh"],
                    observation["wind_direction_10m_degrees"],
                    observation["cloud_cover_pct"],
                    retrieved_at,
                )
            )

            stats["weather_observations_seen"] += 1
            if len(weather_batch) >= batch_size:
                connection.executemany(weather_sql, weather_batch)
                stats["weather_observation_upsert_attempts"] += len(
                    weather_batch
                )
                weather_batch.clear()

    if weather_batch:
        connection.executemany(weather_sql, weather_batch)
        stats["weather_observation_upsert_attempts"] += len(weather_batch)
        weather_batch.clear()

    seen_locations = connection.execute(
        "SELECT COUNT(*) FROM weather_load_seen"
    ).fetchone()[0]

    if seen_locations != len(BOROUGHS):
        raise LoadError(
            f"Expected {len(BOROUGHS)} weather locations, "
            f"processed {seen_locations}."
        )

    stats["weather_files_read"] += 1
    stats["weather_source_file"] = str(path.relative_to(raw_root))


def load_dataset(
    raw_dir: Path = DEFAULT_RAW_DIR,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict:
    """Load the raw snapshot atomically and return a run summary."""
    raw_dir = Path(raw_dir).resolve()
    db_path = Path(db_path).resolve()

    nyc_dir = raw_dir / "nyc311"
    weather_dir = raw_dir / "weather"

    if not nyc_dir.is_dir():
        raise LoadError(f"NYC 311 raw directory is missing: {nyc_dir}")
    if not weather_dir.is_dir():
        raise LoadError(f"Weather raw directory is missing: {weather_dir}")

    pages = list_nyc_files(nyc_dir)
    weather_path, weather_retrieved_at = newest_weather_file(weather_dir)

    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    stats = Counter()

    connection = connect(db_path)

    try:
        connection.executescript(schema)

        before_counts = count_table_rows(connection)

        # One transaction covers all dimensions, events, weather rows and
        # quarantined records. Any fatal error rolls back the whole load.
        connection.execute("BEGIN IMMEDIATE")

        # Building indexes after the first large insert is generally faster.
        # If this transaction fails, rollback restores the original indexes.
        if before_counts["service_requests"] == 0:
            connection.execute(
                "DROP INDEX IF EXISTS idx_requests_borough_date_hour"
            )
            connection.execute(
                "DROP INDEX IF EXISTS idx_requests_complaint_date"
            )
            connection.execute(
                "DROP INDEX IF EXISTS idx_requests_created_utc"
            )
            connection.execute(
                "DROP INDEX IF EXISTS idx_requests_local_date"
            )

        caches = load_dimension_caches(connection)

        load_nyc_pages(
            connection,
            raw_dir,
            pages,
            caches,
            stats,
        )

        load_weather_file(
            connection,
            weather_path,
            weather_retrieved_at,
            raw_dir,
            caches,
            stats,
        )

        for statement in INDEX_STATEMENTS:
            connection.execute(statement)

        foreign_key_errors = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        if foreign_key_errors:
            raise LoadError(
                f"Foreign-key validation failed: "
                f"{len(foreign_key_errors)} problem(s)."
            )

        connection.commit()
        after_counts = count_table_rows(connection)

        stats["nyc_files_discovered"] = len(pages)
        stats["weather_retrieval_timestamp"] = weather_retrieved_at

        return {
            "stats": dict(stats),
            "before": before_counts,
            "after": after_counts,
            "database": str(db_path),
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def print_summary(summary: dict) -> None:
    """Print the required load statistics."""
    stats = summary["stats"]
    before = summary["before"]
    after = summary["after"]

    print("\n========== DATA LOAD SUMMARY ==========")
    print(f"Database: {summary['database']}")
    print(f"NYC JSON files discovered: {stats.get('nyc_files_discovered', 0):,}")
    print(f"NYC JSON files read: {stats.get('nyc_files_read', 0):,}")
    print(f"NYC records seen: {stats.get('nyc_records_seen', 0):,}")
    print(f"Empty NYC pages: {stats.get('empty_nyc_pages', 0):,}")
    print(
        "Valid service request UPSERT attempts: "
        f"{stats.get('service_request_upsert_attempts', 0):,}"
    )
    print(f"Quarantine candidates: {stats.get('records_quarantined', 0):,}")
    print(
        f"Weather source files read: {stats.get('weather_files_read', 0):,}"
    )
    print(f"Weather source: {stats.get('weather_source_file', 'None')}")
    print(
        "Weather retrieval timestamp: "
        f"{stats.get('weather_retrieval_timestamp', 'None')}"
    )
    print(
        "Weather observation UPSERT attempts: "
        f"{stats.get('weather_observation_upsert_attempts', 0):,}"
    )

    print("\nTable counts (before -> after; net new rows):")
    for table in COUNTED_TABLES:
        old_count = before[table]
        new_count = after[table]
        print(
            f"  {table}: {old_count:,} -> {new_count:,} "
            f"(+{new_count - old_count:,})"
        )

    print("\nNew entity counts:")
    for table in DIMENSION_CONFIG:
        print(
            f"  {table}: "
            f"{stats.get(f'new_entities_{table}', 0):,}"
        )
    print(
        "  weather_locations: "
        f"{stats.get('new_entities_weather_locations', 0):,}"
    )

    print("\nTimestamp status counts:")
    for field in (
        "created_date",
        "closed_date",
        "due_date",
        "resolution_action_updated_date",
    ):
        labels = (
            "normalized",
            "ambiguous_local_time",
            "nonexistent_local_time",
            "missing",
        )
        values = [
            f"{label}={stats.get(f'timestamp_{field}_{label}', 0):,}"
            for label in labels
            if stats.get(f"timestamp_{field}_{label}", 0)
        ]
        if values:
            print(f"  {field}: " + ", ".join(values))

    print("\nTransformations:")
    print(
        "  Numeric source strings converted: "
        f"{stats.get('numeric_strings_converted', 0):,}"
    )
    print(
        "  Empty strings converted to NULL: "
        f"{stats.get('empty_strings_converted_to_null', 0):,}"
    )
    print(
        "  Missing location objects preserved as NULL: "
        f"{stats.get('missing_location_objects', 0):,}"
    )

    print("\nForeign-key check: PASS")
    print("Transaction committed successfully.")
    print("========== END OF LOAD SUMMARY ==========")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Load NYC 311 and Open-Meteo raw JSON into SQLite."
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_RAW_DIR,
        help="Root folder containing nyc311/ and weather/ (default: data/raw).",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="SQLite database path (default: data/nyc311_weather.db).",
    )
    args = parser.parse_args()

    try:
        summary = load_dataset(args.raw_dir, args.db_path)
        print_summary(summary)
    except Exception as exc:
        print(
            f"LOAD FAILED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print(
            "The data transaction was rolled back. "
            "Inspect the source and error before retrying.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
