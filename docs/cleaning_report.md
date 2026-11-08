# Cleaning Report — NYC 311 Service Requests and Open-Meteo Weather

## 1. Summary

This report documents the M3 data-quality investigation and cleaning process for the NYC 311 Service Requests and Open-Meteo Weather project. The cleaned layer was built from the existing M2 SQLite tables without modifying the source tables or deleting records. It contains 3,953,178 service requests and 43,800 hourly weather observations, with the same keys, grain, and row counts as their source tables. The main issues are missing request coordinates and dates, timestamps that cannot be safely ordered or converted to UTC, and unusual but plausible precipitation and wind-speed observations. The cleaning process preserves raw values, uses explicit flags, and does not impute missing or untrusted values. All five live STOP checks pass; three WARN checks document coverage and source limitations that remain relevant to M4.

No M2 schema or source-data correction was required during this M3 cleaning run. The M3 changes are implemented in `sql/clean_schema.sql`, `src/clean.py`, `src/clean_config.py`, and `src/validate.py`.

## 2. Profile highlights

The profiling notebook is `notebooks/m3_profile.ipynb`. It is committed with its executed outputs and runs from top to bottom after rebuilding the M2 database.

| Profile item | Result | Interpretation |
|---|---:|---|
| Service requests | 3,953,178 | One row per `unique_key` |
| Weather observations | 43,800 | 8,760 hourly observations for each of five locations |
| Borough coverage | 364 days for the five named boroughs | 12 October 2025 to 10 October 2026 (partial day, ending at about 03:03 local time) |
| UNSPECIFIED borough coverage | 363 days | Ends on 9 October 2026 |
| Missing latitude and longitude | 82,051 each | Both coordinates are missing together; no one-sided missing pair was found |
| Missing closed timestamp | 179,314 | Mainly IN PROGRESS and OPEN; 15 CLOSED requests also lack a closed date |
| Missing due timestamp | 3,938,171 | Only 15,007 rows have a due date |
| Missing resolution-update timestamp | 69,788 | Concentrated in active statuses |
| Unresolvable creation UTC timestamp | 797 | 796 ambiguous and one nonexistent local time |
| Closed timestamp before creation | 1,070 | Chronological inconsistency |
| Resolution update before creation | 82,407 | Chronological inconsistency |
| Due timestamp before creation | 0 | No such case found |
| Weather measurements missing | 0 | No missing hourly weather measurements in this snapshot |
| Weather foreign-key violations | 0 | Referential-integrity check passed |

### Weather distributions and sequence checks

The hourly weather values were profiled separately for each borough location. Observed ranges were temperature -18.0 to 40.2 °C, relative humidity 13–100%, precipitation 0–17.1 mm, wind speed 0–46 km/h, wind direction 1–360 degrees, and cloud cover 0–100%. All observed WMO weather codes were in the accepted code domain.

A global IQR fence for precipitation would be unhelpful because zero-rain hours dominate the distribution. Therefore, precipitation fences were calculated from positive-precipitation hours only. Wind-speed fences were calculated separately for each borough. IQR anomaly flags were applied to precipitation and wind speed only. Temperature has no automatic domain/range rule in `clean.py`; its observed range (-18.0 to 40.2 °C) was inspected manually in the profiling notebook. Humidity, direction, and cloud-cover values had no domain violations requiring invalid-value flags. No IQR anomaly thresholds were applied to temperature or humidity.

The longest identical runs were 4–6 hours for temperature, 3–4 hours for wind speed, and 7–11 hours for humidity. Long runs of zero precipitation lasted 243–273 hours. These dry periods are plausible weather conditions and are not evidence of a stuck sensor. The inputs are gridded model/reanalysis estimates, not direct station telemetry.

### Scope of the cleaned layer

The cleaned service-request table is a focused analytical projection rather than a full duplicate of every M2 source attribute. It retains the request key, five entity foreign keys, creation-date fields used for temporal interpretation, all four timestamp raw/clean/flag groups, latitude and longitude raw/clean/flag groups, and retrieval provenance. Descriptive fields such as incident address, descriptor, street details, resolution description, and other agency-specific attributes remain unchanged in `service_requests`; they are not independently cleaned or copied into this M3 table. An M4 query that needs those attributes should join the cleaned request row to its M2 source row using `unique_key`. The weather cleaned table retains the complete hourly observation key, location relationship, all seven requested weather variables as raw/clean/flag triplets, and retrieval time. This design concentrates cleaning decisions on fields that affect the intended time-and-weather linkage without implying that every source attribute has been quality-corrected.

