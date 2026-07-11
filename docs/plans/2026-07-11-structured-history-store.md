# Structured TickStone History Store Implementation Plan

> **For Hermes:** Implement task-by-task with strict RED-GREEN-REFACTOR and verify the installed Raspberry Pi runtime.

**Goal:** Preserve every BLE event as immutable JSONL while maintaining a queryable, migration-ready SQLite history store suitable for future statistics.

**Architecture:** The BLE listener remains the sole receiver and acknowledgement owner. A standard-library storage module appends unseen raw events, idempotently upserts validated events into SQLite, records TickStone day boundaries in Europe/Stockholm, and can rebuild the database from JSONL. Habit metadata is versioned separately so slot-name changes never rewrite history. A backup command uses SQLite's online backup API and copies the raw JSONL to uniquely named, non-overwriting files.

**Tech Stack:** Python 3.13 standard library (`sqlite3`, `zoneinfo`, `json`, `pathlib`), Bleak, `unittest`, systemd.

---

### Task 1: Specify storage behavior with failing tests

**Files:**
- Create: `tests/tickstone_store_test.py`

Cover schema creation, event validation, idempotent ingest, immutable raw append, JSONL rebuild, 05:00 Europe/Stockholm day assignment (including DST-safe dates), deleted events, habit configuration versioning, integrity checks, and non-overwriting backups.

Run: `python3 tests/tickstone_store_test.py -v`
Expected: RED because `tools.tickstone_store` does not exist.

### Task 2: Implement the SQLite/JSONL store

**Files:**
- Create: `tools/tickstone_store.py`

Implement schema migrations, validated ingest, raw append, rebuild/import, habit snapshot versioning, integrity reporting, and online backups. Use transactions, WAL, foreign keys, checks, unique event IDs, UTC ingest timestamps, and preserve original epoch values.

Run focused tests, then refactor while green.

### Task 3: Integrate the BLE receiver safely

**Files:**
- Modify: `tools/tickstone_ble_sync.py`
- Modify: `tests/tickstone_store_test.py`

Add `--database`; persist raw JSONL and SQLite before acknowledging a device record. Replayed IDs must repair a missing database row without duplicating JSONL. Keep the existing JSONL-only mode compatible.

Run focused tests and a timeout-based listener smoke test.

### Task 4: Add operations artifacts and documentation

**Files:**
- Create: `deploy/tickstone-sync.service`
- Create: `deploy/tickstone-backup.service`
- Create: `deploy/tickstone-backup.timer`
- Modify: `README.md`

Document paths, schema, restore/rebuild, integrity checks, habit metadata import, service installation, and backup behavior. Daily backups must use unique names and never truncate source data.

### Task 5: Verify, review, deliver, and install

Run:
- `python3 tests/tickstone_store_test.py -v`
- `tools/run_tests.sh`
- `python3 -m compileall tools`
- temporary-data CLI ingest/rebuild/integrity/backup smoke
- `git diff --check`

Review the complete diff. Commit and push the feature branch, merge with privacy-safe Opifex noreply metadata after verification, then fast-forward the Pi checkout. Install repo-owned units, migrate the existing JSONL into SQLite, verify row counts/content/integrity, restart the live listener, exercise restart recovery, run a real BLE append/readback if available, and verify the backup timer plus a manual backup.
