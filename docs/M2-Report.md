# **Milestone M2 Report — Schema Design and Database Load**

**Course:** Introduction to Data Science and Engineering
**Lifecycle Stage:** STORE
**M2 Deadline:** 25 October 2026
**Late Deadline:** 1 November 2026
**Project:** NYC 311 Service Requests and Weather Analysis
**Report Last Updated:** 23 October 2026
**Team Work:** Both team members collaborated on the M2 implementation and testing, as confirmed by the team.

## **1. Objective**

M1 established a reproducible ingestion workflow and preserved raw NYC 311 service-request records and Open-Meteo weather responses. The objective of M2 is to define a relational schema for these landed data, load them from local raw files, enforce database constraints, and demonstrate that loading is repeatable and atomic.

The project investigates whether the volume and types of NYC 311 service requests vary by borough, local time, day, and weather conditions. M2 prepares the structured storage layer for later milestones. It does not attempt to complete the data-cleaning, exploratory-analysis, modelling, or scheduling work assigned to later stages.

## **2. Data Sources and Scope**

### **2.1 NYC 311 Service Requests**

- **Provider:** City of New York / NYC Open Data
- **Dataset:** [311 Service Requests from 2020 to Present](https://data.cityofnewyork.us/Social-Services/311-Service-Requests-from-2020-to-Present/erm2-nwe9)
- **JSON endpoint:** `https://data.cityofnewyork.us/resource/erm2-nwe9.json`
- **Requested `created_date` range:** 12 October 2025 through 11 October 2026, inclusive
- **Source event identifier:** `unique_key`
- **Complaint-type filter:** None; all observed complaint types were retained
- **Raw input directory:** `data/raw/nyc311/`

The loader reads the previously saved JSON files rather than requesting new data from the API. This keeps M2 separate from ingestion and makes the database rebuild depend on the landed snapshot.

### **2.2 Open-Meteo Historical Weather**

- **Provider:** Open-Meteo
- **API documentation:** [Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)
- **Endpoint:** `https://archive-api.open-meteo.com/v1/archive`
- **Raw input file:** `data/raw/weather/20261011T183814Z_weather_unix.json`
- **Snapshot timestamp encoded in filename:** `2026-10-11T18:38:14Z`
- **Locations:** Five representative points for the Bronx, Brooklyn, Manhattan, Queens, and Staten Island
- **Temporal resolution:** Hourly
- **Timezone used for local-time interpretation:** `America/New_York`

The weather observations are historical archive/model-grid values for representative coordinates, not direct measurements from a dense network of weather stations. Outputs based on these data should include the attribution **“Weather data by Open-Meteo.com.”** and a link to the provider and applicable licence.

## **3. Repository Changes**

The following files implement the M2 storage layer:

| File | Purpose |
|---|---|
| `sql/schema.sql` | Creates the relational schema and constraints; safe to execute repeatedly |
| `sql/queries/hourly_complaints_vs_weather.sql` | Example analytical query joining request counts to borough-level hourly weather |
| `src/db.py` | Shared SQLite connection helper; enables foreign-key enforcement |
| `src/load.py` | Loads the local NYC 311 and weather raw files into the database |
| `src/checks.py` | Runs schema, constraint, idempotence, and atomicity checks using temporary test data/database copies |
| `scripts/verify_real_db_idempotence.py` | Compares saved real-database before/after hashes and hashes a supplied database |
| `docs/evidence/` | Preserves loader logs, hash snapshots, cold-rebuild verification, passing checks, and atomicity mutation evidence |
| `README.md` | Documents the data model, table grain, decisions, query, results, and build/check commands |
| `docs/sources.md` | Records source details and M2 loading/validation notes |
| `.gitignore` | Excludes the generated database file from Git |
| `docs/M2-Report.md` | This milestone report, implementation history, evidence summary, and checklist |

The generated database is `data/nyc311_weather.db`. It is intentionally excluded from Git because it is a derived artifact and is submitted separately through the course submission system.

## **4. Schema Design**

All nine database tables are declared `STRICT`, and each table contains a `retrieved_at` provenance field. The schema includes entity/dimension tables, event tables, and a quarantine table.

### **4.1 Table Grain and Verified Row Counts**

“One row means” describes the intended grain of each table. The counts below were verified after loading the saved M1 snapshot.

| Table | Grain — one row means | Row count |
|---|---|---:|
| `agencies` | One observed NYC 311 agency code and its associated agency attributes | 16 |
| `boroughs` | One borough/source borough value, including `UNSPECIFIED` | 6 |
| `complaint_types` | One observed source complaint-type value | 194 |
| `request_statuses` | One observed request-status value | 7 |
| `submission_channels` | One observed submission-channel value | 5 |
| `weather_locations` | One configured representative borough weather location | 5 |
| `service_requests` | One NYC 311 event identified by its source `unique_key` | 3,953,178 |
| `weather_observations` | One observation for a weather location and UTC observation timestamp | 43,800 |
| `quarantine_records` | One source record that could not be loaded and was routed to quarantine | 0 |

The `service_requests` natural event identifier is `unique_key`. Weather observations use the composite event key `(weather_location_id, observed_at_utc)`, which prevents duplicate observations for the same location and UTC hour. Entity references are represented by foreign keys rather than repeated free-text labels where the schema has a corresponding entity table.

### **4.2 Key Tests and Findings**

- The raw NYC 311 snapshot contains **3,953,178** records and **3,953,178** distinct `unique_key` values.
- **Zero** records were missing `unique_key`; **zero** duplicate keys were found.
- The audited source key was consistent for checked attributes including `created_date`, complaint type, and borough: no conflicting values were found for the same `unique_key`.
- The weather dataset contains **43,800** observations: 8,760 hourly timestamps for each of five locations. The saved weather series had no duplicate or missing hourly timestamps in the validation audit.
- The primary-key and foreign-key rejection tests are implemented in `src/checks.py` and pass.

### **4.3 Constraints, Provenance, and Quarantine**

The schema uses `STRICT` tables, declared foreign keys, non-null key columns, and event keys appropriate to their grain. The shared `connect()` function in `src/db.py` enables `PRAGMA foreign_keys = ON` immediately after connecting. Every table has a `retrieved_at` field to preserve provenance and support repeatable loading. The schema can be executed repeatedly because table creation uses `CREATE TABLE IF NOT EXISTS`.

A `quarantine_records` table is present. The verified full-data load reported **zero quarantine candidates** and left the quarantine table empty. The full load and the test suite also reported no foreign-key violations.

### **4.4 Missing Values and Timestamp Decisions**

Missing values are not automatically converted to zero. For example, an absent location object remains `NULL`, and a missing `closed_date` remains missing rather than being interpreted as a closure time. In the saved NYC 311 snapshot, **82,051** records lacked a location object; those records were retained.

NYC 311 timestamps do not include a timezone offset and are interpreted as New York local time. Most timestamps can be normalized to UTC, but daylight-saving-time transitions create ambiguous or nonexistent local times. Rather than inventing a UTC instant, the loader preserves the local source value and records the timestamp status; the normalized UTC value remains `NULL` for these exceptional cases.

| Timestamp field | Normalized | Ambiguous local time | Nonexistent local time | Missing |
|---|---:|---:|---:|---:|
| `created_date` | 3,952,381 | 796 | 1 | 0 |
| `closed_date` | 3,773,095 | 757 | 12 | 179,314 |
| `due_date` | 15,007 | 0 | 0 | 3,938,171 |
| `resolution_action_updated_date` | 3,882,616 | 754 | 20 | 69,788 |

These statuses are retained as loading/normalization facts. Decisions about how exceptional timestamps should be handled for later analysis belong to a later milestone.

## **5. Loading Workflow and Results**

### **5.1 How to Build the Database**

Run these commands from the repository root after the M1 raw files have been landed:

```bash
python src/load.py
python src/checks.py
```

`src/load.py` reads local raw files and does not call either source API. It validates and normalizes values before insertion, uses parameterized SQL values, and applies `INSERT ... ON CONFLICT ... DO UPDATE` rather than `INSERT OR REPLACE` or `pandas.to_sql`. The database load runs as a transaction so that a failed load can roll back rather than leave partially written related tables.

The database is reproducible from the raw inputs; it is not committed to Git. The local database file produced for submission is `data/nyc311_weather.db`.

### **5.2 Full-Data Load Summary**

The full load was run successfully and then run again to test idempotence. The second run produced the following results:

| Metric | Verified result |
|---|---:|
| NYC JSON files discovered/read | 263 / 263 |
| NYC 311 records seen | 3,953,178 |
| Valid service-request UPSERT attempts | 3,953,178 |
| Weather source files read | 1 |
| Weather observation UPSERT attempts | 43,800 |
| Quarantine candidates | 0 |
| Empty NYC pages | 0 |
| Numeric source strings converted | 15,484,998 |
| Empty strings converted to `NULL` | 0 |
| Missing location objects retained as `NULL` | 82,051 |
| Foreign-key check | PASS |
| Transaction | Committed successfully |

### **5.3 Table Counts and Idempotence**

On the second run, all table counts were unchanged and no new dimension entities or events were added. A subsequent full-database reload was compared with a baseline recorded before the reload. Row counts and SHA-256 hashes of serialized row contents were unchanged in all nine tables. The hashes include `retrieved_at` and use deterministic `rowid` ordering. This result applies to reloading the same saved source snapshot.

| Table | Count before second run | Count after second run | Net new rows |
|---|---:|---:|---:|
| `agencies` | 16 | 16 | +0 |
| `boroughs` | 6 | 6 | +0 |
| `complaint_types` | 194 | 194 | +0 |
| `request_statuses` | 7 | 7 | +0 |
| `submission_channels` | 5 | 5 | +0 |
| `weather_locations` | 5 | 5 | +0 |
| `service_requests` | 3,953,178 | 3,953,178 | +0 |
| `weather_observations` | 43,800 | 43,800 | +0 |
| `quarantine_records` | 0 | 0 | +0 |

The second run preserved all observed row counts and did not duplicate source events. A further full reload also preserved row counts and row-content hashes across all nine tables. `PRAGMA integrity_check` returned `ok`, and `PRAGMA foreign_key_check` returned no violations in the database validation.

## **6. Checks and Test Results**

`src/checks.py` uses temporary test data and a temporary database rather than modifying the real 4.3 GB database. The recorded test output contains the following successful checks:

- Schema executes repeatedly.
- All required tables are `STRICT`.
- Every table has `retrieved_at`.
- Foreign-key enforcement is enabled.
- A valid service request is accepted.
- A duplicate natural key is rejected.
- A `NULL` primary key is rejected.
- An incorrect data type is rejected.
- An orphan event reference is rejected.
- A normalized timestamp cannot be `NULL` for a record that requires one.
- An ambiguous local timestamp is preserved without inventing UTC.
- Foreign-key integrity check passes.
- Synthetic data loads successfully.
- Loader preserves ambiguous and nonexistent DST timestamps without inventing UTC values.
- A new complaint type creates a dimension member; a missing natural key is quarantined.
- Synthetic-load idempotence compares table row counts and serialized row-content hashes.
- An injected weather value raises the expected `LoadError`.
- Atomicity passes: a failed load leaves table counts and contents unchanged.
- A mutation test replacing `rollback()` with `commit()` triggered the expected atomicity assertion failure.
- Temporary database and fixture data are cleaned up.

**Recorded result:** `ALL CHECKS PASSED`.

The two standard loader outputs and normal check output are committed in `docs/evidence/` as `load-run-1.txt`, `load-run-2.txt`, and `checks.txt`. The additional full-reload log and before/after JSON states are also committed there. `atomicity-mutation-test.txt` records the expected assertion failure when rollback was deliberately replaced with commit; it is not the normal passing test run.

## **7. Analytical Query Demonstration**

The query in `sql/queries/hourly_complaints_vs_weather.sql` demonstrates how service requests can be compared with hourly weather while preserving an explicit result grain.

**Question:** How many NYC 311 requests were recorded for each complaint type in each borough, local date, and local hour, alongside the corresponding hourly weather?

**Result grain:** One row per borough × local date × local hour × complaint type. Requests are counted at the request-event grain before being presented at this aggregate grain. The query joins to weather by the relevant borough location and UTC hour; request records without a valid normalized UTC creation time are excluded from the time-based join rather than assigned an invented instant. The inner join to `weather_locations` also excludes borough `UNSPECIFIED`, which has no representative weather location.

For the local date **12 October 2025**, the query produced **2,448 groups**, covered **118 complaint types**, and represented **9,990 joined requests**. **Zero output groups lacked matching weather** for this one-day test window.

Top five groups by request count in that test window:

| Borough | Local hour | Complaint type | Requests | Temperature | Precipitation |
|---|---:|---|---:|---:|---:|
| BRONX | 00:00 | NOISE - RESIDENTIAL | 133 | 16.9 °C | 0.0 mm |
| BRONX | 22:00 | NOISE - RESIDENTIAL | 110 | 13.5 °C | 1.5 mm |
| BRONX | 23:00 | NOISE - RESIDENTIAL | 108 | 13.6 °C | 1.2 mm |
| BRONX | 20:00 | NOISE - RESIDENTIAL | 107 | 13.1 °C | 0.7 mm |
| BRONX | 01:00 | NOISE - RESIDENTIAL | 105 | 16.7 °C | 0.0 mm |

This is a query and join validation example, not a claim that weather causes a change in complaint volume. Broader exploratory analysis is outside the scope of M2.

## **8. Known Issues and Decisions**

1. **Recent NYC 311 coverage:** The requested interval ends on 11 October 2026, while the latest `created_date` in the checked raw snapshot is `2026-10-10T03:03:53`. The final part of the requested range is therefore not fully represented in the saved snapshot; a future analysis should document an appropriate cut-off.
2. **Local-time exceptions:** `created_date` contains 796 ambiguous local times and one nonexistent local time around the 2025 fall-back and 2026 spring-forward daylight-saving transitions. The loader does not invent UTC values for these rows.
3. **Optional source timestamps:** Many `closed_date`, `due_date`, and `resolution_action_updated_date` values are missing in the source. They remain missing in storage and are not converted to zero or an artificial timestamp.
4. **Missing locations:** 82,051 NYC 311 records have no location object. They are retained with missing location fields; they are not dropped solely because location is missing.
5. **Representative weather points:** Weather values represent five coordinate points snapped to the weather model grid. They do not capture neighbourhood-level microclimates across the city.
6. **Modelled/recent weather values:** Open-Meteo archive values are grid-based estimates. The latest weather hours in the retrieved snapshot may be preliminary or revised by the provider.
7. **No quarantine rows in this snapshot:** The full loader reported zero quarantine candidates and zero rows in `quarantine_records`. The table is included for records that cannot be loaded in other input conditions.
8. **Entity history:** The M2 tables represent the current loaded version of dimension attributes. This milestone does not maintain a full historical dimension history for renamed or reclassified entities.
9. **Analysis scope:** The one-day query verifies the join and result grain; it is not a full statistical analysis or evidence of causality.

## **9. M2 Work Log — Steps Completed**

This section records the main M2 steps completed for this project, including the source audit, schema design, database loading, testing, documentation, and GitHub release actions.

### **9.1 Confirmed the M1 inputs and source keys**

- [x] Used the landed NYC 311 JSON files and the saved Open-Meteo historical response; M2 loading reads local files and does not call the source APIs.
- [x] Audited the 263 NYC 311 JSON page files: 3,953,178 records, 44 source-field names, no unreadable JSON files, and no missing or duplicate `unique_key` values.
- [x] Checked the source natural key against selected attributes, including `created_date`, complaint type, and borough; no conflicts were found for the same `unique_key` in the audited snapshot.
- [x] Checked the weather snapshot for five representative borough points and 8,760 hourly observations per point, totalling 43,800 observations.

### **9.2 Designed the database schema**

- [x] Added `sql/schema.sql` with nine SQLite `STRICT` tables: `agencies`, `boroughs`, `complaint_types`, `request_statuses`, `submission_channels`, `weather_locations`, `service_requests`, `weather_observations`, and `quarantine_records`.
- [x] Defined table grain, event keys, entity keys, relationship foreign keys, key nullability, and `retrieved_at` provenance fields.
- [x] Made schema creation repeatable with `CREATE TABLE IF NOT EXISTS`; the repeat-execution check passes.
- [x] Preserved the original NYC 311 source `unique_key`; used `(weather_location_id, observed_at_utc)` to identify a weather-location/hour observation.
- [x] Retained a quarantine table for records that cannot be loaded; the full verified load reported zero quarantine candidates.

### **9.3 Implemented and ran the loader**

- [x] Added `src/db.py` with the shared database connection helper and foreign-key enforcement enabled immediately after connecting.
- [x] Added `src/load.py` to read the landed raw files, validate and normalize values, and write the schema in one transaction.
- [x] Used parameterized SQL values and `ON CONFLICT ... DO UPDATE` upserts; the loader does not use `pandas.to_sql` or `INSERT OR REPLACE`.
- [x] Loaded 263 NYC JSON files and 3,953,178 request records, plus 43,800 weather observations from the saved weather snapshot.
- [x] Rebuilt the full snapshot from an empty temporary SQLite database: 3,953,178 service requests and 43,800 weather observations were inserted, zero quarantine candidates remained, and the foreign-key check passed. The resulting nine-table content hashes matched the saved full-database after-state; the log is `docs/evidence/cold-rebuild.txt`.
- [x] Retained 82,051 records whose source location object was missing, rather than dropping them for that reason.
- [x] Recorded timestamp-normalization outcomes, including ambiguous and nonexistent local times, without inventing UTC values for those exceptional `created_date` rows.
- [x] Ran the full load twice. On the second run, every table had `+0` net new rows and all row counts were unchanged.
- [x] Compared the real database before and after a subsequent full reload; all nine table row counts and SHA-256 content hashes matched.
- [x] Both saved load summaries reported `Foreign-key check: PASS` and `Transaction committed successfully.`
- [x] Verified `PRAGMA integrity_check` returned `ok` and `PRAGMA foreign_key_check` returned no violations.

### **9.4 Implemented and ran the checks**

- [x] Added `src/checks.py`; it uses temporary test data and a temporary database for tests that intentionally reject data or inject a load failure.
- [x] Verified repeated schema execution, `STRICT` declarations, `retrieved_at`, and foreign-key enforcement.
- [x] Verified rejection of duplicate natural keys, `NULL` primary keys, incorrect numeric types, orphan foreign-key references, and normalized timestamps that are required but missing.
- [x] Verified that an ambiguous source-local timestamp is preserved without assigning an invented UTC timestamp.
- [x] Verified synthetic-load idempotence using row counts and streaming SHA-256 hashes of serialized row contents.
- [x] Injected a load failure; the expected `LoadError` occurred and the atomicity check confirmed row counts and contents were unchanged.
- [x] Verified that replacing `rollback()` with `commit()` triggers the atomicity assertion; restored `src/load.py` byte-for-byte and reran the normal test suite successfully.
- [x] Saved the test output. It ends with `ALL CHECKS PASSED` and confirms temporary test data and databases were cleaned up.

### **9.5 Created and validated the analytical query**

- [x] Added `sql/queries/hourly_complaints_vs_weather.sql` with the result grain stated in the query comments.
- [x] Ran a one-day test for 12 October 2025: 2,448 output groups, 118 complaint types, and 9,990 joined requests represented; no result group in this test window lacked matching weather.
- [x] Documented the query, its result grain, sample output, and interpretation limits in the README and this report.

### **9.6 Updated project documentation and captured evidence**

- [x] Updated `README.md` with the data model/ER diagram, the grain of each table, key and missing-value decisions, known issues, an analytical query example, and database build/check instructions.
- [x] Updated `docs/sources.md` with M2 loading and validation details.
- [x] Updated this report in the repository with project steps, evidence, checklist, and submission status.
- [x] Verified `data/nyc311_weather.db` exists locally (about 4.3 GB) and is ignored by Git, rather than committed to the repository.
- [x] Saved the two full loader logs, normal checks output, the full-reload log, the before/after hash states, the empty-database cold-rebuild log, and the intentional rollback-mutation log under `docs/evidence/`.

### **9.7 Git history and release checkpoint**

- The final M2 files, documentation, tests, and evidence are consolidated into one commit after the pre-M2 base commit `7e90273`.
- The annotated `m2` tag points to that same final M2 commit as `main`.
- The pre-squash history is retained only in the local `backup/m2-before-squash` branch, not in the published `main` history.
