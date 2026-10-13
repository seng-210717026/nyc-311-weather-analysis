#!/usr/bin/env python3

import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"

NYC311_DEFAULT_URL = (
    "https://data.cityofnewyork.us/resource/erm2-nwe9.json"
)



TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = 2

HEADERS = {
    "User-Agent": "nyc-311-weather-analysis/1.0"
}


class IngestionError(Exception):
    """Raised when an ingestion operation cannot be completed."""


class AuthenticationError(IngestionError):
    """Raised when an API rejects the request for authentication."""


def get_date_range():
    """Read and validate the inclusive date range from .env variables."""
    try:
        start_date = date.fromisoformat(os.environ["START_DATE"])
        end_date = date.fromisoformat(os.environ["END_DATE"])
    except KeyError as exc:
        raise IngestionError(
            f"Missing environment variable: {exc.args[0]}"
        ) from exc
    except ValueError as exc:
        raise IngestionError(
            "START_DATE and END_DATE must use YYYY-MM-DD format."
        ) from exc

    if end_date < start_date:
        raise IngestionError("END_DATE cannot be earlier than START_DATE.")

    return start_date, end_date


def get_run_id():
    """Create a unique UTC identifier for this ingestion run."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")


def save_raw(relative_dir, filename, content):
    """Save an unmodified HTTP response body without overwriting files."""
    output_dir = RAW_DIR / relative_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / filename

    try:
        with output_path.open("xb") as output_file:
            output_file.write(content)
    except FileExistsError as exc:
        raise IngestionError(
            f"Refusing to overwrite existing file: {output_path}"
        ) from exc

    print(f"Saved: {output_path.relative_to(ROOT)}")
    return output_path


def request_with_retry(url, params, source_name):
    """Send a GET request and retry temporary network/server failures."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(
                url,
                params=params,
                headers=HEADERS,
                timeout=float(os.environ.get('REQUEST_TIMEOUT_SECONDS', TIMEOUT_SECONDS)),
            )
        except requests.exceptions.RequestException as exc:
            if attempt == MAX_ATTEMPTS:
                raise IngestionError(
                    f"{source_name}: request failed after "
                    f"{MAX_ATTEMPTS} attempts: {exc}"
                ) from exc

            delay = BACKOFF_SECONDS * (2 ** (attempt - 1))
            print(
                f"{source_name}: network error; retrying in {delay}s "
                f"({attempt}/{MAX_ATTEMPTS})"
            )
            time.sleep(delay)
            continue

        if response.status_code in (401, 403):
            response.close()
            raise AuthenticationError(
                f"{source_name}: access denied (HTTP "
                f"{response.status_code})."
            )

        if response.status_code == 429 or 500 <= response.status_code < 600:
            status_code = response.status_code
            response.close()

            if attempt == MAX_ATTEMPTS:
                raise IngestionError(
                    f"{source_name}: HTTP {status_code} after "
                    f"{MAX_ATTEMPTS} attempts."
                )

            delay = BACKOFF_SECONDS * (2 ** (attempt - 1))
            print(
                f"{source_name}: HTTP {status_code}; retrying in {delay}s "
                f"({attempt}/{MAX_ATTEMPTS})"
            )
            time.sleep(delay)
            continue

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            detail = response.text[:500]
            response.close()
            raise IngestionError(
                f"{source_name}: HTTP error: {exc}\n{detail}"
            ) from exc

        return response

    raise IngestionError(f"{source_name}: request failed.")


def parse_json_response(response, source_name):
    """Decode an API response as JSON."""
    try:
        return response.json()
    except ValueError as exc:
        raise IngestionError(
            f"{source_name}: the response was not valid JSON."
        ) from exc


def build_nyc311_where(start_date, end_date, complaint_types):
    """Build a half-open time range and optional complaint-type filter."""
    end_exclusive = end_date + timedelta(days=1)

    where = (
        f"created_date >= '{start_date.isoformat()}T00:00:00' "
        f"AND created_date < '{end_exclusive.isoformat()}T00:00:00'"
    )

    if complaint_types:
        quoted_types = ", ".join(
            "'" + item.replace("'", "''") + "'"
            for item in complaint_types
        )
        where += f" AND complaint_type IN ({quoted_types})"

    return where


