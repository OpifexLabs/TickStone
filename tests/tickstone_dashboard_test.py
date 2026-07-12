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
    build_statistics_overview,
    build_overview_comparisons,
    build_timeline,
    make_handler,
    render_dashboard,
    render_habit_detail,
    render_statistics_dashboard,
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

    def add_habit(self, slot, code, name, kind, default_minutes=1):
        with open_store(self.database) as connection, connection:
            snapshot = connection.execute("SELECT id FROM habit_snapshots LIMIT 1").fetchone()[0]
            connection.execute(
                "INSERT INTO habits(slot_id,code,name,type,default_minutes,active,current_snapshot_id,updated_at) "
                "VALUES(?,?,?,?,?,1,?,'2026-07-12T00:00:00Z')",
                (slot, code, name, kind, default_minutes, snapshot),
            )
            connection.execute(
                "INSERT INTO habit_snapshot_entries(snapshot_id,slot_id,code,name,type,default_minutes,active) "
                "VALUES(?,?,?,?,?,?,1)", (snapshot, slot, code, name, kind, default_minutes),
            )

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
        self.assertEqual(model["trend_label"], "+150% jämfört med förra veckan")
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
    def test_overview_comparisons_are_clear_for_positive_negative_and_zero_baseline(self):
        for ident, stamp in enumerate(("2026-07-06T08:00:00", "2026-07-07T08:00:00", "2026-07-12T08:00:00"), 30):
            self.add(ident, 0, "count", stamp, count=1)
        self.add(40, 0, "count", "2026-06-29T08:00:00", count=1)
        self.add(41, 0, "count", "2026-07-05T08:00:00", count=1)

        comparisons = build_overview_comparisons(self.database, self.epoch("2026-07-12T12:00:00"))

        self.assertEqual(comparisons["week"], {"current": 3, "previous": 2, "percent": 50,
                                                "tone": "up", "label": "+50% jämfört med förra veckan"})
        self.assertEqual(comparisons["month"]["label"], "+300% jämfört med förra månaden")

        empty_database = self.root / "empty.sqlite3"
        with open_store(empty_database):
            pass
        empty = build_overview_comparisons(empty_database, self.epoch("2026-07-12T12:00:00"))
        self.assertEqual(empty["week"]["label"], "Samma nivå som förra veckan")
        self.assertEqual(empty["week"]["tone"], "flat")

    def test_timeline_zero_fills_buckets_and_groups_year_by_month(self):
        self.add(50, 0, "count", "2026-07-06T08:00:00", count=4)
        self.add(51, 1, "time", "2026-07-06T09:00:00", duration=90)
        self.add(52, 0, "count", "2026-07-12T08:00:00", count=1)
        self.add(53, 0, "count", "2026-06-01T08:00:00", count=1)

        week = build_timeline(self.database, "week", self.epoch("2026-07-12T12:00:00"))
        year = build_timeline(self.database, "year", self.epoch("2026-07-12T12:00:00"))

        self.assertEqual(len(week["labels"]), 7)
        meditation = next(item for item in week["series"] if item["id"] == 0)
        self.assertEqual(meditation["values"], [1, 0, 0, 0, 0, 0, 1])
        fallback = next(item for item in week["series"] if item["id"] == 1)
        self.assertEqual(fallback["name"], "Habit 2")
        self.assertEqual(len(year["labels"]), 12)
        self.assertEqual(next(item for item in year["series"] if item["id"] == 0)["values"][5:7], [1, 2])
        with self.assertRaises(ValueError):
            build_timeline(self.database, "decade", self.epoch("2026-07-12T12:00:00"))

    def test_month_comparison_reports_new_activity_without_fake_infinity(self):
        self.add(60, 0, "count", "2026-07-12T08:00:00", count=1)
        comparison = build_overview_comparisons(self.database, self.epoch("2026-07-12T12:00:00"))["month"]
        self.assertEqual(comparison["percent"], None)
        self.assertEqual(comparison["tone"], "up")
        self.assertEqual(comparison["label"], "Ny aktivitet den här månaden")
    def test_reference_overview_uses_calendar_period_navigation_and_kpis(self):
        self.add_habit(1, "MED", "MEDITATION", "time", default_minutes=10)
        self.add(70, 0, "count", "2026-07-06T08:00:00", count=1)
        self.add(71, 1, "time", "2026-07-06T09:00:00", duration=300)
        self.add(72, 0, "count", "2026-07-07T08:00:00", count=1)
        self.add(73, 1, "time", "2026-07-07T09:00:00", duration=600)
        self.add(74, 0, "count", "2026-06-30T08:00:00", count=1)
        self.add(75, 0, "count", "2026-07-08T08:00:00", count=1, deleted=True)

        model = build_statistics_overview(self.database, "week", 0, self.epoch("2026-07-12T12:00:00"))
        previous = build_statistics_overview(self.database, "week", -1, self.epoch("2026-07-12T12:00:00"))

        self.assertEqual((model["period_start"], model["period_end"]), ("2026-07-06", "2026-07-12"))
        self.assertEqual(model["period_label"], "6–12 juli 2026")
        self.assertEqual(model["navigation"], {"previous_offset": -1, "next_offset": None})
        self.assertEqual((previous["period_start"], previous["period_end"]), ("2026-06-29", "2026-07-05"))
        self.assertEqual(model["kpis"]["active_days"], 2)
        self.assertEqual(model["kpis"]["possible_days"], 7)
        self.assertEqual(model["kpis"]["completion_percent"], 25)
        self.assertEqual(model["kpis"]["total_seconds"], 900)
        self.assertEqual(model["kpis"]["comparison"]["label"], "+300% jämfört med förra veckan")
        self.assertEqual(len(model["activity"]), 7)
        self.assertEqual(model["activity"][0]["count_percent"], 100)
        self.assertEqual(model["activity"][0]["time_percent"], 50)

    def test_streak_remains_current_when_last_activity_was_yesterday(self):
        self.add(76, 0, "count", "2026-07-11T08:00:00", count=1)
        model = build_statistics_overview(self.database, "week", 0, self.epoch("2026-07-12T12:00:00"))
        self.assertEqual(model["habits"][0]["current_streak"], 1)

    def test_reference_overview_habit_rows_heatmap_and_insights_are_grounded(self):
        self.add_habit(1, "MED", "MEDITATION", "time", default_minutes=10)
        for ident, stamp in enumerate(("2026-07-06T08:00:00", "2026-07-07T08:00:00", "2026-07-08T08:00:00"), 80):
            self.add(ident, 0, "count", stamp, count=1)
        self.add(90, 1, "time", "2026-07-06T09:00:00", duration=600)

        model = build_statistics_overview(self.database, "week", 0, self.epoch("2026-07-12T12:00:00"))

        meditation = next(row for row in model["habits"] if row["id"] == 1)
        self.assertEqual((meditation["type_label"], meditation["display_value"]), ("Tid", "10 min"))
        self.assertEqual(meditation["progress_percent"], 14)
        self.assertEqual(len(model["heatmap"]["cells"]), 84)
        self.assertEqual(model["heatmap"]["weeks"], 12)
        self.assertTrue(all(0 <= cell["level"] <= 5 for cell in model["heatmap"]["cells"]))
        self.assertTrue(model["insights"])
        self.assertTrue(all(item["text"] and item["kind"] in ("calendar", "trend", "consistency")
                            for item in model["insights"]))

        rendered = render_statistics_dashboard(model)
        model["habits"][0]["current_streak"] = 1
        singular_rendered = render_statistics_dashboard(model)
        self.assertIn("1 dags streak", singular_rendered)
        self.assertNotIn("1 dagars streak", singular_rendered)
        for marker in ('class="app-sidebar"', 'Din statistik', 'Veckans aktivitet', 'Dina vanor',
                       'Aktivitet senaste 12 veckorna', 'Insikter', 'period-switcher', 'habit-performance'):
            self.assertIn(marker, rendered)
        self.assertIn('href="/?period=month&amp;offset=0"', rendered)
        self.assertIn('aria-label="Föregående period"', rendered)
        self.assertIn('<strong>Ny</strong><span>aktivitet den här veckan</span>', rendered)
        self.assertLess(rendered.index('class="stack-count"'), rendered.index('class="stack-time"'))
        self.assertNotIn("https://", rendered)

    def test_reference_overview_supports_month_year_all_and_rejects_future_offsets(self):
        month = build_statistics_overview(self.database, "month", 0, self.epoch("2024-02-29T12:00:00"))
        year = build_statistics_overview(self.database, "year", 0, self.epoch("2024-02-29T12:00:00"))
        all_time = build_statistics_overview(self.database, "all", 0, self.epoch("2024-02-29T12:00:00"))
        self.assertEqual((month["period_start"], month["period_end"], len(month["activity"])),
                         ("2024-02-01", "2024-02-29", 29))
        self.assertEqual((year["period_start"], year["period_end"], len(year["activity"])),
                         ("2024-01-01", "2024-12-31", 12))
        self.assertEqual(all_time["period_label"], "All sparad tid")
        with self.assertRaises(ValueError):
            build_statistics_overview(self.database, "week", 1, self.epoch("2026-07-12T12:00:00"))
        with self.assertRaises(ValueError):
            build_statistics_overview(self.database, "decade", 0, self.epoch("2026-07-12T12:00:00"))


