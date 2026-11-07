# Milestone M3 Report — Data Cleaning and Quality

- **Course:** Introduction to Data Science and Engineering
- **Lifecycle Stage:** CLEAN
- **M3 Deadline:** 8 November 2026
- **Late Deadline:** 13 November 2026
- **Project:** NYC 311 Service Requests and Weather Analysis
- **Report Last Updated:** 8 November 2026
- **Team Members:** Şeyma Nur Demirkoparan and Melike Aldemir

## 1. Objective

M2 established the relational storage layer for the NYC 311 Service Requests and Open-Meteo Weather project. The objective of M3 was to investigate the quality of the stored data, identify missing, invalid, unusual, inconsistent, textual, and identity-related values, and implement a cleaned layer without modifying the original M2 tables.

The cleaning process follows three principles: raw source data are never edited, every cleaning decision is implemented in code, and raw values are retained next to cleaned values and explicit quality flags. M3 does not impute missing values or remove unusual observations. It prepares a trustworthy and traceable data layer for the analytical work in M4.

No M2 schema or source-data correction was required during this M3 cleaning milestone.

## 2. Data Sources and Scope

M3 uses the relational database created in M2. The cleaning script reads from the M2 SQLite tables; it does not read directly from the APIs or raw JSON files.

| Source table | Grain | M2 row count |
|---|---|---:|
| `service_requests` | One NYC 311 request per `unique_key` | 3,953,178 |
| `weather_observations` | One hourly observation per weather location and UTC timestamp | 43,800 |

The request data cover five named boroughs and an `UNSPECIFIED` borough group. Weather data contain 8,760 hourly observations for each of five representative borough locations.

The weather values are historical archive/model-grid estimates, not direct measurements at every street or neighbourhood. Analyses using these observations should retain the attribution “Weather data by Open-Meteo.com” and link to the provider and applicable licence.

The M3 cleaning scope focuses on timestamps, coordinates, and the seven weather variables used by the project. Descriptive request fields remain available in the original `service_requests` table and can be joined to the cleaned request projection using `unique_key`.

## 3. Repository Changes

| File | Purpose |
|---|---|
| `sql/clean_schema.sql` | Defines the new STRICT cleaned tables and mapping tables |
| `src/clean.py` | Builds the cleaned layer from M2 tables |
| `src/clean_config.py` | Stores borough-specific IQR thresholds and batch size |
| `src/validate.py` | Executes PASS, WARN, and STOP data-quality checks |
| `src/test_validate_failures.py` | Tests that all five STOP conditions fail in separate temporary databases |
| `src/m3_integrity.py` | Compares row counts and SHA-256 hashes for M2 and M3 tables |
| `notebooks/m3_profile.ipynb` | Contains the profiling investigation and executed outputs |
| `data/mappings/category_alias_map.csv` | Records approved category aliases; header-only in this snapshot |
| `data/mappings/identity_alias_map.csv` | Records approved identity decisions; header-only in this snapshot |
| `docs/M3-Report.md` | Milestone implementation, validation, and submission summary |
| `docs/cleaning_report.md` | Detailed findings, issues register, missingness analysis, flags, thresholds, and limitations |
| `docs/evidence/` | Stores final cleaning, validation, failure-test, rollback, and integrity evidence |
| `README.md` | Documents M3 findings, build commands, report links, and milestone status |

The two mapping CSV files contain their required headers but no data rows. No category or identity merge was approved without sufficient evidence.

The generated database, `data/nyc311_weather.db`, remains excluded from Git because it is a derived local artifact and is submitted separately.

## 4. Data Quality Investigation

The profiling notebook examines all six required data-quality families.

| Family | Main finding |
|---|---|
| Missing values | Request coordinates and several request timestamps have substantial missingness. No weather measurements are missing in this snapshot. |
| Invalid values | No impossible coordinate, negative precipitation/wind, out-of-range humidity/cloud/wind direction, or unsupported WMO weather code was found in the loaded snapshot. |
| Unusual values | Borough-specific IQR fences flagged 518 high-precipitation and 784 high-wind observations. These values were retained. |
| Cross-field and sequence issues | 1,070 closed timestamps and 82,407 resolution-update timestamps precede request creation. No due-before-created cases were found. |
| Text and categories | Fuzzy-similarity candidates were reviewed, but similar labels were not automatically merged. |
| Identity | No duplicate request keys, duplicate weather keys, or confirmed dimension identity conflicts were found. |

### 4.1 Important Missingness Findings

