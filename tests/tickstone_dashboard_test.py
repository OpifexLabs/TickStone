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
    build_habit_detail,
    make_handler,
    render_dashboard,
    render_habit_detail,
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
                """INSERT INTO habit_snapshots(
                       content_hash, recorded_at, protocol_version, device_hash, valid_from
                   ) VALUES('snapshot', '2026-07-12T00:00:00Z', 1, '12345678', 0)"""
            )
            snapshot = connection.execute("SELECT id FROM habit_snapshots").fetchone()[0]
            connection.execute(
                "INSERT INTO habits(slot_id, code, name, type, default_minutes, active, current_snapshot_id, updated_at) "
                "VALUES(0, 'MED', 'MEDITATION', 'count', 1, 1, ?, '2026-07-12T00:00:00Z')",
                (snapshot,),
            )
            connection.execute(
                """INSERT INTO habit_snapshot_entries(
                       snapshot_id,slot_id,code,name,type,default_minutes,active
                   ) VALUES(?,0,'MED','MEDITATION','count',1,1)""", (snapshot,)
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
        self.assertEqual([(item["name"], item["sessions"]) for item in model["habits"]], [("MEDITATION", 0)])
        self.assertEqual(model["recent"], [])
        self.assertEqual(model["metadata_status"], "synced")

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

    def test_week_detail_uses_tickstone_days_semantics_and_previous_comparison(self):
        self.add(10, 0, "count", "2026-07-06T08:00:00", count=2)
        self.add(11, 0, "count", "2026-07-07T08:00:00", count=3)
        self.add(12, 0, "count", "2026-06-30T08:00:00", count=2)
        self.add(13, 0, "count", "2026-07-08T08:00:00", count=99, deleted=True)

        model = build_habit_detail(self.database, 0, "week", self.epoch("2026-07-12T12:00:00"))

        self.assertEqual(model["total"], 5)
        self.assertEqual(model["active_days"], 2)
        self.assertEqual(model["sessions"], 2)
        self.assertEqual(model["previous_total"], 2)
        self.assertEqual(model["trend"], 150)
        self.assertEqual(model["longest_streak"], 2)
        self.assertEqual(model["average_value"], 2)

    def test_month_year_and_zero_baseline_are_calendar_bounded(self):
        self.add(20, 0, "count", "2024-02-29T08:00:00", count=1)
        month = build_habit_detail(self.database, 0, "month", self.epoch("2024-02-29T12:00:00"))
        year = build_habit_detail(self.database, 0, "year", self.epoch("2024-12-31T12:00:00"))
        self.assertEqual((month["period_start"], month["period_end"]), ("2024-02-01", "2024-02-29"))
        self.assertEqual(month["trend"], None)
        self.assertEqual((year["period_start"], year["period_end"]), ("2024-01-01", "2024-12-31"))
        self.assertEqual(year["total"], 1)
        self.assertEqual(len(month["points"]), 29)
        self.assertEqual(len(year["points"]), 12)


class DashboardRenderTest(unittest.TestCase):
    def test_render_is_semantic_local_responsive_and_accessible(self):
        model = {
            "generated_at": "12 juli 2026 12:00",
            "metadata_status": "synced",
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

    def test_detail_render_escapes_metadata_and_has_period_navigation(self):
        model = {"habit": {"id": 0, "code": "<X", "name": "<script>", "type": "count"},
                 "period": "week", "period_start": "2026-07-06", "period_end": "2026-07-12",
                 "metadata_status": "synced", "display_value": "2", "display_unit": "gånger",
                 "active_days": 1, "average_value": "2", "average_unit": "gånger",
                 "longest_streak": 1, "current_streak": 0, "sessions": 1, "trend": None,
                 "best_day": "2026-07-07", "best_period": "2026-07-07",
                 "points": [{"label": "2026-07-07", "value": 2, "height": 100}]}
        rendered = render_habit_detail(model)
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn('/habit/0?period=month', rendered)
        self.assertIn('aria-current=page', rendered)


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

    def test_habit_routes_period_validation_and_read_only_http(self):
        before = (self.database.stat().st_mtime_ns, self.database.stat().st_size)
        self.assertEqual(self.request("GET", "/habit/0?period=week")[0], 404)
        self.assertEqual(self.request("GET", "/habit/9?period=nonsense")[0], 400)
        self.assertEqual(self.request("GET", "/habit/99")[0], 404)
        self.assertEqual((self.database.stat().st_mtime_ns, self.database.stat().st_size), before)


if __name__ == "__main__":
    unittest.main()
