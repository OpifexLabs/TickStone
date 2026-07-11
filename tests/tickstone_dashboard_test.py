#!/usr/bin/env python3
import http.client
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.tickstone_store import ingest_event, open_store  # noqa: E402
from tools.tickstone_dashboard import (  # noqa: E402
    DashboardServer,
    build_dashboard,
    make_handler,
    render_dashboard,
)


class DashboardDataTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.raw = self.root / "logs.jsonl"
        self.database = self.root / "tickstone.sqlite3"
        self.stockholm = ZoneInfo("Europe/Stockholm")
        with open_store(self.database) as connection, connection:
            connection.execute(
                "INSERT INTO habit_snapshots(content_hash, recorded_at) VALUES('snapshot', '2026-07-12T00:00:00Z')"
            )
            snapshot = connection.execute("SELECT id FROM habit_snapshots").fetchone()[0]
            connection.execute(
                "INSERT INTO habits(slot_id, code, name, type, default_minutes, active, current_snapshot_id, updated_at) "
                "VALUES(0, 'MED', 'MEDITATION', 'count', 1, 1, ?, '2026-07-12T00:00:00Z')",
                (snapshot,),
            )

    def tearDown(self):
        self.temp.cleanup()

    def epoch(self, value):
        return int(datetime.fromisoformat(value).replace(tzinfo=self.stockholm).timestamp())

    def add(self, ident, habit_id, kind, started, duration=0, count=0, deleted=False):
        start = self.epoch(started)
        ingest_event(self.raw, self.database, {
            "id": ident,
            "habit_id": habit_id,
            "type": kind,
            "started_at": start,
            "ended_at": start + duration,
            "duration_seconds": duration,
            "count": count,
            "deleted": deleted,
        })

    def test_empty_dashboard_has_stable_zero_state(self):
        model = build_dashboard(self.database, self.epoch("2026-07-12T12:00:00"))

        self.assertEqual(model["summary"], {"today": 0, "week": 0, "minutes": 0, "streak": 0})
        self.assertEqual(len(model["days"]), 7)
        self.assertEqual(model["habits"], [])
        self.assertEqual(model["recent"], [])

    def test_dashboard_aggregates_active_events_and_uses_known_or_fallback_names(self):
        self.add(1, 0, "count", "2026-07-12T08:00:00", count=2)
        self.add(2, 1, "time", "2026-07-12T09:00:00", duration=125)
        self.add(3, 0, "count", "2026-07-11T04:30:00", count=1)
        self.add(4, 0, "count", "2026-07-10T10:00:00", count=5, deleted=True)

        model = build_dashboard(self.database, self.epoch("2026-07-12T12:00:00"))

        self.assertEqual(model["summary"], {"today": 2, "week": 3, "minutes": 2, "streak": 1})
        self.assertEqual([day["value"] for day in model["days"]], [0, 0, 0, 0, 1, 0, 2])
        self.assertEqual(model["habits"][0]["name"], "MEDITATION")
        self.assertEqual(model["habits"][0]["total"], 3)
        self.assertEqual(model["habits"][1]["name"], "Habit 2")
        self.assertEqual(model["habits"][1]["minutes"], 2)
        self.assertEqual((model["habits"][1]["display_value"], model["habits"][1]["display_unit"]), (2, "minuter"))
        self.assertEqual([item["id"] for item in model["recent"]], [2, 1, 3])
        self.assertNotIn(4, [item["id"] for item in model["recent"]])

    def test_short_time_habit_is_not_rendered_as_zero_minutes(self):
        self.add(5, 2, "time", "2026-07-12T10:00:00", duration=5)

        model = build_dashboard(self.database, self.epoch("2026-07-12T12:00:00"))

        habit = next(item for item in model["habits"] if item["id"] == 2)
        self.assertEqual((habit["display_value"], habit["display_unit"]), (5, "sekunder"))

    def test_dashboard_connection_is_read_only(self):
        build_dashboard(self.database, self.epoch("2026-07-12T12:00:00"))
        before = self.database.stat().st_mtime_ns

        build_dashboard(self.database, self.epoch("2026-07-12T12:01:00"))

        self.assertEqual(self.database.stat().st_mtime_ns, before)


class DashboardRenderTest(unittest.TestCase):
    def test_render_is_semantic_local_responsive_and_accessible(self):
        model = {
            "generated_at": "12 juli 2026 12:00",
            "summary": {"today": 2, "week": 3, "minutes": 2, "streak": 2},
            "days": [{"label": label, "value": index, "height": index * 10} for index, label in enumerate("MTOTFLS")],
            "habits": [{"id": 0, "name": "MEDITATION", "code": "MED", "total": 3, "minutes": 0,
                        "display_value": 3, "display_unit": "gånger"}],
            "recent": [{"id": 1, "name": "MEDITATION", "kind": "2 gånger", "when": "Idag 08:00"}],
        }

        html = render_dashboard(model)

        for marker in ("<main", "<header", "<section", "aria-label=", "TickStone", "Senaste aktivitet"):
            self.assertIn(marker, html)
        self.assertIn('/assets/styles.css', html)
        self.assertIn('/assets/app.js', html)
        self.assertNotIn('https://', html)
        self.assertNotIn('http://', html)

        css = (ROOT / "tools" / "tickstone_dashboard_web" / "styles.css").read_text()
        self.assertIn("@media (max-width: 720px)", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn(":focus-visible", css)
        self.assertIn("overflow-x: hidden", css)


class DashboardHttpTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "tickstone.sqlite3"
        with open_store(self.database):
            pass
        self.server = DashboardServer(("127.0.0.1", 0), make_handler(self.database))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, method, path):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=3)
        connection.request(method, path)
        response = connection.getresponse()
        body = response.read()
        headers = dict(response.getheaders())
        connection.close()
        return response.status, headers, body

    def test_dashboard_health_assets_and_security_headers(self):
        for path, content_type in (("/", "text/html"), ("/assets/styles.css", "text/css"),
                                   ("/assets/app.js", "text/javascript")):
            status, headers, body = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertIn(content_type, headers["Content-Type"])
            self.assertTrue(body)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(headers["X-Frame-Options"], "DENY")
            self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
            self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        status, headers, body = self.request("GET", "/healthz")
        self.assertEqual((status, body), (200, b'{"status":"ok"}\n'))
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")

    def test_head_404_and_mutations_are_bounded(self):
        status, _, body = self.request("HEAD", "/")
        self.assertEqual((status, body), (200, b""))
        self.assertEqual(self.request("GET", "/../etc/passwd")[0], 404)
        self.assertEqual(self.request("GET", "/missing")[0], 404)
        status, headers, _ = self.request("POST", "/")
        self.assertEqual(status, 405)
        self.assertEqual(headers["Allow"], "GET, HEAD")


if __name__ == "__main__":
    unittest.main()
