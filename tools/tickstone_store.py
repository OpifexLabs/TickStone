#!/usr/bin/env python3
"""Durable TickStone event storage: immutable JSONL plus queryable SQLite."""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SCHEMA_VERSION = 2
REQUIRED_EVENT_KEYS = {
    "id", "habit_id", "type", "started_at", "ended_at",
    "duration_seconds", "count", "deleted",
}
STOCKHOLM = ZoneInfo("Europe/Stockholm")

SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS habits (
    slot_id INTEGER PRIMARY KEY CHECK (slot_id BETWEEN 0 AND 9),
    code TEXT,
    name TEXT,
    type TEXT CHECK (type IS NULL OR type IN ('count', 'time')),
    default_minutes INTEGER CHECK (default_minutes IS NULL OR default_minutes BETWEEN 1 AND 99),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    current_snapshot_id INTEGER,
    updated_at TEXT NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS habit_snapshots (
    id INTEGER PRIMARY KEY,
    content_hash TEXT NOT NULL UNIQUE,
    recorded_at TEXT NOT NULL,
    protocol_version INTEGER NOT NULL DEFAULT 0 CHECK (protocol_version >= 0),
    device_hash TEXT,
    valid_from INTEGER NOT NULL,
    valid_to INTEGER CHECK (valid_to IS NULL OR valid_to > valid_from)
) STRICT;
CREATE TABLE IF NOT EXISTS habit_snapshot_entries (
    snapshot_id INTEGER NOT NULL REFERENCES habit_snapshots(id) ON DELETE CASCADE,
    slot_id INTEGER NOT NULL CHECK (slot_id BETWEEN 0 AND 9),
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('count', 'time')),
    default_minutes INTEGER NOT NULL CHECK (default_minutes BETWEEN 1 AND 99),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    PRIMARY KEY (snapshot_id, slot_id)
) STRICT;
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY CHECK (id >= 0),
    habit_id INTEGER NOT NULL CHECK (habit_id BETWEEN 0 AND 9),
    type TEXT NOT NULL CHECK (type IN ('count', 'time')),
    started_at INTEGER NOT NULL CHECK (started_at >= 0),
    ended_at INTEGER NOT NULL CHECK (ended_at >= 0),
    duration_seconds INTEGER NOT NULL CHECK (duration_seconds >= 0),
    count INTEGER NOT NULL CHECK (count >= 0),
    deleted INTEGER NOT NULL CHECK (deleted IN (0, 1)),
    tickstone_day TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    raw_json TEXT NOT NULL
    ,config_snapshot_id INTEGER REFERENCES habit_snapshots(id)
) STRICT;
CREATE INDEX IF NOT EXISTS events_habit_day_idx ON events(habit_id, tickstone_day);
CREATE INDEX IF NOT EXISTS events_started_idx ON events(started_at);
CREATE INDEX IF NOT EXISTS events_active_day_idx ON events(tickstone_day, deleted);
CREATE INDEX IF NOT EXISTS events_habit_started_idx ON events(habit_id, started_at, deleted);
CREATE INDEX IF NOT EXISTS habit_snapshots_validity_idx ON habit_snapshots(valid_from, valid_to);
CREATE VIEW IF NOT EXISTS event_history AS
SELECT e.*, h.code AS current_habit_code, h.name AS current_habit_name
FROM events e LEFT JOIN habits h ON h.slot_id = e.habit_id;
"""


@dataclass(frozen=True)
class IngestResult:
    raw_appended: bool
    database_inserted: bool


@dataclass(frozen=True)
class ImportResult:
    read: int
    inserted: int


@dataclass(frozen=True)
class IntegrityReport:
    database_integrity: str
    database_events: int
    raw_valid_events: int
    raw_invalid_lines: tuple
    missing_from_database: tuple


@dataclass(frozen=True)
class BackupResult:
    database: Path
    raw_jsonl: Path


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def validate_event(event):
    if not isinstance(event, dict) or set(event) != REQUIRED_EVENT_KEYS:
        raise ValueError("event must contain exactly the TickStone event fields")
    integer_fields = ("id", "habit_id", "started_at", "ended_at", "duration_seconds", "count")
    for key in integer_fields:
        if type(event[key]) is not int:
            raise ValueError(f"{key} must be an integer")
    if type(event["deleted"]) is not bool:
        raise ValueError("deleted must be boolean")
    if event["id"] < 0 or not 0 <= event["habit_id"] <= 9:
        raise ValueError("event identifiers are out of range")
    if event["type"] not in ("count", "time"):
        raise ValueError("type must be count or time")
    if min(event["started_at"], event["ended_at"], event["duration_seconds"], event["count"]) < 0:
        raise ValueError("event values cannot be negative")
    if event["ended_at"] < event["started_at"]:
        raise ValueError("ended_at cannot precede started_at")
    return dict(event)


def tickstone_day(epoch_seconds):
    local = datetime.fromtimestamp(epoch_seconds, timezone.utc).astimezone(STOCKHOLM)
    return (local - timedelta(hours=5)).date()


@contextmanager
def open_store(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA journal_mode=WAL")
        has_metadata = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'"
        ).fetchone()
        current_version = 0
        if has_metadata:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()
            if row and int(row[0]) > SCHEMA_VERSION:
                raise RuntimeError("database uses a newer schema version")
            current_version = int(row[0]) if row else 0
        if current_version == 1:
            _migrate_v1_to_v2(connection)
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO metadata(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(SCHEMA_VERSION),),
        )
        connection.commit()
        yield connection
    finally:
        connection.close()


def _migrate_v1_to_v2(connection):
    connection.execute("ALTER TABLE habit_snapshots ADD COLUMN protocol_version INTEGER NOT NULL DEFAULT 0")
    connection.execute("ALTER TABLE habit_snapshots ADD COLUMN device_hash TEXT")
    connection.execute("ALTER TABLE habit_snapshots ADD COLUMN valid_from INTEGER")
    connection.execute("ALTER TABLE habit_snapshots ADD COLUMN valid_to INTEGER")
    connection.execute("ALTER TABLE habit_snapshot_entries ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
    connection.execute("ALTER TABLE events ADD COLUMN config_snapshot_id INTEGER REFERENCES habit_snapshots(id)")
    connection.execute(
        "UPDATE habit_snapshots SET valid_from=COALESCE(CAST(strftime('%s', recorded_at) AS INTEGER), 0)"
    )
    rows = connection.execute("SELECT id, valid_from FROM habit_snapshots ORDER BY valid_from, id").fetchall()
    for index, (snapshot_id, _) in enumerate(rows[:-1]):
        connection.execute("UPDATE habit_snapshots SET valid_to=? WHERE id=?", (rows[index + 1][1], snapshot_id))
    connection.execute("UPDATE metadata SET value='2' WHERE key='schema_version'")
    connection.commit()


def _insert_event(connection, event, ingested_at=None, snapshot_id=None):
    event = validate_event(event)
    raw = canonical_json(event)
    existing = connection.execute("SELECT raw_json FROM events WHERE id=?", (event["id"],)).fetchone()
    if existing:
        if existing[0] != raw:
            raise ValueError(f"conflicting payload for event id {event['id']}")
        return False
    now = ingested_at or utc_now()
    connection.execute(
        "INSERT OR IGNORE INTO habits(slot_id, active, updated_at) VALUES(?, 1, ?)",
        (event["habit_id"], now),
    )
    connection.execute(
        """INSERT INTO events(
            id, habit_id, type, started_at, ended_at, duration_seconds, count,
            deleted, tickstone_day, ingested_at, raw_json, config_snapshot_id
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event["id"], event["habit_id"], event["type"], event["started_at"],
            event["ended_at"], event["duration_seconds"], event["count"],
            int(event["deleted"]), tickstone_day(event["started_at"]).isoformat(), now, raw, snapshot_id,
        ),
    )
    return True


