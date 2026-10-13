# Data Source Cards

This document records the provenance, scope, access method, and known limitations of the two data sources used in the NYC 311 Service Requests and Weather Analysis project.

**Last updated:** 2026-10-13 (data verification performed on 2026-10-11)

## Source 1: NYC 311 Service Requests

- **source_name:** NYC 311 Service Requests from 2020 to Present
- **provider:** City of New York / NYC Open Data; service-request data provided through NYC 311
- **url:** [311 Service Requests from 2020 to Present](https://data.cityofnewyork.us/Social-Services/311-Service-Requests-from-2020-to-Present/erm2-nwe9)
- **api_url:** <https://data.cityofnewyork.us/resource/erm2-nwe9.json>
- **access_method:** Public Socrata JSON REST API; no API key is currently configured for this project.
- **retrieval_script:** `src/ingest_nyc311.py` (also run by the pipeline entry point `src/ingest.py`).
- **retrieval_parameters:** `$where` on `created_date` (half-open range: start date at 00:00:00 up to, but not including, the day after the end date); `$order` by `created_date ASC, unique_key ASC`; `$limit` equal to the configured page size; no complaint-type filter.
- **page_size:** Mixed. The script default is 1,000 and `.env.example` sets 20,000. The 263 raw files hold 45 × 1,000, 26 × 5,000, 5 × 10,000 and 186 × 20,000 records, plus one final partial file of 8,178 records (total 3,953,178; checked 2026-10-13). The page size is not part of the checkpoint configuration and was therefore changed between runs; the exact run history was not recorded. Page size affects only how records are split across files, not which records are retrieved.
- **licence:** A dataset-specific redistribution licence has not been confirmed for this project.
- **terms_notes:** The dataset is publicly accessible and updated over time. Review the current dataset and portal terms before redistributing raw records. Raw source files are kept outside the public repository because of their size and while applicable redistribution permissions remain unconfirmed. Preserve retrieval metadata and source URLs for provenance.
- **update_cadence:** The dataset is updated daily.
- **requested_coverage:** `created_date` from 2025-10-12 through 2026-10-11, inclusive.
- **observed_coverage:** Earliest observed `created_date`: `2025-10-12T00:00:00.000`. Latest observed `created_date`: `2026-10-10T03:03:53.000`.
- **final_records_saved:** 3,953,178 records.
- **raw_json_page_files:** 263 files, saved under `data/raw/nyc311/`. A cursor checkpoint file (`.cursor_checkpoint.json`) is kept in the same directory.
- **api_count_query:** The API count query returned 3,953,178 records at validation time, matching the local record count.
- **validation_status:** The local audit found 3,953,178 unique `unique_key` values, zero duplicate keys, zero records missing `unique_key`, and zero unreadable or invalid JSON files. These checks were run as local verification steps on 2026-10-11 and are not part of a repository script.
- **record_meaning:** One record represents one NYC 311 service request. The field `unique_key` identifies a request. Individual JSON objects may omit fields whose values are null, and the published schema may change over time.
- **join_key:** Borough plus `created_date` normalized to the local hour in `America/New_York`. This can be used to associate a request with the corresponding borough reference point and hourly weather value in a later milestone. Requests with missing or ambiguous borough values may not join cleanly. `created_date` has no timezone offset and is treated as local New York time; it must be localized, not converted from UTC. DST-ambiguous (2025-11-02 01:00–01:59) and nonexistent (2026-03-08 02:00–02:59) local hours must be handled explicitly when joining.
- **first_retrieved:** `2026-10-11T12:34:09Z` — the run identifier (UTC) of the earliest raw page file retained in `data/raw/nyc311/` (`20261011T123409_616565Z_offset_0.json`). Any earlier test requests are not documented by a retained raw file.
- **full_range_completed_at:** An exact UTC completion timestamp was not retained in the available verification notes. The completed local snapshot was verified on 2026-10-11.
- **known_issues:**
  - NYC Open Data is a live dataset, so record counts and field values may change after retrieval.
  - The requested interval contains millions of records. High-offset requests encountered read timeouts, and cursor-based pagination using `created_date` and `unique_key` was used to resume extraction.
  - The requested end date is the same day as the retrieval, and the latest observed record (2026-10-10 03:03:53) predates it. Because the source is updated daily, the last days of the snapshot should be treated as incomplete. This does not prove complete coverage of every hour or date earlier in the range either. A later milestone should define an analysis cut-off a few days before the retrieval date.
  - If the checkpoint already points to the end of the range, re-running the script retrieves no new records and may save an empty page file. Check the raw directory after such a run.
  - A crash between saving a raw page and writing the checkpoint could cause the same page to be downloaded twice on restart. No duplicates were found in the verified snapshot, but later stages should deduplicate on `unique_key`.
  - `created_date` carries no timezone offset. It is treated as New York local time, and ambiguous and nonexistent local hours around the daylight-saving-time transitions need an explicit rule in the join step.
  - Future count comparisons should record the query time and investigate any discrepancy.

## Source 2: Open-Meteo Historical Weather

- **source_name:** Open-Meteo Historical Weather API — hourly values
- **provider:** Open-Meteo
- **url:** [Historical Weather API documentation](https://open-meteo.com/en/docs/historical-weather-api)
- **api_url:** <https://archive-api.open-meteo.com/v1/archive>
- **access_method:** Public HTTP GET API; query parameters specify coordinates, dates, and hourly variables.
- **data_nature:** The historical archive is based on gridded model/reanalysis data, so the hourly values are modelled estimates for each coordinate point, not direct station measurements.
- **retrieval_script:** `src/ingest_weather.py` (also run by the pipeline entry point `src/ingest.py`). Derived files are produced by `src/process_weather.py`.
- **retrieval_parameters:** One request for all five points; `timezone=America/New_York`; `timeformat=unixtime`; temperature in °C, wind speed in km/h, precipitation in mm; hourly variables `temperature_2m`, `relative_humidity_2m`, `precipitation`, `weather_code`, `wind_speed_10m`, `wind_direction_10m`, `cloud_cover`.
- **requested_points:** Bronx (40.8448, -73.8648); Brooklyn (40.6782, -73.9442); Manhattan (40.7831, -73.9712); Queens (40.7282, -73.7949); Staten Island (40.5795, -74.1502). The processing script assigns borough names to the response locations by their order, matching the order of the request.
- **licence:** Creative Commons Attribution 4.0 International (CC BY 4.0).
- **terms_notes:** Attribute Open-Meteo, link to the applicable CC BY 4.0 licence, and indicate changes when distributing adapted data. Suggested attribution: "Weather data by Open-Meteo.com." Review current provider terms for uses beyond this academic project.
- **update_cadence:** Historical archive; availability and revision timing for recent dates depend on the data product and provider update schedule.
- **requested_coverage:** 2025-10-12 through 2026-10-11, inclusive, for five representative coordinate points corresponding to the Bronx, Brooklyn, Manhattan, Queens, and Staten Island.
- **observed_coverage:** 8,760 hourly values per point. After conversion to `America/New_York`, the processed local dates run from 2025-10-12 through 2026-10-11.
- **final_values_saved:** 43,800 hourly values across the five points.
- **raw_snapshot_file:** `data/raw/weather/20261011T183814Z_weather_unix.json`.
- **snapshot_file_timestamp:** `2026-10-11T18:38:14Z`, as indicated by the filename. A separate process-exit timestamp was not independently recorded.
- **superseded_raw_file:** `data/raw/weather/20261011T161302_789888Z_weather.json` is an earlier raw response that is retained but not used for processing. `src/process_weather.py` reads only `*_weather_unix.json` files.
- **derived_outputs:**
  - `data/processed/weather_hourly_by_borough.csv` — 43,800 rows.
  - `data/processed/weather_daily_by_borough.csv` — 1,825 rows.
  - `data/processed/weather_daily_citywide.csv` — 365 rows.
- **validation_status:** Array lengths, unique and consecutive UTC timestamps, and local-date coverage are checked inside `src/process_weather.py`. Output row counts, the absence of empty cells, and the daylight-saving-time hour counts were confirmed as local verification steps on 2026-10-11.
- **record_meaning:** One raw hourly record represents one hourly weather value set at one requested coordinate point. Variables include temperature at 2 metres, relative humidity, precipitation, weather code, wind speed, wind direction, and cloud cover.
- **join_key:** Borough label associated with the configured coordinate point plus the hourly timestamp normalized to `America/New_York`. Timestamp conversion is handled by the weather-processing script before any later join.
- **first_retrieved:** `2026-10-11T16:13:02Z` — the run identifier (UTC) of the earliest raw weather file retained in `data/raw/weather/` (`20261011T161302_789888Z_weather.json`, see `superseded_raw_file`). The snapshot actually used is the Unix-timestamp file listed above (`2026-10-11T18:38:14Z`).
- **known_issues:**
  - The five coordinates are representative points, not a dense measurement network covering every neighbourhood. Weather at one point may not represent an entire borough.
  - The historical archive is based on gridded model data, and the five points are only a few kilometres apart. Neighbouring boroughs may therefore receive very similar or identical hourly series. This has not been examined in M1 and should be checked before borough-level weather conclusions are drawn.
  - The hourly values are modelled estimates, not direct station measurements.
  - The citywide daily summaries are estimates derived from the five selected points, not official citywide measurements.
  - Values for the most recent days are preliminary and may be revised by the provider. The last hourly value (2026-10-11 23:00 local) lies after the snapshot time (2026-10-11T18:38Z), so the final hours cannot be settled historical values.  
  - The processed output includes 25 local hourly values on 2025-11-02 and 23 on 2026-03-08 because of daylight-saving-time transitions.
  - The daily `weather_code_mode` column picks an arbitrary value when several codes tie, and the mean wind direction is an unweighted circular mean.
  - Structural checks do not eliminate uncertainty in the underlying weather data.

## Retrieval and Validation Notes

The verification results recorded on 2026-10-11 are documented in [`M1-Report.md`](M1-Report.md).

The NYC 311 count query and local record count both returned 3,953,178 records at validation time. The exact UTC timestamp of the count query was not retained. The Open-Meteo snapshot contains 43,800 hourly values across the five points, and its three derived CSV files passed the recorded row-count and empty-cell checks.

The NYC 311 JSON files and raw Open-Meteo responses are retained locally and excluded from Git, because of their size and while redistribution terms for the NYC 311 data remain unconfirmed. The weather CSV files are derived local outputs, also excluded from Git, and can be regenerated from the raw weather snapshot using `src/process_weather.py`.

Future runs should record the UTC time of any count query, the completion time of each extraction, and the request parameters alongside the raw files.