No rows were deduplicated in M3. Key uniqueness and entity reference resolution were established during M2 and then checked again through row-count and foreign-key validation. The mapping files intentionally contain headers only: no candidate alias met the evidence standard for a human-approved merge. This avoids treating visual similarity as proof of equivalence.

## 3. Issues register

| ID | Family | Table.column | What | Where / when / how many | Evidence | Cause | Decision / flag | Investigated by |
|---|---|---|---|---|---|---|---|---|
| I-01 | Missing | `service_requests.latitude`, `longitude` | Both coordinates missing | 82,051 requests; 3,684 of 3,958 UNSPECIFIED-borough requests (93.08%) lack coordinates; the remaining 78,367 missing pairs belong to named boroughs | Both fields are NULL together; no single-coordinate-only cases | Missingness varies by borough, but the source cause is unknown | Keep NULL; `missing_not_reported` | Şeyma Nur Demirkoparan |
| I-02 | Missing | `service_requests.closed_at_utc` | Closed date not supplied | 179,314 requests: 113,409 IN PROGRESS; 56,363 OPEN; 5,064 PENDING; 3,159 ASSIGNED; 1,275 STARTED; 29 UNSPECIFIED; and 15 CLOSED | Missingness varies substantially by request status; 15 rows marked CLOSED also lack a closed date | Inferred relationship with workflow/status; not confirmed | Keep NULL; `missing_not_reported` | Şeyma Nur Demirkoparan |
| I-03 | Missing | `service_requests.due_at_utc` | Due date absent | 3,938,171 requests (99.62%) | All 15,007 populated due dates belong to DSNY / GRAFFITI requests | Inferred MAR by agency and complaint type; not confirmed | Do not infer a due date; `missing_not_reported` | Şeyma Nur Demirkoparan |
| I-04 | Missing | `service_requests.resolution_action_updated_at_utc` | Resolution update absent | 69,788 requests; 64,499 IN PROGRESS, 5,266 OPEN, 11 PENDING, 12 UNSPECIFIED | Missingness is concentrated in active statuses | Inferred MAR by workflow/status; not confirmed | Keep NULL; `missing_not_reported` | Şeyma Nur Demirkoparan |
| I-05 | Invalid / time | `service_requests.created_at_utc` | Local timestamp cannot be uniquely converted to UTC | 796 ambiguous and 1 nonexistent local timestamps | Source timestamps have no explicit UTC offset; local DST rules create a repeated hour and a nonexistent hour | DST ambiguity is confirmed by timezone rules; intended UTC instant is unknown | Keep UTC NULL; `ambiguous_local_time` / `nonexistent_local_time` | Şeyma Nur Demirkoparan |
| I-06 | Cross-field | `closed_at_utc`, `resolution_action_updated_at_utc` | Event time precedes creation time | 1,070 closed timestamps; 82,407 resolution-update timestamps | Direct chronological comparison after UTC normalization; zero due-before-created cases | Unknown; source correction, event semantics, or timestamp issues cannot be distinguished from these fields alone | Keep raw value; cleaned timestamp NULL; `invalid_before_created` | Şeyma Nur Demirkoparan |
| I-07 | Unusual | `weather_observations.precipitation_mm` | High positive precipitation | 518 hourly observations across borough locations | Borough-specific positive-only IQR fences; values inspected and retained | Unusual but plausible weather; exact event cause not independently confirmed | Keep value; `unusual_high` | Şeyma Nur Demirkoparan |
| I-08 | Unusual | `weather_observations.wind_speed_10m_kmh` | High hourly wind speed | 784 observations across borough locations | Borough-specific IQR fences; maximum observed speed 46 km/h | Unusual but plausible weather; exact event cause not independently confirmed | Keep value; `unusual_high` | Şeyma Nur Demirkoparan |
| I-09 | Coverage | `service_requests.created_local_date`, `retrieved_at` | Latest request coverage is stale relative to the validation date | Latest request date is 10 October 2026 in the five named boroughs and 9 October in UNSPECIFIED; checked on 8 November 2026. The latest request timestamp precedes the latest service-request retrieval timestamp by approximately 33 hours 9 minutes. The snapshot is approximately 28 days old as of 8 November. | Per-borough maximum dates, monthly coverage profile, and retrieval timestamps | The stored service-request snapshot was retrieved on 11 October 2026 and had not been refreshed by the 8 November validation date; the cause of the approximately 33-hour source-to-retrieval lag is unknown | Retain records; report freshness WARN and distinguish record age from retrieval age | Şeyma Nur Demirkoparan |
| I-10 | Text / category | `complaint_types.complaint_type` | Similar labels may not mean the same thing | 194 distinct complaint types; several fuzzy-similarity candidates | Examples include BUILDING MARSHAL'S OFFICE / BUILDING MARSHALS OFFICE (similarity about 0.98) and HAZARDOUS MATERIAL / HAZARDOUS MATERIALS (about 0.973); TAXI COMPLAINT / TAXI COMPLIMENT is a warning against automatic merging | Alias status unknown without authoritative evidence | Keep labels separate; no category mapping approved | Şeyma Nur Demirkoparan |
| I-11 | Identity | Entity dimensions and request keys | Possible split or duplicated identities | 3,953,178 distinct request keys; dimension natural-key duplicate checks returned zero | Primary/natural-key and dimension duplicate checks; temporal coverage review | No confirmed identity conflict found | No identity merge; identity mapping remains empty | Şeyma Nur Demirkoparan |