def raw_event_exists(path, event):
    path = Path(path)
    raw = canonical_json(event)
    if not path.exists():
        return False
    with path.open(encoding="utf-8") as source:
        for line in source:
            try:
                current = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(current, dict) and current.get("id") == event["id"]:
                if canonical_json(current) != raw:
                    raise ValueError(f"conflicting payload for event id {event['id']}")
                return True
    return False


def append_raw_once(path, event):
    path = Path(path)
    raw = canonical_json(event)
    if raw_event_exists(path, event):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(raw + "\n")
        output.flush()
        os.fsync(output.fileno())
    return True


def ingest_event(raw_path, database_path, event, snapshot_id=None):
    event = validate_event(event)
    raw_already_present = raw_event_exists(raw_path, event)
    with open_store(database_path) as connection:
        with connection:
            inserted = _insert_event(connection, event, snapshot_id=snapshot_id)
    raw_appended = False if raw_already_present else append_raw_once(raw_path, event)
    return IngestResult(raw_appended, inserted)


def import_jsonl(raw_path, database_path):
    read = inserted = 0
    with open_store(database_path) as connection:
        with Path(raw_path).open(encoding="utf-8") as source, connection:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"invalid JSON on line {line_number}") from error
                read += 1
                inserted += int(_insert_event(connection, event))
    return ImportResult(read, inserted)