- Both latitude and longitude are missing in 82,051 requests. In the `UNSPECIFIED` borough group, 3,684 of 3,958 requests (93.08%) lack coordinates.
- The closed timestamp is missing in 179,314 requests.
- The due timestamp is missing in 3,938,171 requests (99.62%). All 15,007 populated due dates belong to DSNY / GRAFFITI requests.
- The resolution-update timestamp is missing in 69,788 requests.
- There are 797 creation timestamps without a uniquely resolvable UTC instant: 796 ambiguous local times and one nonexistent local time caused by daylight-saving transitions.

The observed relationships between missingness and request status, borough, agency, and complaint type support some inferred MAR interpretations. They do not establish the source's business rules. The causes that cannot be demonstrated are explicitly marked unknown in the detailed cleaning report.

### 4.2 Unusual Weather Values

Borough-specific positive-only IQR fences were used for precipitation, while borough-specific IQR fences were used for wind speed. The method uses the upper fence `Q3 + 1.5 × IQR`.

The resulting 518 precipitation and 784 wind-speed observations were flagged as `unusual_high`. They remain in the cleaned layer with their original values. An unusual value is not automatically an invalid measurement.

## 5. Cleaned Layer Design

The cleaned layer is implemented in `sql/clean_schema.sql`.

| Cleaned table | Source table | Row count |
|---|---|---:|
| `service_requests_clean` | `service_requests` | 3,953,178 |
| `weather_observations_clean` | `weather_observations` | 43,800 |

Both cleaned tables preserve the source grain, primary key, and row count. They are declared `STRICT` and use declared foreign keys to the relevant M2 tables.

For every value cleaned by the M3 process, the cleaned table stores the raw value, cleaned value, and a corresponding `_flag` column. Every flag column is `TEXT NOT NULL` and has a `CHECK` constraint listing its allowed values.

Missing or untrusted cleaned values remain `NULL`. No means, medians, forward fills, interpolations, or other imputation methods are used.

The service-request cleaned table is a focused analytical projection. It retains the request key, entity relationships, creation-date information, timestamp groups, coordinate groups, and retrieval provenance. Descriptive source attributes remain unchanged in M2 and can be retrieved by joining on `unique_key`.

The weather cleaned table retains its composite key and all seven weather variables with raw, cleaned, and flag fields.

## 6. Cleaning Workflow and Implementation

Build and validate the database from the repository root:

```bash
python src/load.py
python src/clean.py
python src/validate.py
```

The cleaning script reads the M2 SQLite tables and writes to separate M3 tables. It does not call source APIs or modify M2 data. Database changes are executed in one transaction. SQL data values use placeholders, and service requests are processed in batches of 5,000 rows.

The cleaning rules are applied in this order:

1. Apply the timestamp-normalization status recorded by M2.
2. Compare normalized optional timestamps with creation time and flag impossible chronology.
3. Validate coordinate ranges.
4. Validate weather numeric ranges and WMO codes.
5. Apply borough-specific IQR anomaly flags to valid precipitation and wind-speed values.

The script prints row counts, flag counts, mapping counts, unmatched mapping counts, and foreign-key status. It exits non-zero on failure. The production cleaning script was run twice; both runs committed successfully and produced identical row counts and flag totals.

## 7. Validation and Test Results

The final live validator reported five STOP checks as PASS and three WARN checks.

| Level | Check | Result |
|---|---|---|
| STOP | Service-request row-count equality | PASS — 3,953,178 = 3,953,178 |
| STOP | Weather-observation row-count equality | PASS — 43,800 = 43,800 |
| STOP | Foreign-key integrity | PASS — no violations |
| STOP | Service-request cleaned-value rules | PASS |
| STOP | Weather cleaned-value rules | PASS |
| WARN | Coordinate missingness by borough | 93.08% missing in UNSPECIFIED |
| WARN | Coverage freshness | 29 days for named boroughs; 30 days for UNSPECIFIED |
| WARN | Project-specific limitations | 3,958 unspecified-borough requests, 797 unresolved creation UTC timestamps, and 99.62% missing due dates |

The three WARN results describe source coverage and measurement limitations, not failures of the cleaning pipeline.

### 7.1 STOP Failure Demonstrations

Each STOP condition was deliberately made to fail in a separate temporary SQLite database. The validator was invoked as a separate process for each case.