### Checked and not found

| Family | Check | Result |
|---|---|---|
| Missing | Weather values by location and variable | No missing weather measurements in 43,800 observations |
| Invalid | Latitude/longitude outside [-90, 90] / [-180, 180] | Zero |
| Invalid | Negative precipitation or wind speed; humidity/cloud outside 0–100%; wind direction outside 0–360° | Zero in the loaded M2 snapshot |
| Invalid | Weather codes outside the accepted WMO code domain | Zero |
| Invalid | Due timestamp earlier than request creation | Zero |
| Cross-field | One coordinate missing while the other is present | Zero |
| Cross-field | Suspicious constant-value weather runs | No stuck-sensor evidence; long zero-rain runs are plausible dry periods |
| Text | Duplicate dimension natural keys | Zero |
| Identity | Duplicate request `unique_key` values | Zero; all 3,953,178 keys are distinct |
| Identity | Weather duplicate `(weather_location_id, observed_at_utc)` keys | Zero |

## 4. Missing values and mechanisms

Missingness was not treated as one universal process. MCAR means missingness is unrelated to observed or unobserved data; MAR means it is associated with observed variables; MNAR means it depends on the missing value itself or an unobserved process. The available snapshot does not establish MCAR or MNAR for these request fields. Where missingness follows observed request status, borough, agency, or complaint type, MAR is a reasonable inference, not a confirmed explanation.

Coordinates are missing together in 82,051 requests. Although 93.08% of requests in the UNSPECIFIED borough group lack coordinates, this group accounts for only 3,684 of all 82,051 missing coordinate pairs (about 4.5%). The remaining 78,367 missing pairs belong to requests assigned to the five named boroughs. Missingness therefore varies substantially by borough, but the total number of missing pairs is not concentrated in the UNSPECIFIED group. The available data do not establish the source cause, so a blanket MCAR assumption would be unsafe. Requests without coordinates remain in the cleaned layer, but precise spatial analyses should exclude or separately identify them.

Closed dates are missing mainly for IN PROGRESS and OPEN requests, which is consistent with a workflow in which closure has not yet occurred. The full status breakdown is:

| Status | Missing closed timestamps |
|---|---:|
| IN PROGRESS | 113,409 |
| OPEN | 56,363 |
| PENDING | 5,064 |
| ASSIGNED | 3,159 |
| STARTED | 1,275 |
| UNSPECIFIED | 29 |
| CLOSED | 15 |
| **Total** | **179,314** |