def _validate_habits(habits):
    if not isinstance(habits, list) or len(habits) > 10:
        raise ValueError("habits must be a list with at most ten entries")
    clean = []
    seen = set()
    for habit in habits:
        if not isinstance(habit, dict) or not set(habit).issubset(
                {"id", "code", "name", "mode", "minutes", "active"}) or not {
                    "id", "code", "name", "mode", "minutes"
                }.issubset(habit):
            raise ValueError("invalid habit fields")
        ident = habit["id"]
        if type(ident) is not int or not 0 <= ident <= 9 or ident in seen:
            raise ValueError("habit id must be unique and between zero and nine")
        seen.add(ident)
        mode = habit["mode"]
        if mode not in ("count", "time"):
            raise ValueError("habit mode must be count or time")
        minutes = habit["minutes"]
        if type(minutes) is not int or not 1 <= minutes <= 99:
            raise ValueError("habit minutes must be between one and 99")
        code = str(habit["code"]).strip().upper()
        name = " ".join(str(habit["name"]).strip().upper().split())
        active = habit.get("active", True)
        if type(active) is not bool:
            raise ValueError("habit active must be boolean")
        if active and (not 1 <= len(code) <= 3 or not 1 <= len(name) <= 15):
            raise ValueError("habit code or name has invalid length")
        if not active and (len(code) > 3 or len(name) > 15):
            raise ValueError("inactive habit code or name has invalid length")
        clean.append({"id": ident, "code": code, "name": name, "mode": mode,
                      "minutes": minutes, "active": active})
    return sorted(clean, key=lambda item: item["id"])


def _epoch_from_recorded_at(recorded_at):
    if recorded_at is None:
        return int(datetime.now(timezone.utc).timestamp())
    return int(datetime.fromisoformat(recorded_at.replace("Z", "+00:00")).timestamp())


def record_habits(database_path, habits, recorded_at=None, valid_from=None,
                  device_hash=None, protocol_version=1):
    clean = _validate_habits(habits)
    raw = canonical_json(clean)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    now = recorded_at or utc_now()
    requested_from = int(valid_from) if valid_from is not None else _epoch_from_recorded_at(now)
    with open_store(database_path) as connection, connection:
        existing = connection.execute(
            "SELECT id FROM habit_snapshots WHERE content_hash=?", (digest,)
        ).fetchone()
        if existing:
            return existing[0]
        latest = connection.execute(
            "SELECT valid_from FROM habit_snapshots ORDER BY valid_from DESC, id DESC LIMIT 1"
        ).fetchone()
        effective_from = max(requested_from, latest[0] + 1) if latest else requested_from
        connection.execute(
            "UPDATE habit_snapshots SET valid_to=? WHERE valid_to IS NULL", (effective_from,)
        )
        cursor = connection.execute(
            """INSERT INTO habit_snapshots(
                   content_hash, recorded_at, protocol_version, device_hash, valid_from
               ) VALUES(?, ?, ?, ?, ?)""",
            (digest, now, protocol_version, device_hash, effective_from),
        )
        snapshot_id = cursor.lastrowid
        for habit in clean:
            connection.execute(
                """INSERT INTO habit_snapshot_entries(
                    snapshot_id, slot_id, code, name, type, default_minutes, active
                ) VALUES(?, ?, ?, ?, ?, ?, ?)""",
                (snapshot_id, habit["id"], habit["code"], habit["name"], habit["mode"],
                 habit["minutes"], int(habit["active"])),
            )
        active_ids = {habit["id"] for habit in clean if habit["active"]}
        connection.execute("UPDATE habits SET active=0, updated_at=?", (now,))
        for habit in clean:
            if not habit["active"]:
                continue
            connection.execute(
                """INSERT INTO habits(slot_id, code, name, type, default_minutes, active,
                           current_snapshot_id, updated_at)
                   VALUES(?, ?, ?, ?, ?, 1, ?, ?)
                   ON CONFLICT(slot_id) DO UPDATE SET code=excluded.code, name=excluded.name,
                     type=excluded.type, default_minutes=excluded.default_minutes, active=1,
                     current_snapshot_id=excluded.current_snapshot_id, updated_at=excluded.updated_at""",
                (habit["id"], habit["code"], habit["name"], habit["mode"], habit["minutes"], snapshot_id, now),
            )
        if active_ids:
            placeholders = ",".join("?" for _ in active_ids)
            connection.execute(
                f"UPDATE habits SET active=0, updated_at=? WHERE slot_id NOT IN ({placeholders})",
                (now, *sorted(active_ids)),
            )
        return snapshot_id


