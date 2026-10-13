# NYC 311 Service Requests and Weather Analysis

## 1. Project Overview

This project investigates whether the volume and types of New York City 311 service requests vary with local weather conditions, time of day, and day of the week.

It combines two public data sources:

- NYC Open Data — 311 Service Requests
- Open-Meteo — Historical Weather API

Hourly weather values are collected for representative points in the five NYC boroughs: Bronx, Brooklyn, Manhattan, Queens, and Staten Island. These values can later be compared with service requests by borough and local time.

The project follows the data lifecycle:

**INGEST → STORE → CLEAN → EXPLORE → MODEL → COMMUNICATE**

M1 focuses on data ingestion, raw data preservation, and validation. The pipeline entry point, `src/ingest.py`, runs `src/ingest_weather.py` and then `src/ingest_nyc311.py` as separate steps and prints a summary of each result. Each ingestion script can also be run on its own. A separate weather-processing script (`src/process_weather.py`) generates derived hourly and daily CSV files for validation.

## 2. Date Range and Variables

The requested date range is **2025-10-12 through 2026-10-11, inclusive**.

NYC 311 records are selected using `created_date`, without a complaint-type filter. Cursor-based pagination supports resuming large downloads from the last successfully saved record.

Hourly weather data is requested for five representative borough coordinates. Variables include:

- Temperature at 2 metres
- Relative humidity
- Precipitation
- Weather code
- Wind speed and direction
- Cloud cover

Weather timestamps are converted from Unix timestamps to the `America/New_York` timezone before local dates and daily summaries are derived.

The Open-Meteo historical archive is based on gridded model/reanalysis data, so the hourly values are modelled estimates for each coordinate point, not direct station measurements.

The five coordinates are representative points, not a dense network covering every neighbourhood. Citywide daily summaries are estimates derived from these points, not official citywide measurements.

## 3. Data Sources

### Source 1: NYC 311 Service Requests