The 15 CLOSED requests without a closed date show that status does not explain every missing value. Due dates are present only for DSNY GRAFFITI requests, suggesting an agency/category-specific workflow. Resolution-update dates are also concentrated in active statuses. These patterns support an inferred MAR interpretation, but the data do not prove the business rules. M4 must not treat missing dates as zero, as a date of request creation, or as evidence of a particular duration.

The 797 creation timestamps are different: the source local timestamp exists, but 796 fall in an ambiguous repeated DST hour and one in a nonexistent local hour. Without a source offset or other authoritative disambiguation, an exact UTC instant cannot be reconstructed. The source string remains available, while the cleaned UTC field is NULL. Weather values have no missing measurements in this snapshot.

**Chronology limitation:** Chronology could not be evaluated for 797 service requests because `created_at_utc` is NULL. Among these records, 519 have at least one optional timestamp: 514 have `closed_at_utc`, 1 has `due_at_utc`, and 518 have `resolution_action_updated_at_utc`. These counts overlap and are not additive. The remaining 278 records have none of these optional timestamps. Since the creation timestamp is unavailable, chronological relationships cannot be verified for these records. The validator skips this comparison when the creation timestamp is NULL.


## 5. Flags and cleaning rules

Rules are applied in this order: (1) use the M2 timestamp-normalization status; (2) compare normalized optional timestamps with creation time and flag impossible chronology; (3) validate coordinate ranges; (4) validate weather numeric ranges and WMO codes; (5) apply borough-specific IQR anomaly flags to valid precipitation and wind-speed values. The first applicable rule determines the flag. No values are imputed.

| Field | Flag | Meaning / rule | Cleaned value | Count |
|---|---|---|---|---:|
| Creation timestamp | `ok` | M2 normalized timestamp | Original UTC value | 3,952,381 |
| Creation timestamp | `ambiguous_local_time` | Repeated DST local hour | NULL | 796 |
| Creation timestamp | `nonexistent_local_time` | Nonexistent DST local hour | NULL | 1 |
| Closed timestamp | `ok` | Normalized and not before creation | Original UTC value | 3,772,025 |
| Closed timestamp | `missing_not_reported` | No source date | NULL | 179,314 |
| Closed timestamp | `ambiguous_local_time` / `nonexistent_local_time` | DST conversion cannot be resolved | NULL | 757 / 12 |
| Closed timestamp | `invalid_before_created` | Earlier than creation | NULL | 1,070 |
| Due timestamp | `ok` | Normalized and not before creation | Original UTC value | 15,007 |
| Due timestamp | `missing_not_reported` | No source date | NULL | 3,938,171 |
| Resolution-update timestamp | `ok` | Normalized and not before creation | Original UTC value | 3,800,209 |
| Resolution-update timestamp | `missing_not_reported` | No source date | NULL | 69,788 |
| Resolution-update timestamp | `ambiguous_local_time` / `nonexistent_local_time` | DST conversion cannot be resolved | NULL | 754 / 20 |
| Resolution-update timestamp | `invalid_before_created` | Earlier than creation | NULL | 82,407 |
| Latitude / longitude | `ok` | Within geographic range | Original value | 3,871,127 each |
| Latitude / longitude | `missing_not_reported` | Source coordinate absent | NULL | 82,051 each |
| Precipitation | `ok` | At or below borough fence | Original value | 43,282 |
| Precipitation | `unusual_high` | Above positive-only borough IQR fence | Original value, retained | 518 |
| Wind speed | `ok` | At or below borough fence | Original value | 43,016 |
| Wind speed | `unusual_high` | Above borough IQR fence | Original value, retained | 784 |
| All seven weather fields | `missing_not_reported` | Source measurement is NULL | NULL | 0 in this snapshot |
| Other weather fields | `ok` | Automatic domain checks passed for applicable fields; temperature has no automatic range rule and was manually inspected; no unusual candidate found | Original value | 43,800 per field |

### Allowed flags with zero counts

These flags are permitted by the schema but did not occur in this snapshot. Temperature and humidity unusual flags are reserved categories; this implementation does not apply IQR anomaly thresholds to those two variables.