def event_habit_metadata(connection, event_id):
    event = connection.execute(
        "SELECT habit_id, started_at, config_snapshot_id FROM events WHERE id=?", (event_id,)
    ).fetchone()
    if not event:
        return None
    habit_id, started_at, snapshot_id = event
    if snapshot_id is not None:
        row = connection.execute(
            """SELECT code, name, type FROM habit_snapshot_entries
                WHERE snapshot_id=? AND slot_id=? AND active=1""", (snapshot_id, habit_id)
        ).fetchone()
        if row:
            return {"code": row[0], "name": row[1], "type": row[2], "status": "exact"}
    row = connection.execute(
        """SELECT e.code, e.name, e.type
             FROM habit_snapshot_entries e
             JOIN habit_snapshots s ON s.id=e.snapshot_id
            WHERE e.slot_id=? AND e.active=1 AND s.valid_from<=?
              AND (s.valid_to IS NULL OR ?<s.valid_to)
            ORDER BY s.valid_from DESC LIMIT 1""", (habit_id, started_at, started_at)
    ).fetchone()
    if row:
        return {"code": row[0], "name": row[1], "type": row[2], "status": "exact"}
    row = connection.execute("SELECT code, name, type FROM habits WHERE slot_id=?", (habit_id,)).fetchone()
    if row and row[1]:
        return {"code": row[0], "name": row[1], "type": row[2], "status": "fallback"}
    return {"code": None, "name": None, "type": None, "status": "missing"}


def integrity_report(raw_path, database_path):
    raw_ids = []
    invalid = []
    raw_path = Path(raw_path)
    lines = raw_path.read_text(encoding="utf-8").splitlines() if raw_path.exists() else []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            event = validate_event(json.loads(line))
            raw_ids.append(event["id"])
        except (json.JSONDecodeError, ValueError, TypeError):
            invalid.append(number)
    with open_store(database_path) as connection:
        health = connection.execute("PRAGMA integrity_check").fetchone()[0]
        database_ids = {row[0] for row in connection.execute("SELECT id FROM events")}
    return IntegrityReport(health, len(database_ids), len(raw_ids), tuple(invalid),
                           tuple(sorted(set(raw_ids) - database_ids)))


def _unique_backup_path(directory, stem, suffix):
    candidate = directory / f"{stem}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


def backup_store(raw_path, database_path, backup_dir, timestamp=None):
    raw_path, database_path, backup_dir = Path(raw_path), Path(database_path), Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    database_backup = _unique_backup_path(backup_dir, f"tickstone-{stamp}", ".sqlite3")
    raw_backup = _unique_backup_path(backup_dir, f"logs-{stamp}", ".jsonl")
    with open_store(database_path) as source, sqlite3.connect(database_backup) as destination:
        source.backup(destination)
    if raw_path.exists():
        shutil.copy2(raw_path, raw_backup)
    else:
        raw_backup.touch(mode=0o600)
    return BackupResult(database_backup, raw_backup)


def _paths(args):
    data_dir = Path(args.data_dir).expanduser()
    return data_dir / "logs.jsonl", data_dir / "tickstone.sqlite3"


def main():
    parser = argparse.ArgumentParser(description="Store and verify TickStone history")
    parser.add_argument("--data-dir", default="~/.local/share/tickstone")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("import-jsonl")
    commands.add_parser("integrity")
    habits = commands.add_parser("record-habits")
    habits.add_argument("json_file", type=Path)
    backup = commands.add_parser("backup")
    backup.add_argument("--backup-dir")
    args = parser.parse_args()
    raw_path, database_path = _paths(args)
    if args.command == "init":
        with open_store(database_path):
            pass
        print(database_path)
    elif args.command == "import-jsonl":
        result = import_jsonl(raw_path, database_path)
        print(f"read={result.read} inserted={result.inserted} database={database_path}")
    elif args.command == "integrity":
        result = integrity_report(raw_path, database_path)
        print(canonical_json(result.__dict__))
        if result.database_integrity != "ok" or result.raw_invalid_lines or result.missing_from_database:
            raise SystemExit(1)
    elif args.command == "record-habits":
        payload = json.loads(args.json_file.read_text())
        snapshot = record_habits(database_path, payload.get("habits", payload))
        print(f"snapshot={snapshot}")
    else:
        directory = Path(args.backup_dir).expanduser() if args.backup_dir else Path(args.data_dir).expanduser() / "backups"
        result = backup_store(raw_path, database_path, directory)
        print(f"database={result.database}\njsonl={result.raw_jsonl}")


if __name__ == "__main__":
    main()