- **Provider:** City of New York / NYC Open Data
- **Dataset:** [311 Service Requests from 2020 to Present](https://data.cityofnewyork.us/Social-Services/311-Service-Requests-from-2020-to-Present/erm2-nwe9)
- **JSON API:** https://data.cityofnewyork.us/resource/erm2-nwe9.json
- **Access:** Public Socrata JSON API
- **Requested interval:** 2025-10-12 through 2026-10-11, inclusive
- **Record identifier:** `unique_key`

At validation time, the local extraction contained 3,953,178 records. The source API count query returned the same total. The latest `created_date` returned by the source was `2026-10-10T03:03:53.000`. The requested end date is the same day the data was retrieved, so the most recent days of the snapshot are expected to be incomplete.

The dataset is publicly accessible, but a dataset-specific redistribution licence has not been confirmed for this project. Raw source files are kept out of Git because of their size and while the applicable terms remain under review.

### Source 2: Open-Meteo Historical Weather

- **Provider:** Open-Meteo
- **Documentation:** [Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)
- **API endpoint:** https://archive-api.open-meteo.com/v1/archive
- **Access:** Public HTTP GET API
- **Requested interval:** 2025-10-12 through 2026-10-11, inclusive
- **Locations:** Five representative borough coordinates
- **Licence:** Creative Commons Attribution 4.0 International (CC BY 4.0)

When publishing results based on Open-Meteo data, include appropriate attribution and a link to the licence. Suggested attribution: "Weather data by Open-Meteo.com."

See [`docs/sources.md`](docs/sources.md) for source metadata and retrieval notes.

## 4. Verified Data Status

The following results were verified locally on 2026-10-11.

### NYC 311

- **Total records:** 3,953,178
- **JSON files:** 263
- **Unique `unique_key` values:** 3,953,178
- **Duplicate keys:** 0
- **Records missing `unique_key`:** 0
- **Unreadable or invalid JSON files:** 0

The local record count matched the source API count query at the time of validation. The source may publish additional or revised records later.

### Weather Data

The raw weather response uses Unix timestamps and is stored locally under `data/raw/weather/`.

| File | Rows | Description |
|---|---:|---|
| `weather_hourly_by_borough.csv` | 43,800 | Hourly values for five borough points |
| `weather_daily_by_borough.csv` | 1,825 | Daily summaries for five boroughs over 365 dates |
| `weather_daily_citywide.csv` | 365 | Estimated daily summaries derived from the five points |

Each borough has 8,760 hourly values in the requested snapshot. All three CSV files passed the expected row-count checks and had no empty cells at the time of validation.

Daylight-saving-time checks also passed: 2025-11-02 has 25 local hourly values per borough, and 2026-03-08 has 23.

These checks establish structural consistency; they do not eliminate uncertainty in the underlying source data.

## 5. Repository Structure

```text
nyc-311-weather-analysis/
├── README.md
├── .env.example
├── .gitignore
├── requirements.txt
├── data/
│   ├── raw/                         # Local source responses; not committed
│   └── processed/
│       ├── weather_hourly_by_borough.csv
│       ├── weather_daily_by_borough.csv
│       └── weather_daily_citywide.csv
├── src/
│   ├── ingest.py                  # Pipeline entry point: runs both ingestion scripts
│   ├── ingest_nyc311.py           # NYC 311 ingestion
│   ├── ingest_weather.py          # Open-Meteo ingestion
│   └── process_weather.py         # Supplementary weather processing
└── docs/
    ├── sources.md
    └── M1-Report.md
```

Raw API responses are kept separate from derived outputs. Raw files and local environment configuration are excluded from Git. The processed weather CSV files can be regenerated using the weather ingestion and processing scripts.

## 6. Requirements

- Python 3.10 or later
- Internet access to the source APIs
- `pip`
- Dependencies listed in `requirements.txt`

## 7. Setup and Execution

Run these commands from the repository root in a Linux/WSL terminal:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Review `.env` and verify the requested date range and NYC 311 settings before starting an extraction. Do not commit `.env`, API credentials, or other secrets.

### Configuration

Settings are read from environment variables (see `.env.example`):

| Variable | Used by | Purpose |
|---|---|---|
| `START_DATE`, `END_DATE` | all scripts | Inclusive date range, `YYYY-MM-DD` |
| `REQUEST_TIMEOUT_SECONDS` | ingestion scripts | HTTP timeout; 120 was used for the large extraction |
| `NYC311_PAGE_SIZE` | `ingest_nyc311.py` | Records per page (1–50000; script default 1000, `.env.example` sets 20000). The verified snapshot mixes several page sizes, see below |
| `NYC311_COMPLAINT_TYPES` | `ingest_nyc311.py` | Optional comma-separated complaint-type filter; empty means all types |
| `NYC311_BASE_URL`, `WEATHER_BASE_URL` | ingestion scripts | Optional endpoint overrides |

`ingest_nyc311.py` requires `START_DATE` and `END_DATE` to be set. Load `.env` into the shell as shown below before running it.

The verified NYC 311 snapshot was not downloaded with a single page size: its 263 raw files hold 45 × 1,000, 26 × 5,000, 5 × 10,000 and 186 × 20,000 records, plus a final partial file of 8,178 records. Because pagination is cursor-based and the page size is not part of the checkpoint configuration, this only changes how records are split across files, not which records were retrieved.

### NYC 311 Ingestion

To run only the NYC 311 extraction:

```bash
set -a
source .env
set +a

export REQUEST_TIMEOUT_SECONDS=120
python -u src/ingest_nyc311.py
```

The extraction may take a long time because the selected interval contains millions of records. The script uses cursor-based pagination and saved checkpoints (`data/raw/nyc311/.cursor_checkpoint.json`) to support resuming interrupted extractions. Do not delete existing raw files or checkpoint files when recovering from a failed run. Review the terminal summary and local files before deciding whether another extraction is needed.

Note: if the checkpoint already points to the end of the requested range, running the script again retrieves no new records and may save an empty page file. Check `data/raw/nyc311/` for empty files after such a run.

### Weather-Only Ingestion and Processing

To retrieve a new weather snapshot without running the large NYC 311 extraction, use:

```bash
set -a
source .env
set +a

export REQUEST_TIMEOUT_SECONDS=120
python -u src/ingest_weather.py
python -u src/process_weather.py
```

The weather ingestion script saves the raw API response using Unix timestamps. The processing script reads the most recently modified `*_weather_unix.json` file in `data/raw/weather/`, converts timestamps to New York local time, and generates hourly, borough-level daily, and estimated citywide daily CSV files under `data/processed/`. These derived files are ignored by Git and can be regenerated from the raw weather response.

### Full Pipeline

To run both ingestion scripts in sequence (weather first, then NYC 311):

```bash
set -a
source .env
set +a

export REQUEST_TIMEOUT_SECONDS=120
python -u src/ingest.py
```

This downloads a new weather snapshot every time it is run. It does not run `process_weather.py`; run that script separately afterwards.

## 8. Validation and Join Strategy

NYC 311 validation checks include:

- JSON readability
- Total record count
- Presence and uniqueness of `unique_key`
- Comparison of the local count with a source API count query

Weather validation checks include:

- Expected hourly array lengths
- Requested local-date coverage
- Unique and consecutive UTC timestamps
- Expected row counts in derived CSV files
- Correct handling of daylight-saving-time transitions

For later analysis, service requests can be associated with weather using borough and local hour. NYC 311 `created_date` values are published without a timezone offset and are treated as New York local time. Localize them to `America/New_York` (do not convert them from UTC) before joining with weather timestamps. Two daylight-saving-time edge cases need explicit handling: 2025-11-02 01:00–01:59 occurs twice (ambiguous local times), and 2026-03-08 02:00–02:59 does not exist (nonexistent local times). Records with missing or ambiguous borough values may not match a borough reference point.

Daily files can support comparisons of complaint volume with daily weather summaries. Such relationships are observational and do not, by themselves, prove that weather caused changes in complaints.

## 9. Known Limitations

- **Incomplete recent days:** The requested end date equals the retrieval date, so the last days of the NYC 311 snapshot (and possibly of the weather data) are incomplete or preliminary. The final hours of the weather snapshot lie after the retrieval time and are therefore not settled historical values.
- **Weather grid resolution:** The five points are only a few kilometres apart and the historical archive is based on gridded data, so neighbouring boroughs may have very similar weather series. This has not yet been checked and should be examined before drawing borough-level conclusions.
- **Modelled weather values:** The hourly weather values are modelled estimates, not direct station measurements.
- **Timestamp edge cases:** NYC 311 `created_date` values have no timezone offset and must be localized to New York time; ambiguous and nonexistent local hours around the daylight-saving-time transitions need an explicit rule in the join step.
- **Live source:** NYC 311 may publish additional or revised records after retrieval, so later counts may differ.

See [`docs/M1-Report.md`](docs/M1-Report.md) for the full list.

## 10. Current Status

**M1 data ingestion and local data validation are complete for the retrieved source data.** The NYC 311 record count matched the source API count at the time of verification. The hourly weather snapshot and all three derived weather CSV files were generated and passed the recorded structural checks.

Source datasets may change after retrieval, particularly as recent records are published. For reproducibility, retain the source descriptions, raw-file inventory, and verification results in [`docs/M1-Report.md`](docs/M1-Report.md).

## 11. Team

- Şeyma Nur Demirkoparan — GitHub: `@seng-210717026`
- Melike Aldemir — GitHub: `@se-210717019`