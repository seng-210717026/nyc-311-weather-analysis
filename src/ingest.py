"""Run both approved data-source ingestion scripts."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = [
    ("Open-Meteo weather", ROOT / "src" / "ingest_weather.py"),
    ("NYC 311", ROOT / "src" / "ingest_nyc311.py"),
]


def main():
    results = []

    print("M1 ingestion pipeline", flush=True)
    print("=====================", flush=True)

    for source_name, script in SCRIPTS:
        print(f"\nStarting {source_name}: {script.relative_to(ROOT)}", flush=True)

        if not script.is_file():
            print(f"ERROR: Script not found: {script}", flush=True)
            results.append((source_name, 2))
            continue

        try:
            result = subprocess.run(
                [sys.executable, str(script)],
                cwd=ROOT,
                check=False,
            )
            status = result.returncode
        except OSError as exc:
            print(f"ERROR: Could not start {source_name}: {exc}", flush=True)
            status = 2

        results.append((source_name, status))
        label = "SUCCESS" if status == 0 else f"FAILED (exit {status})"
        print(f"{source_name}: {label}", flush=True)

    print("\nIngestion pipeline summary", flush=True)
    for source_name, status in results:
        label = "SUCCESS" if status == 0 else f"FAILED (exit {status})"
        print(f"- {source_name}: {label}", flush=True)

    if any(status != 0 for _, status in results):
        print("Pipeline finished with one or more failures.", flush=True)
        return 1

    print("Both data sources were retrieved successfully.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