def ingest_nyc311(base_url, start_date, end_date, page_size, run_id):
    """Download NYC 311 records using cursor-based pagination."""
    import json

    complaint_types = [
        item.strip()
        for item in os.environ.get("NYC311_COMPLAINT_TYPES", "").split(",")
        if item.strip()
    ]

    where = build_nyc311_where(start_date, end_date, complaint_types)
    config = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "complaint_types": complaint_types,
    }

    checkpoint_path = ROOT / "data" / "raw" / "nyc311" / ".cursor_checkpoint.json"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    cursor_created_date = os.environ.get("NYC311_START_CREATED_DATE", "").strip()
    cursor_unique_key = os.environ.get("NYC311_START_UNIQUE_KEY", "").strip()
    offset = int(os.environ.get("NYC311_START_OFFSET", "0"))

    if bool(cursor_created_date) != bool(cursor_unique_key):
        raise IngestionError(
            "NYC 311: both cursor environment variables must be set together."
        )

    if checkpoint_path.exists():
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if checkpoint.get("config") == config:
                cursor_created_date = checkpoint["cursor_created_date"]
                cursor_unique_key = checkpoint["cursor_unique_key"]
                offset = int(checkpoint["next_offset"])
                print(
                    "Resuming from saved checkpoint: "
                    f"{cursor_created_date}, unique_key={cursor_unique_key}"
                )
        except (OSError, ValueError, KeyError, TypeError):
            print("Existing checkpoint could not be read; using the configured cursor.")

    print("\nStarting NYC 311 ingestion...")
    print(f"Date range: {start_date} to {end_date} (inclusive)")
    print(f"Complaint-type filter: {complaint_types or 'none'}")
    print(f"Page size: {page_size}")

    if cursor_created_date and cursor_unique_key:
        print(
            f"Starting after: {cursor_created_date}, "
            f"unique_key={cursor_unique_key}"
        )

    total_records = 0
    total_pages = 0

    while True:
        page_where = where

        if cursor_created_date and cursor_unique_key:
            escaped_key = cursor_unique_key.replace("'", "''")
            page_where += (
                " AND (created_date > "
                f"'{cursor_created_date}' OR "
                "(created_date = "
                f"'{cursor_created_date}' AND "
                f"unique_key > '{escaped_key}'))"
            )

        params = {
            "$where": page_where,
            "$order": "created_date ASC, unique_key ASC",
            "$limit": page_size,
        }

        response = request_with_retry(base_url, params, "NYC 311")

        try:
            save_raw(
                "nyc311",
                f"{run_id}_offset_{offset}.json",
                response.content,
            )
            records = parse_json_response(response, "NYC 311")
        finally:
            response.close()

        if not isinstance(records, list):
            raise IngestionError("NYC 311: expected a JSON array of records.")

        if not records:
            print("NYC 311: no more records after the current cursor.")
            break

        last_record = records[-1]
        last_created_date = last_record.get("created_date")
        last_unique_key = last_record.get("unique_key")

        if not last_created_date or last_unique_key is None:
            raise IngestionError(
                "NYC 311: the last record lacks created_date or unique_key."
            )

        cursor_created_date = str(last_created_date)
        cursor_unique_key = str(last_unique_key)
        next_offset = offset + len(records)

        checkpoint_data = {
            "config": config,
            "cursor_created_date": cursor_created_date,
            "cursor_unique_key": cursor_unique_key,
            "next_offset": next_offset,
        }
        temp_path = checkpoint_path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(checkpoint_data, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(checkpoint_path)

        total_pages += 1
        total_records += len(records)

        print(
            f"NYC 311 page {total_pages}: {len(records)} records; "
            f"saved-file offset label={offset}; "
            f"last record={cursor_created_date}, key={cursor_unique_key}"
        )

        offset = next_offset

        if len(records) < page_size:
            print("NYC 311: final partial page received.")
            break

        time.sleep(0.2)

    print(
        f"NYC 311 complete for this run: {total_records} records "
        f"across {total_pages} pages."
    )
    return total_records, total_pages



def main():
    run_id = get_run_id()

    try:
        start_date, end_date = get_date_range()

        page_size = int(
            os.environ.get("NYC311_PAGE_SIZE", "1000")
        )
        if not 1 <= page_size <= 50000:
            raise IngestionError(
                "NYC311_PAGE_SIZE must be between 1 and 50000."
            )

        nyc_url = os.environ.get(
            "NYC311_BASE_URL", NYC311_DEFAULT_URL
        )

        RAW_DIR.mkdir(parents=True, exist_ok=True)

        nyc_records, nyc_pages = ingest_nyc311(
            nyc_url,
            start_date,
            end_date,
            page_size,
            run_id,
        )

        print("\nNYC 311 ingestion summary")
        print("-------------------------")
        print(f"Run ID: {run_id}")
        print(f"NYC 311 records: {nyc_records}")
        print(f"NYC 311 pages: {nyc_pages}")
        print(f"Raw data directory: {RAW_DIR.relative_to(ROOT)}")
        print("\nNYC 311 ingestion finished successfully.")
        return 0

    except (IngestionError, ValueError) as exc:
        print(f"\nINGESTION FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
