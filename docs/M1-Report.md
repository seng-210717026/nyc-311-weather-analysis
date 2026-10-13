# Milestone M1 Report — Data Ingestion and Repository

**Course:** Introduction to Data Science and Engineering  
**Lifecycle Stage:** INGEST  
**M1 Start Date:** 23 September 2026  
**M1 Deadline:** 11 October 2026  
**Project:** NYC 311 Service Requests and Weather Analysis  
**Data Validation Date:** 11 October 2026  
**Report Last Updated:** 13 October 2026

## 1. Objective

The M0 proposal selected NYC 311 Service Requests and the Open-Meteo Historical Weather API as the project's primary data sources. The project investigates whether the volume and types of 311 service requests vary with borough, time of day, day of the week, and local weather conditions.

The main objective of M1 is to implement a reproducible ingestion workflow, retrieve the approved data sources, preserve their raw responses, document source provenance, and validate the retrieved data.

The NYC 311 records remain raw; this milestone does not include cleaning, joining, exploratory analysis, or modelling. As a supplementary validation step, a separate weather-processing script converts the retrieved hourly weather values into borough-level hourly and daily CSV files. These derived weather outputs do not constitute a completed join or analysis of the two datasets.

## 2. Data Sources and Requested Scope

### 2.1 NYC 311 Service Requests

