#!/usr/bin/env python3
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.tickstone_store import (  # noqa: E402
    backup_store,
    import_jsonl,
    ingest_event,
    integrity_report,
    open_store,
    record_habits,
    tickstone_day,
)

sys.path.insert(0, str(ROOT / "tools"))
import importlib.util
if importlib.util.find_spec("bleak") is None:
    import types
    bleak_module = types.ModuleType("bleak")
    setattr(bleak_module, "BleakClient", object)
    setattr(bleak_module, "BleakScanner", object)
    bleak_exc_module = types.ModuleType("bleak.exc")
    setattr(bleak_exc_module, "BleakError", OSError)
    sys.modules["bleak"] = bleak_module
    sys.modules["bleak.exc"] = bleak_exc_module
from tickstone_ble_sync import persist_event  # noqa: E402


class TickStoneStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.raw = self.root / "logs.jsonl"
        self.database = self.root / "tickstone.sqlite3"
        self.event = {
            "id": 12,
            "habit_id": 0,
            "type": "count",
            "started_at": 1783806918,
            "ended_at": 1783806918,
            "duration_seconds": 0,
            "count": 1,
            "deleted": False,
        }

    def tearDown(self):
        self.temp.cleanup()

    def rows(self, query, parameters=()):
        with sqlite3.connect(self.database) as connection:
            return connection.execute(query, parameters).fetchall()

    def test_ingest_creates_queryable_schema_and_preserves_raw_event(self):
        result = ingest_event(self.raw, self.database, self.event)

        self.assertTrue(result.raw_appended)
        self.assertTrue(result.database_inserted)
        self.assertEqual(json.loads(self.raw.read_text()), self.event)
        row = self.rows(
            "SELECT id, habit_id, type, started_at, ended_at, duration_seconds, "
            "count, deleted, tickstone_day, raw_json FROM events"
        )[0]
        self.assertEqual(row[:9], (12, 0, "count", 1783806918, 1783806918, 0, 1, 0, "2026-07-11"))
        self.assertEqual(json.loads(row[9]), self.event)
        self.assertEqual(self.rows("SELECT slot_id, active FROM habits"), [(0, 1)])
        self.assertEqual(self.rows("PRAGMA journal_mode")[0][0].lower(), "wal")
        self.assertEqual(self.rows("SELECT value FROM metadata WHERE key='schema_version'"), [("1",)])

    def test_replayed_event_is_idempotent_and_repairs_database(self):
        ingest_event(self.raw, self.database, self.event)
        self.database.unlink()

        result = ingest_event(self.raw, self.database, self.event)

        self.assertFalse(result.raw_appended)
        self.assertTrue(result.database_inserted)
        self.assertEqual(len(self.raw.read_text().splitlines()), 1)
        self.assertEqual(self.rows("SELECT count(*) FROM events"), [(1,)])

    def test_conflicting_payload_for_existing_id_is_rejected(self):
        ingest_event(self.raw, self.database, self.event)
        changed = dict(self.event, count=2)

        with self.assertRaisesRegex(ValueError, "conflicting payload"):
            ingest_event(self.raw, self.database, changed)

        self.assertEqual(len(self.raw.read_text().splitlines()), 1)
        self.assertEqual(self.rows("SELECT count FROM events WHERE id=12"), [(1,)])

    def test_conflicting_database_payload_does_not_append_missing_raw_event(self):
        ingest_event(self.raw, self.database, self.event)
        self.raw.unlink()

        with self.assertRaisesRegex(ValueError, "conflicting payload"):
            ingest_event(self.raw, self.database, dict(self.event, count=2))

        self.assertFalse(self.raw.exists())

    def test_conflicting_raw_payload_does_not_create_database_row(self):
        changed = dict(self.event, count=2)
        self.raw.write_text(json.dumps(changed) + "\n")

        with self.assertRaisesRegex(ValueError, "conflicting payload"):
            ingest_event(self.raw, self.database, self.event)

        with open_store(self.database) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM events").fetchone()[0], 0)

    def test_validation_rejects_malformed_events_without_writing(self):
        cases = [
            dict(self.event, id=True),
            dict(self.event, type="other"),
            dict(self.event, habit_id=10),
            dict(self.event, duration_seconds=-1),
            {key: value for key, value in self.event.items() if key != "count"},
        ]
        for event in cases:
            with self.subTest(event=event):
                with self.assertRaises(ValueError):
                    ingest_event(self.raw, self.database, event)
        self.assertFalse(self.raw.exists())

    def test_tickstone_day_uses_stockholm_five_am_boundary(self):
        self.assertEqual(tickstone_day(1711853999), date(2024, 3, 30))  # 2024-03-31 04:59 CEST
        self.assertEqual(tickstone_day(1711854000), date(2024, 3, 31))  # 2024-03-31 05:00 CEST
        self.assertEqual(tickstone_day(1730001599), date(2024, 10, 26))  # 2024-10-27 04:59 CET
        self.assertEqual(tickstone_day(1730001600), date(2024, 10, 27))  # 2024-10-27 05:00 CET

    def test_import_jsonl_skips_blank_lines_and_is_repeatable(self):
        second = dict(self.event, id=13, habit_id=2, type="time", started_at=1783806929,
                      ended_at=1783806933, duration_seconds=3, count=0)
        self.raw.write_text(json.dumps(self.event) + "\n\n" + json.dumps(second) + "\n")

        first_result = import_jsonl(self.raw, self.database)
        second_result = import_jsonl(self.raw, self.database)

        self.assertEqual((first_result.read, first_result.inserted), (2, 2))
        self.assertEqual((second_result.read, second_result.inserted), (2, 0))
        self.assertEqual(self.rows("SELECT id FROM events ORDER BY id"), [(12,), (13,)])

    def test_habit_snapshots_are_versioned_without_relabeling_history(self):
        ingest_event(self.raw, self.database, self.event)
        first = [{"id": 0, "code": "MED", "name": "MEDITATION", "mode": "count", "minutes": 1}]
        second = [{"id": 0, "code": "WTR", "name": "WATER", "mode": "count", "minutes": 1}]

        first_snapshot = record_habits(self.database, first, recorded_at="2026-07-11T20:00:00Z")
        same_snapshot = record_habits(self.database, first, recorded_at="2026-07-11T20:01:00Z")
        second_snapshot = record_habits(self.database, second, recorded_at="2026-07-12T20:00:00Z")

        self.assertEqual(first_snapshot, same_snapshot)
        self.assertNotEqual(first_snapshot, second_snapshot)
        self.assertEqual(self.rows("SELECT count(*) FROM habit_snapshots"), [(2,)])
        self.assertEqual(
            self.rows("SELECT name FROM habit_snapshot_entries WHERE slot_id=0 ORDER BY snapshot_id"),
            [("MEDITATION",), ("WATER",)],
        )

    def test_integrity_reports_invalid_raw_lines_and_database_health(self):
        ingest_event(self.raw, self.database, self.event)
        with self.raw.open("a") as output:
            output.write("not-json\n")

        report = integrity_report(self.raw, self.database)

        self.assertEqual(report.database_integrity, "ok")
        self.assertEqual(report.database_events, 1)
        self.assertEqual(report.raw_valid_events, 1)
        self.assertEqual(report.raw_invalid_lines, (2,))
        self.assertEqual(report.missing_from_database, ())

    def test_backup_uses_unique_files_and_keeps_sources_unchanged(self):
        ingest_event(self.raw, self.database, self.event)
        backup_dir = self.root / "backups"
        original_raw = self.raw.read_bytes()
        original_rows = self.rows("SELECT count(*) FROM events")

        first = backup_store(self.raw, self.database, backup_dir, timestamp="20260711T220000Z")
        second = backup_store(self.raw, self.database, backup_dir, timestamp="20260711T220000Z")

        self.assertNotEqual(first.database, second.database)
        self.assertNotEqual(first.raw_jsonl, second.raw_jsonl)
        self.assertEqual(self.raw.read_bytes(), original_raw)
        self.assertEqual(self.rows("SELECT count(*) FROM events"), original_rows)
        with sqlite3.connect(first.database) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("SELECT count(*) FROM events").fetchone()[0], 1)

    def test_empty_store_can_be_checked_and_backed_up_before_first_event(self):
        with open_store(self.database):
            pass

        report = integrity_report(self.raw, self.database)
        backup = backup_store(self.raw, self.database, self.root / "empty-backups",
                              timestamp="20260711T230000Z")

        self.assertEqual(report.raw_valid_events, 0)
        self.assertEqual(report.database_events, 0)
        self.assertEqual(backup.raw_jsonl.read_text(), "")

    def test_ble_persistence_supports_database_and_legacy_jsonl_only_mode(self):
        persisted = persist_event(self.raw, self.event, self.database)
        legacy_raw = self.root / "legacy.jsonl"
        legacy = persist_event(legacy_raw, self.event, None)

        self.assertTrue(persisted.raw_appended)
        self.assertEqual(self.rows("SELECT id FROM events"), [(12,)])
        self.assertTrue(legacy.raw_appended)
        self.assertEqual(json.loads(legacy_raw.read_text()), self.event)

    def test_open_store_rejects_unknown_future_schema(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT INTO metadata VALUES('schema_version', '999')")

        with self.assertRaisesRegex(RuntimeError, "newer schema"):
            with open_store(self.database):
                pass


if __name__ == "__main__":
    unittest.main()
