# Project Validation Evidence — M1, M2, and M3

These files record the local ingestion, database, and cleaning validation runs
for the saved NYC 311 and Open-Meteo source snapshots.

- `load-run-1.txt` and `load-run-2.txt`: the two recorded full loader runs.
  Both ran against an already populated database and showed +0 net new rows;
  `cold-rebuild.txt` records the empty-database load.
- `load-run-real-idempotence.txt`: a subsequent full reload.
- `real-db-state-before.json`: row counts and SHA-256 content hashes recorded
  before that subsequent reload.
- `real-db-state-after.json`: the same measurements recorded after the reload.
- `checks.txt`: the normal synthetic schema, integrity, idempotence, and
  atomicity test run; the expected final line is `ALL CHECKS PASSED`.
- `atomicity-mutation-test.txt`: an intentional mutation-test run in which
  `rollback()` was temporarily replaced with `commit()`. The atomicity
  assertion failed as expected because the failed load changed table contents.
  This file is evidence of fault detection, not the normal passing test run.

The before and after JSON files were produced with `read_table_state()` from
`src/checks.py`. The recorded baseline predates the reload, and the after-state
was saved after the reload. The hashes include the stored row contents,
including `retrieved_at`, and use deterministic `rowid` order.

The verification script compares the saved states and then hashes the current
local database against the saved after-state. It does not rerun the loader.
Rebuilding with a different source snapshot or different recorded retrieval
metadata may legitimately produce different hashes.


## Cold rebuild

- `cold-rebuild.txt`: a full load into an empty temporary SQLite database. It recorded 3,953,178 service requests, 43,800 weather observations, zero quarantine candidates, a passing foreign-key check, and a successful commit. The verification script compared its table-content hashes with the saved full-database after-state. The temporary database was deleted after validation.


## M3 Cleaning and Quality Evidence

- `m3_clean_run_1.txt` and `m3_clean_run_2.txt`: final production clean runs.
- `m3_validate_output.txt`: final live validator output.
- `m3_self_test.txt`: function-level STOP self-tests.
- `m3_stop_failure_tests.txt`: five separate process tests; all exited with code 1.
- `m3_integrity_before.json` and `m3_integrity_compare.txt`: M2 source immutability and M3 idempotence evidence.
- `m3_atomicity_test.txt`: temporary-database injected-failure rollback test.

The production SQLite database and raw M1 files are excluded from Git. Submit the built database separately and include the raw-data ZIP if required by the course system.