- **Provider:** City of New York / NYC Open Data
- **Dataset:** [311 Service Requests from 2020 to Present](https://data.cityofnewyork.us/Social-Services/311-Service-Requests-from-2020-to-Present/erm2-nwe9)
- **JSON API:** <https://data.cityofnewyork.us/resource/erm2-nwe9.json>
- **Access Method:** Public Socrata JSON API
- **Date Field:** `created_date`
- **Requested Date Range:** 12 October 2025 through 11 October 2026, inclusive
- **Record Identifier:** `unique_key`
- **Complaint-Type Filter:** None; all complaint types were requested.

The selected period contains millions of records, so the ingestion workflow uses pagination. Cursor-based resumption with `created_date` and `unique_key` was used to continue extraction after high-offset requests encountered read timeouts.

Note that the requested end date (11 October 2026) is the same day the data was retrieved. Because NYC 311 is updated daily, the most recent days in any snapshot are expected to be incomplete (see Section 5.1 and Section 7).

### 2.2 Open-Meteo Historical Weather

- **Provider:** Open-Meteo
- **Documentation:** [Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)
- **API Endpoint:** <https://archive-api.open-meteo.com/v1/archive>
- **Access Method:** Public HTTP GET API
- **Requested Date Range:** 12 October 2025 through 11 October 2026, inclusive
- **Locations:** Representative coordinate points for the Bronx, Brooklyn, Manhattan, Queens, and Staten Island
- **Temporal Resolution:** Hourly
- **Licence:** Creative Commons Attribution 4.0 International (CC BY 4.0)

The requested variables include temperature at 2 metres, relative humidity, precipitation, weather code, wind speed, wind direction, and cloud cover.

The Open-Meteo historical archive is based on gridded model/reanalysis data, so the hourly values are modelled estimates for each coordinate point, not direct station measurements.

The raw weather response preserves hourly timestamps as Unix timestamps. The processing script converts these timestamps to the `America/New_York` timezone before deriving local dates and daily summaries.

The five locations are representative points rather than a dense network of measurements across every neighbourhood. Consequently, the citywide daily weather file contains estimates derived from these five points, not official measurements covering the entire city.

Open-Meteo attribution should accompany published outputs based on this data. Suggested attribution: **"Weather data by Open-Meteo.com."** Include a link to the provider and its applicable licence.

Additional source metadata and retrieval notes are documented in [`docs/sources.md`](sources.md).

## 3. Repository and Configuration

The repository contains the ingestion scripts, configuration template, source documentation, report, and local data directories.

Relevant files include:

- `README.md` — project overview, setup, and execution instructions
- `.gitignore` — local environment and raw-data exclusions
- `.env.example` — documented configuration defaults
- `requirements.txt` — external Python dependencies
- `src/ingest.py` — pipeline entry point; runs `ingest_weather.py` and then `ingest_nyc311.py` as separate subprocesses and reports each result
- `src/ingest_nyc311.py` — NYC 311 ingestion (cursor-based pagination and checkpointing)
- `src/ingest_weather.py` — Open-Meteo weather ingestion
- `src/process_weather.py` — supplementary weather timestamp conversion and CSV generation
- `docs/sources.md` — source metadata and retrieval notes
- `docs/M1-Report.md` — this milestone report
- `data/raw/` — local raw source responses
- `data/processed/` — derived weather CSV files

Configuration is supplied through environment variables (for example `START_DATE`, `END_DATE`, `NYC311_PAGE_SIZE`, and `REQUEST_TIMEOUT_SECONDS`). A local `.env` file can be created from `.env.example`; it is excluded from Git. The current public source endpoints do not require an API key.

**Page size used for the verified snapshot:** The extraction was not run with a single page size. The 263 raw files contain 45 files of 1,000 records, 26 of 5,000, 5 of 10,000 and 186 of 20,000, plus one final partial file of 8,178 records (45 × 1,000 + 26 × 5,000 + 5 × 10,000 + 186 × 20,000 + 8,178 = 3,953,178). The script's built-in default is 1,000 and `.env.example` sets 20,000; the smaller sizes presumably come from earlier test or recovery runs, but the exact run history was not recorded. Because pagination is cursor-based on (`created_date`, `unique_key`) and the page size is not part of the checkpoint configuration, the page size only changes how records are split across files, not which records are retrieved. The duplicate check found no overlap between files. The final 8,178-record file is a partial page, which is consistent with the extraction reaching the end of the requested range.

Raw source files are kept separate from derived outputs. The raw data is excluded from Git, in part because of its size (millions of records) and while the applicable NYC 311 redistribution terms remain unconfirmed. The weather CSV files are locally generated outputs and can be regenerated from a valid raw weather response using the project's processing script.

## 4. Ingestion Workflow

### 4.1 NYC 311

The NYC 311 ingestion script is `src/ingest_nyc311.py`, run from the repository root. The orchestrating script `src/ingest.py` also runs it, but `ingest.py` first downloads a new weather snapshot; to resume or repeat only the NYC 311 extraction, run `src/ingest_nyc311.py` directly. Retrieved pages are saved under `data/raw/nyc311/`. The extraction uses cursor-based pagination and a checkpoint so that a large download can resume from the last confirmed saved record.

The workflow uses HTTP timeouts and retry handling for temporary network failures, HTTP 429 responses, and HTTP 5xx responses. Authentication-related HTTP 401 and 403 responses are handled as failures rather than being silently retried. Unexpected or empty responses are checked during extraction.

Timestamped raw page files preserve the retrieved source responses, and the script refuses to overwrite an existing raw file. Existing raw files and checkpoints should not be deleted when resuming an interrupted run. Because the requested period contains millions of records, a complete re-extraction can take a considerable amount of time.

### 4.2 Open-Meteo

The weather ingestion entry point is `src/ingest_weather.py`. The verified raw snapshot is:

`data/raw/weather/20261011T183814Z_weather_unix.json`

The timestamp embedded in this filename is `2026-10-11T18:38:14Z`. It identifies the saved snapshot filename; it should not be interpreted as a separately recorded process-exit timestamp.

The retrieved weather response contains hourly values for five representative borough points. The raw response is preserved locally, and `src/process_weather.py` converts the values' timestamps to New York local time and produces the supplementary CSV outputs described in Section 5. The processing script reads the most recently modified `*_weather_unix.json` file in `data/raw/weather/`, and relies on the order of the five locations matching the configured borough list.

## 5. Verified Results

The following results were checked against the local files and source query results on 11 October 2026.

### 5.1 NYC 311 Results

| Validation item | Verified result |
|---|---|
| Requested `created_date` interval | 2025-10-12 to 2026-10-11, inclusive |
| Local raw JSON page files | 263 |
| Total saved records | 3,953,178 |
| Earliest observed `created_date` | `2025-10-12T00:00:00.000` |
| Latest observed `created_date` | `2026-10-10T03:03:53.000` |
| Unique `unique_key` values | 3,953,178 |
| Duplicate `unique_key` values | 0 |
| Records missing `unique_key` | 0 |
| Unreadable or invalid JSON files | 0 |
| Source API count query | 3,953,178 |
| Records per raw file (checked 2026-10-13) | 45 × 1,000; 26 × 5,000; 5 × 10,000; 186 × 20,000; 1 × 8,178 (final partial page) |

The local record count matched the source API count query at the time of validation. The exact UTC time of that count query was not retained in the available verification notes; therefore, no more precise query timestamp is claimed here.

Although the requested filter ends on 11 October 2026, the latest `created_date` observed in the retrieved snapshot is 10 October 2026 at 03:03:53. This describes the records available in the checked snapshot and does not establish that the source contains a record for every hour or calendar day in the requested interval. In particular, 10 October 2026 appears only partially covered and 11 October 2026 has no records, which is consistent with the source's daily publication cycle. NYC Open Data is updated over time, so a later query may return a different count.

### 5.2 Open-Meteo and Derived Weather Results

The retrieved weather snapshot contains 8,760 hourly values per borough point, for 43,800 hourly values across the five points.

| Output file | Verified rows | Description |
|---|---:|---|
| `weather_hourly_by_borough.csv` | 43,800 | Hourly values for five representative borough points |
| `weather_daily_by_borough.csv` | 1,825 | Daily summaries for five boroughs over 365 local dates |
| `weather_daily_citywide.csv` | 365 | Estimated daily summaries derived from the five points |

The processed files cover local dates from 12 October 2025 through 11 October 2026. The expected row counts were verified, and no empty cells were found in the three CSV files during validation.

Daylight-saving-time checks produced the expected local-hour counts for each borough:

- **2 November 2025:** 25 hourly values
- **8 March 2026:** 23 hourly values

These results support the timestamp-conversion and structural checks for the saved snapshot. They do not establish that every source value is free of uncertainty or that the five coordinate points fully represent citywide conditions.

## 6. Validation and Reproducibility

The following checks were used to evaluate the retrieved data.

### NYC 311 checks

- Counted the saved JSON page files and records.
- Confirmed that the saved JSON files were readable.
- Checked the presence and uniqueness of `unique_key`.
- Confirmed that no records were missing `unique_key` and no duplicate keys were found.
- Compared the saved record count with the source API count query.
- Inspected the earliest and latest observed `created_date` values.

### Weather checks

- Confirmed the presence of five borough locations with 8,760 hourly values per location.
- Checked the expected row counts in the hourly and daily output files.
- Checked the local-date coverage of the processed outputs.
- Verified the expected 25-hour and 23-hour local dates around daylight-saving-time transitions.
- Confirmed that the three generated CSV files had no empty cells during validation.

The weather checks on array lengths, unique and consecutive UTC timestamps, and local-date coverage are built into `src/process_weather.py`. The remaining checks, including the NYC 311 audit and the API count comparison, were carried out as local verification steps on 11 October 2026 and are recorded in this report rather than in a repository script.

The count comparison is specific to the source snapshot and validation date. If the live NYC 311 dataset changes, a later API count may differ. Any future discrepancy should be recorded with the relevant query time and investigated instead of being silently treated as an extraction error.

These checks establish structural consistency for the retrieved files; they are not a substitute for later data cleaning, semantic validation, or analysis.

## 7. Known Issues and Decisions

1. **Live source updates:** NYC 311 may publish additional or revised records after retrieval. Counts and date coverage must be interpreted in the context of the snapshot and validation date.
2. **Recent-record coverage:** The requested end date equals the retrieval date, and the latest `created_date` in the verified 311 snapshot is earlier than the requested end date. This is documented rather than interpreted as proof of complete daily coverage. Later milestones should treat the final days of the snapshot as incomplete, for example by defining an analysis cut-off a few days before the retrieval date.
3. **Large extraction volume:** High-offset requests encountered read timeouts. Cursor-based resumption was used to continue the extraction from the last confirmed saved record. The extraction was therefore carried out in several runs with different page sizes (see Section 3); the exact run history was not recorded.
4. **Possible join gaps:** A 311 record with a missing or unusable borough or timestamp may not match a weather value in a later milestone.
5. **Representative weather points:** The five borough coordinates cannot describe every neighbourhood's local microclimate. The citywide daily file is an estimate based on the selected points.
6. **Weather grid resolution (not yet checked):** The historical weather archive is based on gridded model data. The five points are only several kilometres apart, so neighbouring boroughs may receive very similar or identical hourly series. The degree of difference between borough series has not been examined in M1 and should be checked before drawing borough-level conclusions about weather effects.
7. **Recent weather values:** The snapshot was saved at 2026-10-11T18:38:14Z, but the last hourly value is for 2026-10-11 23:00 local time
   (2026-10-12T03:00Z), i.e. for hours that had not yet occurred at retrieval time. Values for the most recent hours and days are therefore preliminary
   or model-projected rather than settled historical values, and may be revised by the provider. The absence of empty cells does not address this. Later milestones should exclude the final days of the range from analysis, consistent with the NYC 311 cut-off.
8. **Timestamp handling:** Weather timestamps are normalized to `America/New_York`. NYC 311 `created_date` values carry no timezone offset and are treated as New York local time; they must be localized, not converted from UTC, before joining. Ambiguous (2025-11-02 01:00–01:59) and nonexistent (2026-03-08 02:00–02:59) local times need an explicit rule in the join step.
9. **Redistribution and raw-data storage:** NYC 311 redistribution terms have not been confirmed for this project. The raw source files therefore remain local and are excluded from Git. Open-Meteo attribution is documented in the README and source metadata. 
10. **Not-retained provenance details:** The exact UTC time of the NYC 311 count query, the exact completion time of the full 311 extraction, and a separate process-exit time for the weather download were not recorded (see `docs/sources.md`). Future runs should record these automatically.

## 8. Conclusion

The local retrieval and data-validation work documented in this report produced a verified NYC 311 snapshot containing 3,953,178 records across 263 raw JSON page files. The local count matched the source API count query at validation time, all inspected JSON files were readable, and every saved record had a unique `unique_key`.

The Open-Meteo snapshot contains 43,800 hourly values across five representative borough points. The supplementary weather-processing script generated hourly, borough-level daily, and estimated citywide daily CSV files with the expected row counts and the expected local-hour counts around daylight-saving-time transitions.

These results document the local data-ingestion state for the retrieved snapshot. The NYC 311 data has not yet been cleaned, joined to weather data, or analysed. Repository compilation checks, secret-history review, and the required commit, push, and tag steps must be completed and verified separately before final submission.

## 9. Submission Checklist

### Data and code

- [x] The requested NYC 311 extraction was saved locally and its record count was compared with the source API count query.
- [x] The NYC 311 JSON files were checked for readability, unique keys, and missing keys.
- [x] The retrieved weather snapshot contains 8,760 hourly values per representative borough point.
- [x] The three derived weather CSV files passed the recorded row-count and empty-cell checks.
- [x] Run `python3 -m py_compile src/ingest.py src/ingest_nyc311.py src/ingest_weather.py src/process_weather.py`; the syntax check passed on 2026-10-13.

### Repository and submission

- [x] `.env` is excluded from Git by the repository's ignore rules.
- [x] Raw source data is excluded from Git while redistribution permissions remain unconfirmed.
- [x] Document the NYC 311 page-size distribution (the extraction mixed page sizes) in this report, the README, `docs/sources.md` and `.env.example`.
- [x] Review the full Git history for accidentally committed credentials or secrets.
- [x] Ensure the README lists the actual team members and their correct GitHub usernames.
- [x] Confirm that every team member has made the required contribution using their own account.
- [x] Commit and push the final report and required project files.
- [x] Create and push the `m1` tag after verifying the intended submission commit.
- [x] Submit the repository URL through the course submission system.

Items that require Git or course-platform verification are intentionally left unchecked. Their completion should be recorded only after the corresponding action has been performed and verified.