| STOP scenario | Result |
|---|---|
| Service-request row-count mismatch | STOP; exit code 1 |
| Weather-observation row-count mismatch | STOP; exit code 1 |
| Foreign-key integrity failure | STOP; exit code 1 |
| Impossible service-request value | STOP; exit code 1 |
| Impossible weather value | STOP; exit code 1 |

All five tests returned exit code 1. Their temporary databases were removed after testing.

### 7.2 Atomicity Test

Atomicity was tested using a separate temporary database. The first cleaning run completed successfully. A SQLite trigger then injected an intentional failure during the next run. The process exited with code 1.

A before/after snapshot comparison confirmed that all table data and schema definitions were unchanged. The previous clean layer was preserved by transaction rollback. The production database was not used for failure injection. The test result is documented in `docs/evidence/m3_atomicity_test.txt`.

### 7.3 Source Immutability and Idempotence

All nine M2 tables retained identical row counts and SHA-256 content hashes. All four M3 tables also retained identical row counts and content hashes across the compared runs.

This verifies that the recorded cleaning run did not modify M2 source data and that rebuilding the M3 layer with the same inputs produced identical content.

Final evidence is stored in `docs/evidence/`:

- `m3_clean_run_1.txt` and `m3_clean_run_2.txt`: final production cleaning outputs.
- `m3_validate_output.txt`: final live validator output.
- `m3_self_test.txt`: function-level STOP self-tests.
- `m3_stop_failure_tests.txt`: five separate process exit-code tests.
- `m3_integrity_before.json` and `m3_integrity_compare.txt`: source immutability and M3 idempotence evidence.
- `m3_atomicity_test.txt`: injected-failure rollback test.

## 8. Mapping and Identity Decisions

The profiling investigation reviewed distinct category labels and fuzzy-similarity candidates. Similar spelling, punctuation, and pluralization were treated as proposals rather than proof of equivalence.

No category alias or entity identity decision had sufficient evidence for approval. Consequently, both mapping CSV files contain their required headers but no data rows. The loader reported zero loaded and zero unmatched mapping entries. No surrogate IDs were merged or rewritten.

Future mapping changes must be recorded in the corresponding CSV with `decided_by`, `decided_at`, and an evidence note.

## 9. Known Limitations and M4 Considerations

The latest request date is 10 October 2026 for the five named boroughs and 9 October 2026 for UNSPECIFIED, as checked on 8 November 2026. The requested recent coverage is therefore incomplete.

Requests without coordinates cannot support precise spatial analysis. Requests in the UNSPECIFIED borough group cannot be joined to a named borough weather point without an explicit analytical rule.

The 797 unresolved creation timestamps cannot be assigned a unique UTC instant from the available source information. Due-date analysis is limited by the 99.62% missing share.

Weather observations represent five model-grid locations, not direct station measurements throughout New York City. Borough-level weather comparisons should therefore be interpreted cautiously.

M4 must preserve these exclusions and limitations explicitly. Any imputation or analytical filtering must be performed visibly in M4 analysis code, not silently in the M3 cleaned layer.

## 10. M3 Completion Checklist

- [x] Profiling notebook created, executed, and saved with outputs.
- [x] All six data-quality families investigated.
- [x] Missingness mechanisms assessed, with uncertainty stated.
- [x] Unusual values identified using robust IQR fences and retained.
- [x] STRICT cleaned tables created with the same keys, grain, and row counts.
- [x] Raw, cleaned, and flag columns implemented for cleaned values.
- [x] Mapping CSV files created with decision metadata columns.
- [x] Cleaning code implemented with transaction, parameterized values, constants, and summary output.
- [x] Cleaning run twice with matching results.
- [x] Atomic rollback tested using a temporary database.
- [x] Five STOP checks deliberately failed and verified with exit code 1.
- [x] Live validator completed with five STOP PASS results and three documented WARN results.
- [x] M2 source hashes verified unchanged.
- [x] M3 content idempotence verified.
- [x] README and both M3 reports prepared.
- [ ] Final M3 commit created and pushed to GitHub.
- [ ] `m3` tag pushed to GitHub.
- [ ] Built database and required raw-data archive submitted through the course system.

## 11. Submission

The final M3 repository state must be committed and tagged `m3`. The tag must be pushed to GitHub.

The course submission should include:

- Repository URL.
- Built database file `data/nyc311_weather.db`.
- Raw-data ZIP if `data/raw/` is not included in the repository.
- Outputs of the two final `clean.py` runs.
- Output of the final live `validate.py` run.

The database and raw source files are intentionally excluded from Git and must be provided separately through the course submission system.