class DashboardRenderTest(unittest.TestCase):
    def test_render_is_semantic_local_responsive_and_accessible(self):
        model = {
            "generated_at": "12 juli 2026 12:00",
            "metadata_status": "synced",
            "comparisons": {
                "week": {"current": 3, "previous": 2, "percent": 50, "tone": "up", "label": "+50% jämfört med förra veckan"},
                "month": {"current": 3, "previous": 0, "percent": None, "tone": "up", "label": "Ny aktivitet den här månaden"},
            },
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
        self.assertIn('+50% jämfört med förra veckan', html)
        self.assertIn('id="timeline-chart"', html)
        self.assertIn('data-range="week"', html)
        self.assertIn('aria-label="Välj habits i linjegrafen"', html)
        self.assertNotIn('https://', html)
        self.assertNotIn('http://', html)

        css = (ROOT / "tools" / "tickstone_dashboard_web" / "styles.css").read_text()
        self.assertIn("@media (max-width: 720px)", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn(":focus-visible", css)
        self.assertIn("overflow-x: hidden", css)
        self.assertIn("38px minmax(82px,1.2fr) minmax(48px,.6fr)", css)
        script = (ROOT / "tools" / "tickstone_dashboard_web" / "app.js").read_text()
        self.assertIn("Math.min(4, maximum)", script)
        self.assertIn("tickCount", script)

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
        self.assertIn('class="statistics-app"', rendered)
        self.assertIn('class="app-sidebar"', rendered)
        self.assertIn('detail-workspace', rendered)


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

    def test_overview_period_query_is_validated_and_read_only(self):
        before = (self.database.stat().st_mtime_ns, self.database.stat().st_size)
        status, _, body = self.request("GET", "/?period=month&offset=-1")
        self.assertEqual(status, 200)
        self.assertIn(b"Din statistik", body)
        self.assertEqual(self.request("GET", "/?period=decade")[0], 400)
        self.assertEqual(self.request("GET", "/?period=week&offset=1")[0], 400)
        self.assertEqual(self.request("GET", "/?period=week&offset=not-a-number")[0], 400)
        self.assertEqual((self.database.stat().st_mtime_ns, self.database.stat().st_size), before)

    def test_timeline_api_is_bounded_json_and_read_only(self):
        before = (self.database.stat().st_mtime_ns, self.database.stat().st_size)
        status, headers, body = self.request("GET", "/api/timeline?range=year")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        payload = json.loads(body)
        self.assertEqual(payload["range"], "year")
        self.assertEqual(len(payload["labels"]), 12)
        self.assertEqual(self.request("GET", "/api/timeline?range=decade")[0], 400)
        self.assertEqual((self.database.stat().st_mtime_ns, self.database.stat().st_size), before)

    def test_habit_routes_period_validation_and_read_only_http(self):
        before = (self.database.stat().st_mtime_ns, self.database.stat().st_size)
        self.assertEqual(self.request("GET", "/habit/0?period=week")[0], 404)
        self.assertEqual(self.request("GET", "/habit/9?period=nonsense")[0], 400)
        self.assertEqual(self.request("GET", "/habit/99")[0], 404)
        self.assertEqual((self.database.stat().st_mtime_ns, self.database.stat().st_size), before)


if __name__ == "__main__":
    unittest.main()
