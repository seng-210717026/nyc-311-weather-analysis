"""Schema, integrity, idempotence, and transaction checks."""

import hashlib
import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from src.db import connect
    from src.load import COUNTED_TABLES, LoadError, load_dataset
except ModuleNotFoundError:
    from db import connect
    from load import COUNTED_TABLES, LoadError, load_dataset


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "sql" / "schema.sql"
RETRIEVED_AT = "2026-10-23T12:00:00Z"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def must_reject(connection, label, sql, parameters, expected_error):
    try:
        connection.execute(sql, parameters)
    except sqlite3.IntegrityError as exc:
        require(
            expected_error in str(exc),
            f"{label}: unexpected integrity error: {exc}",
        )
        print(f"PASS: {label}")
        return
    except sqlite3.DatabaseError as exc:
        require(
            expected_error in str(exc),
            f"{label}: unexpected database error: {exc}",
        )
        print(f"PASS: {label}")
        return

    raise AssertionError(f"{label}: invalid input was accepted.")


def run_schema_checks() -> None:
    """Check schema constraints in an in-memory database."""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    connection = connect(":memory:")

    try:
        connection.executescript(schema)
        connection.executescript(schema)

        tables = {
            row[1]: bool(row[5])
            for row in connection.execute("PRAGMA table_list")
            if row[0] == "main" and row[2] == "table"
        }

        expected_tables = set(COUNTED_TABLES)
        require(
            expected_tables <= tables.keys(),
            "One or more required tables are missing.",
        )

        for table in expected_tables:
            require(tables[table], f"{table} is not a STRICT table.")
            columns = {
                row[1]
                for row in connection.execute(
                    f'PRAGMA table_info("{table}")'
                )
            }
            require(
                "retrieved_at" in columns,
                f"{table} lacks retrieved_at.",
            )

        require(
            connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1,
            "Foreign-key enforcement is disabled.",
        )

        print("PASS: Schema executes repeatedly")
        print("PASS: All required tables are STRICT")
        print("PASS: Every table has retrieved_at")
        print("PASS: Foreign-key enforcement is enabled")

        request_columns = """
            unique_key, created_date_source, created_at_utc,
            created_local_date, created_local_hour,
            created_timestamp_status, agency_id, borough_id,
            complaint_type_id, status_id, channel_id,
            closed_timestamp_status, due_timestamp_status,
            resolution_updated_timestamp_status, retrieved_at
        """

        request_sql = f"""
            INSERT INTO service_requests ({request_columns})
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        for sql, parameters in [
            (
                """
                INSERT INTO agencies
                    (agency_id, agency_code, agency_name, retrieved_at)
                VALUES (?, ?, ?, ?)
                """,
                (1, "NYPD", "New York City Police Department", RETRIEVED_AT),
            ),
            (
                """
                INSERT INTO boroughs
                    (borough_id, borough_name, retrieved_at)
                VALUES (?, ?, ?)
                """,
                (1, "BRONX", RETRIEVED_AT),
            ),
            (
                """
                INSERT INTO complaint_types
                    (complaint_type_id, complaint_type, retrieved_at)
                VALUES (?, ?, ?)
                """,
                (1, "NOISE - RESIDENTIAL", RETRIEVED_AT),
            ),
            (
                """
                INSERT INTO request_statuses
                    (status_id, status_name, retrieved_at)
                VALUES (?, ?, ?)
                """,
                (1, "OPEN", RETRIEVED_AT),
            ),
            (
                """
                INSERT INTO submission_channels
                    (channel_id, channel_name, retrieved_at)
                VALUES (?, ?, ?)
                """,
                (1, "ONLINE", RETRIEVED_AT),
            ),
        ]:
            connection.execute(sql, parameters)

        valid = (
            "TEST-1001", "2025-10-12T00:00:00.000",
            "2025-10-12T04:00:00.000000Z",
            "2025-10-12", 0, "normalized",
            1, 1, 1, 1, 1,
            "missing", "missing", "missing", RETRIEVED_AT,
        )

        connection.execute(request_sql, valid)
        print("PASS: Valid service request is accepted")

        must_reject(
            connection,
            "Duplicate natural key rejected",
            request_sql,
            valid,
            "UNIQUE constraint failed",
        )

        null_key = list(valid)
        null_key[0] = None
        must_reject(
            connection,
            "NULL primary key rejected",
            request_sql,
            tuple(null_key),
            "NOT NULL constraint failed",
        )

        wrong_type = list(valid)
        wrong_type[0] = "TEST-1002"
        wrong_type[4] = "not-an-hour"
        must_reject(
            connection,
            "Wrong data type rejected",
            request_sql,
            tuple(wrong_type),
            "cannot store TEXT value",
        )

        orphan = list(valid)
        orphan[0] = "TEST-1003"
        orphan[6] = 999999
        must_reject(
            connection,
            "Orphan event reference rejected",
            request_sql,
            tuple(orphan),
            "FOREIGN KEY constraint failed",
        )

        bad_timestamp = list(valid)
        bad_timestamp[0] = "TEST-1004"
        bad_timestamp[2] = None
        must_reject(
            connection,
            "Normalized timestamp cannot be NULL",
            request_sql,
            tuple(bad_timestamp),
            "CHECK constraint failed",
        )

        ambiguous = list(valid)
        ambiguous[0] = "TEST-1005"
        ambiguous[1] = "2025-11-02T01:00:00.000"
        ambiguous[2] = None
        ambiguous[3] = "2025-11-02"
        ambiguous[4] = 1
        ambiguous[5] = "ambiguous_local_time"
        connection.execute(request_sql, tuple(ambiguous))
        print("PASS: Ambiguous local time preserved without invented UTC")

        require(
            not connection.execute("PRAGMA foreign_key_check").fetchall(),
            "Foreign-key check failed.",
        )
        print("PASS: Foreign-key integrity check")

    finally:
        connection.close()


def make_fixture(root: Path) -> tuple[Path, Path]:
    """Create a small synthetic NYC record and a complete weather snapshot."""
    raw_dir = root / "raw"
    nyc_dir = raw_dir / "nyc311"
    weather_dir = raw_dir / "weather"

    nyc_dir.mkdir(parents=True)
    weather_dir.mkdir(parents=True)

    record = {
        "unique_key": "TEST-2001",
        "created_date": "2025-10-12T00:00:00.000",
        "agency": "NYPD",
        "agency_name": "New York City Police Department",
        "complaint_type": "NOISE - RESIDENTIAL",
        "status": "OPEN",
        "borough": "BRONX",
        "open_data_channel_type": "ONLINE",
        "latitude": "40.8448",
        "longitude": "-73.8648",
        "x_coordinate_state_plane": "1000000",
        "y_coordinate_state_plane": "200000",
        "location": {
            "type": "Point",
            "coordinates": [-73.8648, 40.8448],
        },
    }

    ambiguous_record = record.copy()
    ambiguous_record.update(
        unique_key="TEST-2002",
        created_date="2025-11-02T01:00:00.000",
    )

    nonexistent_record = record.copy()
    nonexistent_record.update(
        unique_key="TEST-2003",
        created_date="2026-03-08T02:30:00.000",
    )

    new_dimension_record = record.copy()
    new_dimension_record.update(
        unique_key="TEST-2004",
        complaint_type="TEST NEW COMPLAINT TYPE",
    )

    missing_key_record = record.copy()
    missing_key_record.pop("unique_key")

    fixture_records = [
        record,
        ambiguous_record,
        nonexistent_record,
        new_dimension_record,
        missing_key_record,
    ]

    nyc_file = nyc_dir / "20261011T123409_616565Z_offset_0.json"
    nyc_file.write_text(
        json.dumps(fixture_records, ensure_ascii=False),
        encoding="utf-8",
    )

    boroughs = [
        ("Bronx", 40.8448, -73.8648),
        ("Brooklyn", 40.6782, -73.9442),
        ("Manhattan", 40.7831, -73.9712),
        ("Queens", 40.7282, -73.7949),
        ("Staten Island", 40.5795, -74.1502),
    ]

    start_epoch = int(
        datetime(2025, 10, 12, 4, tzinfo=timezone.utc).timestamp()
    )
    timestamps = [
        start_epoch + hour * 3600
        for hour in range(8760)
    ]

    weather_payload = []
    for _, latitude, longitude in boroughs:
        weather_payload.append({
            "latitude": latitude,
            "longitude": longitude,
            "timezone": "America/New_York",
            "hourly": {
                "time": timestamps,
                "temperature_2m": [12.5] * 8760,
                "relative_humidity_2m": [55] * 8760,
                "precipitation": [0.0] * 8760,
                "weather_code": [1] * 8760,
                "wind_speed_10m": [8.0] * 8760,
                "wind_direction_10m": [180.0] * 8760,
                "cloud_cover": [50] * 8760,
            },
        })

    weather_file = weather_dir / "20261011T183814Z_weather_unix.json"
    weather_file.write_text(
        json.dumps(weather_payload, separators=(",", ":")),
        encoding="utf-8",
    )

    return raw_dir, weather_file


def read_table_state(db_path: Path) -> dict[str, tuple[int, str]]:
    """Return row counts and streaming hashes of table contents."""
    queries = {
        "agencies": "SELECT * FROM agencies ORDER BY rowid",
        "boroughs": "SELECT * FROM boroughs ORDER BY rowid",
        "complaint_types": "SELECT * FROM complaint_types ORDER BY rowid",
        "request_statuses": "SELECT * FROM request_statuses ORDER BY rowid",
        "submission_channels": "SELECT * FROM submission_channels ORDER BY rowid",
        "weather_locations": "SELECT * FROM weather_locations ORDER BY rowid",
        "service_requests": "SELECT * FROM service_requests ORDER BY rowid",
        "weather_observations": "SELECT * FROM weather_observations ORDER BY rowid",
        "quarantine_records": "SELECT * FROM quarantine_records ORDER BY rowid",
    }

    require(
        set(queries) == set(COUNTED_TABLES),
        "Content-hash queries do not match COUNTED_TABLES.",
    )

    connection = connect(db_path)
    try:
        state = {}
        for table in COUNTED_TABLES:
            digest = hashlib.sha256()
            count = 0

            for row in connection.execute(queries[table]):
                payload = json.dumps(
                    tuple(row),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")

                # Length-prefix each row so concatenated payloads are unambiguous.
                digest.update(len(payload).to_bytes(8, byteorder="big"))
                digest.update(payload)
                count += 1

            state[table] = (count, digest.hexdigest())

        return state
    finally:
        connection.close()


def run_loader_checks() -> None:
    """Test repeated loads and rollback using synthetic data only."""
    with tempfile.TemporaryDirectory(prefix="nyc311_loader_checks_") as temp:
        root = Path(temp)
        raw_dir, weather_file = make_fixture(root)
        db_path = root / "test_database.sqlite"

        first = load_dataset(raw_dir, db_path)
        first_counts = first["after"]
        first_state = read_table_state(db_path)

        require(
            first_counts["service_requests"] == 4,
            "The fixture should load exactly four valid service requests.",
        )
        require(
            first_counts["weather_observations"] == 43800,
            "The fixture should load 43,800 weather observations.",
        )
        require(
            first_counts["quarantine_records"] == 1,
            "The missing-key fixture record should be quarantined.",
        )
        print("PASS: Synthetic data loads successfully")

        verification = connect(db_path)
        try:
            timestamp_rows = verification.execute(
                """
                SELECT unique_key, created_date_source, created_at_utc,
                       created_local_date, created_local_hour,
                       created_timestamp_status
                FROM service_requests
                WHERE unique_key IN (?, ?)
                """,
                ("TEST-2002", "TEST-2003"),
            ).fetchall()
            timestamp_rows = {row[0]: row[1:] for row in timestamp_rows}

            require(
                timestamp_rows.get("TEST-2002") == (
                    "2025-11-02T01:00:00.000",
                    None,
                    "2025-11-02",
                    1,
                    "ambiguous_local_time",
                ),
                "Ambiguous DST timestamp was not retained correctly by the loader.",
            )
            print("PASS: Loader preserves ambiguous DST timestamp without UTC")

            require(
                timestamp_rows.get("TEST-2003") == (
                    "2026-03-08T02:30:00.000",
                    None,
                    "2026-03-08",
                    2,
                    "nonexistent_local_time",
                ),
                "Nonexistent DST timestamp was not retained correctly by the loader.",
            )
            print("PASS: Loader preserves nonexistent DST timestamp without UTC")

            new_type_count = verification.execute(
                """
                SELECT COUNT(*)
                FROM service_requests AS sr
                JOIN complaint_types AS ct
                  ON ct.complaint_type_id = sr.complaint_type_id
                WHERE sr.unique_key = ?
                  AND ct.complaint_type = ?
                """,
                ("TEST-2004", "TEST NEW COMPLAINT TYPE"),
            ).fetchone()[0]
            require(
                new_type_count == 1,
                "A previously unseen complaint type did not create a dimension member.",
            )
            print("PASS: New complaint type dimension member is created")

            quarantine_count = verification.execute(
                """
                SELECT COUNT(*)
                FROM quarantine_records
                WHERE reason_code = ?
                """,
                ("missing_unique_key",),
            ).fetchone()[0]
            require(
                quarantine_count == 1,
                "The invalid-key record was not quarantined exactly once.",
            )
            print("PASS: Missing natural key is quarantined")
        finally:
            verification.close()

        second = load_dataset(raw_dir, db_path)
        second_counts = second["after"]
        second_state = read_table_state(db_path)

        require(
            first_counts == second_counts,
            "Table counts changed after loading the same snapshot twice.",
        )
        require(
            first_state == second_state,
            "Table row contents changed after loading the same snapshot twice.",
        )
        print("PASS: Idempotence (row counts and contents unchanged on second load)")

        # Add a new event with a later retrieval time. A failure later in
        # the same load must roll this record back too.
        new_record = {
            "unique_key": "TEST-2099",
            "created_date": "2025-10-12T00:01:00.000",
            "agency": "NYPD",
            "agency_name": "New York City Police Department",
            "complaint_type": "NOISE - RESIDENTIAL",
            "status": "OPEN",
            "borough": "BRONX",
            "open_data_channel_type": "ONLINE",
        }

        extra_page = raw_dir / "nyc311" / (
            "20261011T183900_000001Z_offset_1.json"
        )
        extra_page.write_text(
            json.dumps([new_record]),
            encoding="utf-8",
        )

        before_failure = read_table_state(db_path)

        # Inject an invalid value after several weather batches have been
        # processed, so the failure occurs after partial transaction work.
        original_weather_text = weather_file.read_text(encoding="utf-8")
        bad_payload = json.loads(original_weather_text)
        bad_payload[0]["hourly"]["temperature_2m"][4000] = "not-a-number"
        weather_file.write_text(
            json.dumps(bad_payload, separators=(",", ":")),
            encoding="utf-8",
        )

        try:
            try:
                load_dataset(raw_dir, db_path)
            except LoadError as exc:
                require(
                    "temperature_2m is not numeric" in str(exc),
                    f"Unexpected LoadError for injected weather value: {exc}",
                )
                print("PASS: Injected weather value raises the expected LoadError")
            except Exception as exc:
                raise AssertionError(
                    f"Expected LoadError for invalid weather value, got "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            else:
                raise AssertionError(
                    "The load unexpectedly accepted invalid weather data."
                )
        finally:
            weather_file.write_text(
                original_weather_text,
                encoding="utf-8",
            )

        after_failure = read_table_state(db_path)

        require(
            before_failure == after_failure,
            "Table row counts or contents changed after a failed load; atomicity failed.",
        )
        require(
            after_failure["service_requests"][0] == 4,
            "The extra service request was not rolled back.",
        )
        verification = connect(db_path)
        try:
            rolled_back_request_count = verification.execute(
                "SELECT COUNT(*) FROM service_requests WHERE unique_key = ?",
                ("TEST-2099",),
            ).fetchone()[0]
        finally:
            verification.close()

        require(
            rolled_back_request_count == 0,
            "The request inserted before the injected failure was not rolled back.",
        )
        print("PASS: Atomicity (row counts and contents unchanged after expected LoadError)")

    print("PASS: Temporary database and fixture data cleaned up")


def run_checks() -> None:
    run_schema_checks()
    run_loader_checks()
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    run_checks()