| Field | Allowed flag | Count |
|---|---|---:|
| Due timestamp | `ambiguous_local_time`, `nonexistent_local_time`, `invalid_before_created` | 0 each |
| Latitude / longitude | `invalid_range` | 0 each |
| Temperature | `unusual_low`, `unusual_high` | 0 each |
| Relative humidity | `unusual_low`, `unusual_high`, `invalid_range` | 0 each |
| Precipitation | `invalid_negative` | 0 |
| Weather code | `invalid_code` | 0 |
| Wind speed | `invalid_negative` | 0 |
| Wind direction | `invalid_range` | 0 |
| Cloud cover | `invalid_range` | 0 |

### Constants

The exact floating-point fence values are stored in `src/clean_config.py`; the rounded values below are for readability.

| Constant | Values / rule | Reason |
|---|---|---|
| `PRECIPITATION_UPPER_FENCE_MM` | Bronx 3.10; Brooklyn 2.85; Manhattan 2.95; Queens 3.10; Staten Island 3.10 mm | Q3 + 1.5 × IQR from positive precipitation hours only; including the many zero-rain hours would collapse the distribution. |
| `WIND_SPEED_UPPER_FENCE_KMH` | Bronx 25.80; Brooklyn 24.70; Manhattan 24.10; Queens 23.85; Staten Island 29.65 km/h | Borough-specific Q3 + 1.5 × IQR because local distributions differ. |
| `BATCH_SIZE` | 5,000 rows | Bounds memory use while inserting millions of requests; changing it affects batch size, not cleaning decisions. |
| `MISSING_COORDINATE_WARN_THRESHOLD` | 10% | A monitoring threshold to surface borough-level coordinate gaps; it does not change or remove data. |
| `MAX_SOURCE_AGE_DAYS` | 7 days | A freshness alert threshold for recent request coverage. The current validator evaluates the age of the latest request date, not the age of the retrieval snapshot. |
| `WMO_CODES` | 28 accepted WMO present-weather codes | Rejects unsupported categorical weather codes while retaining their raw values. |
| `WEATHER_RANGES` | Humidity 0–100%; precipitation and wind non-negative; direction 0–360°; cloud cover 0–100% | Physical/domain limits; invalid values become NULL and receive flags rather than being clipped. |
| Coordinate bounds | Latitude −90 to 90; longitude −180 to 180 | Standard geographic limits; invalid coordinates become NULL and receive `invalid_range`. |

Unusual precipitation and wind observations are retained because an IQR outlier is not proof of an impossible measurement. If a threshold changes, only the corresponding anomaly flags should change; the raw and cleaned measurement values remain the same.



**Chronology interpretation of `ok` flags:** When `created_at_utc` is NULL (797 requests), an `ok` flag on an optional event timestamp indicates successful timestamp normalization only. It does not confirm that the event occurred after creation, because that chronological comparison cannot be performed.
## 6. Mapping and identity decisions

The M2 loader already trims optional text and standardizes the principal category labels to uppercase. The M3 profiling step reviewed distinct labels and generated fuzzy-similarity candidates. Fuzzy similarity was treated as a proposal only: punctuation, pluralization, and similar spelling do not prove semantic identity. In particular, TAXI COMPLAINT and TAXI COMPLIMENT were not merged.

No category alias or entity identity decision had sufficient evidence for an approved mapping. Therefore, `data/mappings/category_alias_map.csv` and `data/mappings/identity_alias_map.csv` contain their required headers but no data rows. The mapping CSV files include the decision metadata columns `decided_by`, `decided_at`, and `note`; the loader reports zero loaded and zero unmatched mapping rows. The empty files are intentional and preserve a reviewable place for future evidence-backed decisions. No surrogate IDs were merged or rewritten. Mapping tables are loaded and counted in M3 but are not applied to cleaned tables; approved aliases are intended to be applied through joins in M4. Unmatched mapping entries are reported but do not stop the cleaning run.

## 7. Counts and validation

The final clean run produced 3,953,178 cleaned requests and 43,800 cleaned weather observations. It loaded zero category mappings and zero identity mappings. The final flag totals are shown in Section 5.

The live validation run reported five STOP checks as PASS: request row-count equality, weather row-count equality, foreign-key integrity, service-request timestamp/coordinate rules, and weather-domain/raw-to-clean/IQR consistency. It reported three WARN checks:

