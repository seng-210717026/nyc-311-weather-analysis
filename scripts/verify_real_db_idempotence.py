#!/usr/bin/env python3
"""Compare saved real-database evidence with the current local SQLite database."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.checks import read_table_state  # noqa: E402


def read_snapshot(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"ERROR: Evidence file not found: {path}")

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"ERROR: Expected a JSON object in {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify saved before/after database hashes and compare the "
            "current local database with the saved after-state."
        )
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=ROOT / "docs" / "evidence",
        help="Evidence directory (default: docs/evidence)",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=ROOT / "data" / "nyc311_weather.db",
        help="Local SQLite database to hash",
    )
    args = parser.parse_args()

    evidence_dir = args.evidence_dir.expanduser()
    database = args.database.expanduser()

    before = read_snapshot(evidence_dir / "real-db-state-before.json")
    after = read_snapshot(evidence_dir / "real-db-state-after.json")

    if before != after:
        print("FAIL: Saved before/after row counts or hashes differ.")
        for table in sorted(set(before) | set(after)):
            if before.get(table) != after.get(table):
                print(f"  Changed in saved evidence: {table}")
        return 1

    print(f"PASS: Saved before/after snapshots match ({len(before)} tables).")

    if not database.is_file():
        print(f"ERROR: Database not found: {database}")
        print("Restore the raw inputs and run src/load.py before this check.")
        return 1

    print(f"Hashing current database: {database}")
    print("This scans the contents of every table and may take several minutes.")

    current_state = read_table_state(database)
    current = {
        table: {"row_count": count, "sha256": digest}
        for table, (count, digest) in current_state.items()
    }

    if current != after:
        print("FAIL: Current database differs from the saved after-state.")
        for table in sorted(set(after) | set(current)):
            if after.get(table) != current.get(table):
                print(f"  Changed: {table}")
        return 1

    for table in sorted(current):
        print(f"PASS: {table} — {current[table]['row_count']:,} rows")

    print("ALL REAL-DATABASE HASH CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
