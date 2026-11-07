"""Hash-based M2 immutability and M3 idempotence evidence."""

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "nyc311_weather.db"
BASELINE_PATH = ROOT / "docs" / "evidence" / "m3_integrity_before.json"

M2_TABLES = [
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

M3_TABLES = [
    "service_requests_clean",
    "weather_observations_clean",
    "category_alias_map",
    "identity_alias_map",
]


def table_state(con, table):
    columns = con.execute(
        f'PRAGMA table_info("{table}")'
    ).fetchall()

    if not columns:
        raise RuntimeError(f"Table does not exist: {table}")

    primary_key = [
        row[1] for row in sorted(columns, key=lambda item: item[5])
        if row[5] > 0
    ]

    if not primary_key:
        raise RuntimeError(f"No primary key found for {table}")

    order_by = ", ".join(f'"{column}"' for column in primary_key)
    cursor = con.execute(
        f'SELECT * FROM "{table}" ORDER BY {order_by}'
    )

    digest = hashlib.sha256()
    count = 0

    for row in cursor:
        encoded = json.dumps(
            row,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        digest.update(encoded)
        digest.update(b"\n")
        count += 1

    return {"rows": count, "sha256": digest.hexdigest()}


def all_states(con):
    return {
        table: table_state(con, table)
        for table in M2_TABLES + M3_TABLES
    }


def open_read_only():
    uri = DB_PATH.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def snapshot():
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open_read_only() as con:
        state = all_states(con)

    payload = {
        "description": (
            "Baseline immediately before the final M3 clean.py run. "
            "M2 hashes prove source immutability during that run; "
            "M3 hashes are used for idempotence comparison."
        ),
        "tables": state,
    }

    BASELINE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"Baseline saved: {BASELINE_PATH}")
    for table, values in state.items():
        print(
            f"{table}: rows={values['rows']:,}; "
            f"sha256={values['sha256']}"
        )


def compare():
    if not BASELINE_PATH.is_file():
        raise FileNotFoundError(
            f"Baseline not found: {BASELINE_PATH}. Run snapshot first."
        )

    baseline = json.loads(
        BASELINE_PATH.read_text(encoding="utf-8")
    )["tables"]

    with open_read_only() as con:
        current = all_states(con)

    failures = []

    print("M2 SOURCE IMMUTABILITY")
    print("-" * 75)

    for table in M2_TABLES:
        before = baseline[table]
        after = current[table]
        passed = before == after

        print(
            f"[{'PASS' if passed else 'FAIL'}] {table}: "
            f"{before['rows']:,} -> {after['rows']:,}; "
            f"hash_match={before['sha256'] == after['sha256']}"
        )

        if not passed:
            failures.append(table)

    print("\nM3 IDEMPOTENCE")
    print("-" * 75)

    for table in M3_TABLES:
        before = baseline[table]
        after = current[table]
        passed = before == after

        print(
            f"[{'PASS' if passed else 'FAIL'}] {table}: "
            f"{before['rows']:,} -> {after['rows']:,}; "
            f"hash_match={before['sha256'] == after['sha256']}"
        )

        if not passed:
            failures.append(table)

    if failures:
        print("\nINTEGRITY TEST FAILED:", ", ".join(failures))
        return 1

    print("\nALL M2 HASHES UNCHANGED; ALL M3 TABLES IDEMPOTENT.")
    return 0


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in {"snapshot", "compare"}:
            print("Usage: python3 src/m3_integrity.py snapshot|compare")
            sys.exit(2)

        result = snapshot() if sys.argv[1] == "snapshot" else compare()
        sys.exit(0 if result is None else result)

    except Exception as exc:
        print(f"INTEGRITY TEST ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