1. **Coordinate missingness:** 93.08% of UNSPECIFIED-borough requests lack both coordinates (3,684 of 3,958). However, this group accounts for only about 4.5% of all missing coordinate pairs; the remaining 78,367 missing pairs belong to the five named boroughs. This is a source/measurement coverage limitation, not a cleaning failure.
2. **Freshness:** the latest request date is 10 October 2026 for the five named boroughs and 9 October 2026 for UNSPECIFIED. On 8 November 2026 these dates are 29 and 30 days old. The validator's seven-day freshness threshold compares the latest request date with the validation date, so this WARN represents the age of the latest event records. It does not measure the age of the retrieval snapshot or the delay between the latest event and extraction.
3. **Project-specific limitations:** 3,958 requests have UNSPECIFIED borough, 797 creation timestamps lack a resolvable UTC instant, and 99.62% of requests have no due date. These limit borough-hour weather joins and due-date analysis; they do not indicate that the cleaning pipeline changed source values.

The retrieval timestamps provide two additional freshness measurements. The latest request timestamp is `2026-10-10T07:03:53Z`, while the latest service-request retrieval timestamp is `2026-10-11T16:13:02.789888Z`. The difference is approximately 33 hours and 9 minutes, representing the source lag at extraction. The latest service-request retrieval timestamp is approximately 28 days old on 8 November 2026, representing the age of the stored snapshot. These measurements describe different aspects of freshness and should not be treated as interchangeable with the latest-record age reported by the validator.

`python3 src/validate.py --self-test` uses isolated in-memory fixtures and confirms that all five STOP check functions return STOP when their fixtures are intentionally invalid. Separate process-based failure demonstrations using temporary databases are listed individually below.

Atomicity was also tested using a separate temporary database. The first cleaning run completed successfully. A SQLite trigger then injected an intentional failure during the next cleaning run. The process exited with code 1, and a before/after snapshot comparison confirmed that all table data and schema definitions were unchanged. The previously committed clean layer was therefore preserved by rollback. The test database was removed, and the production database was not used for failure injection. The saved evidence is a narrative summary; the original raw terminal output and exact before/after hash values were not retained.

The five STOP failure demonstrations were also run as separate processes against temporary SQLite databases:

1. Service-request row-count mismatch: STOP, exit code 1.
2. Weather-observation row-count mismatch: STOP, exit code 1.
3. Foreign-key violation: STOP, exit code 1.
4. Impossible service-request value: STOP, exit code 1.
5. Impossible weather value: STOP, exit code 1.

The corresponding outputs are saved in `docs/evidence/m3_stop_failure_tests.txt`. The atomic rollback test is documented in `docs/evidence/m3_atomicity_test.txt`.

The hash evidence in `docs/evidence/m3_integrity_before.json` and the output of `src/m3_integrity.py compare` showed that all nine M2 tables retained identical row counts and SHA-256 content hashes. All four M3 SQLite tables—`service_requests_clean`, `weather_observations_clean`, `category_alias_map`, and `identity_alias_map`—also had identical row counts and content hashes across the compared runs. The two mapping CSV input files remained header-only, so the two mapping tables contained zero rows. This confirms source immutability and content-level idempotence for the recorded run. The schema's STRICT declarations, foreign keys, and flag constraints were separately inspected and tested.

## 8. What we cannot say

The snapshot cannot establish why every missing request field was omitted. Status, borough, agency, and complaint type explain some patterns, but they do not prove the source's business rules. The 1,070 closed and 82,407 resolution-update timestamps earlier than creation have no confirmed explanation; they are excluded from trusted cleaned timestamp fields but retained in raw columns.

The weather data represent five grid points, not direct measurements at every neighbourhood or street. Similar temperature patterns between borough points mean that fine-grained borough differences should be interpreted cautiously. Observational association between weather and complaint volume cannot establish causation.

Recent request coverage is incomplete relative to the requested extraction window, and 797 creation timestamps cannot be assigned a unique UTC instant. UNSPECIFIED borough requests cannot be joined to a named borough weather point without an explicit analytical rule. Due-date coverage is too sparse for broad citywide due-date or lateness conclusions. M4 should preserve these exclusions and limitations explicitly rather than silently filling gaps.

The raw and cleaned layers remain separate. Future changes to mappings or thresholds should be reviewed, recorded in the CSV/configuration files, rerun through `clean.py`, and validated before analysis.
