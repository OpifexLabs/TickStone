#!/usr/bin/env python3
import http.client
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
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
    build_dashboard_intelligence,
    build_habit_detail,
    build_statistics_overview,
    build_time_chart,
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

    def change_habit(self, slot, code, name, kind, default_minutes=1, valid_from=None):
        valid_from = valid_from or self.epoch("2026-07-01T00:00:00")
        with open_store(self.database) as connection, connection:
            connection.execute(
                "INSERT INTO habit_snapshots(content_hash,recorded_at,protocol_version,device_hash,valid_from) VALUES(?,?,?,?,?)",
                (f"snapshot-{slot}-{kind}-{valid_from}", "2026-07-01T00:00:00Z", 1, "12345678", valid_from),
            )
            snapshot = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO habit_snapshot_entries(snapshot_id,slot_id,code,name,type,default_minutes,active) VALUES(?,?,?,?,?,?,1)",
                (snapshot, slot, code, name, kind, default_minutes),
            )
            connection.execute(
                "UPDATE habits SET code=?,name=?,type=?,default_minutes=?,current_snapshot_id=? WHERE slot_id=?",
                (code, name, kind, default_minutes, snapshot, slot),
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
        self.assertEqual((model["habits"][1]["display_value"], model["habits"][1]["display_unit"]), (2, "minutes"))
        self.assertEqual([item["id"] for item in model["recent"]], [2, 1, 3])
        self.assertNotIn(4, [item["id"] for item in model["recent"]])

    def test_short_time_habit_is_not_rendered_as_zero_minutes(self):
        self.add(5, 2, "time", "2026-07-12T10:00:00", duration=5)

        model = build_dashboard(self.database, self.epoch("2026-07-12T12:00:00"))

        habit = next(item for item in model["habits"] if item["id"] == 2)
        self.assertEqual((habit["display_value"], habit["display_unit"]), (5, "seconds"))

    def test_dashboard_closes_every_read_only_connection(self):
        created = []
        original_connect = sqlite3.connect

        class TrackingConnection(sqlite3.Connection):
            was_closed = False
            def close(self):
                self.was_closed = True
                super().close()

        def tracked_connect(*args, **kwargs):
            kwargs["factory"] = TrackingConnection
            connection = original_connect(*args, **kwargs)
            created.append(connection)
            return connection

        with patch("tools.tickstone_dashboard.sqlite3.connect", side_effect=tracked_connect):
            build_statistics_overview(self.database, "week", 0, self.epoch("2026-07-12T12:00:00"))
            build_time_chart(self.database, "week", 0, self.epoch("2026-07-12T12:00:00"))
        self.assertTrue(created)
        self.assertTrue(all(connection.was_closed for connection in created))

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
        self.assertEqual(model["trend_label"], "+150% compared with last week")
        self.assertEqual(model["longest_streak"], 2)
        self.assertEqual(model["average_value"], 2)
        self.assertEqual(model["trend_summary"]["title"], "New rhythm")

    def test_rich_time_detail_exposes_comparisons_chart_modes_records_patterns_calendar_and_logs(self):
        self.add_habit(1, "MED", "MEDITATION", "time", 10)
        stamps = (
            (60, "2026-06-15T07:00:00", 600),
            (61, "2026-06-22T07:00:00", 900),
            (62, "2026-06-29T07:00:00", 1200),
            (63, "2026-07-06T07:00:00", 600),
            (64, "2026-07-07T07:10:00", 1200),
            (65, "2026-07-08T07:20:00", 1800),
            (66, "2026-07-11T08:00:00", 2400),
            (67, "2026-07-12T08:30:00", 600),
        )
        for ident, stamp, duration in stamps:
            self.add(ident, 1, "time", stamp, duration=duration)

        model = build_habit_detail(self.database, 1, "week", self.epoch("2026-07-12T12:00:00"))

        self.assertNotIn("goal", model)
        self.assertEqual(model["comparisons"]["week"]["current"], 6600)
        self.assertIn("month", model["comparisons"])
        self.assertEqual(set(model["chart_modes"]), {"day", "week", "month"})
        self.assertEqual([len(model["chart_modes"][key]) for key in ("day", "week", "month")], [14, 8, 12])
        self.assertEqual(model["records"]["longest_session"]["value"], 2400)
        self.assertEqual(model["records"]["best_day"]["value"], 2400)
        self.assertEqual(model["records"]["best_week"]["value"], 6600)
        self.assertEqual(model["records"]["longest_streak"]["value"], 3)
        self.assertTrue(model["records"]["latest_record_date"])
        self.assertGreaterEqual(len(model["patterns"]), 2)
        self.assertEqual(len(model["calendar"]["cells"]), 84)
        self.assertTrue(any(cell["events"] for cell in model["calendar"]["cells"]))
        self.assertEqual(model["log_groups"][0]["date"], "2026-07-12")
        self.assertEqual(model["log_groups"][0]["events"][0]["source"], "TickStone")
        self.assertIn("trend_summary", model)
        model["calendar"]["cells"][-1]["future"] = True
        rendered = render_habit_detail(model)
        self.assertIn('aria-describedby="detail-chart-data"', rendered)
        self.assertIn('id="detail-chart-data" class="sr-only"', rendered)
        self.assertIn('<noscript>', rendered)
        self.assertIn(' future" disabled', rendered)

    def test_detail_milestone_requires_beating_previous_week_best(self):
        self.add_habit(1, "MED", "MEDITATION", "time", 10)
        self.add(68, 1, "time", "2026-06-29T08:00:00", duration=900)
        self.add(69, 1, "time", "2026-07-06T08:00:00", duration=600)
        model = build_habit_detail(self.database, 1, "week", self.epoch("2026-07-06T12:00:00"))
        self.assertEqual(model["milestone"]["remaining"], 301)
        self.assertIn("5 min 1 sec left", model["milestone"]["text"])

    def test_detail_excludes_snapshotless_legacy_events_before_current_identity(self):
        self.change_habit(0, "RUN", "RUNNING", "count", valid_from=self.epoch("2026-07-01T05:00:00"))
        self.add(701, 0, "count", "2026-06-30T08:00:00", count=99)
        self.add(702, 0, "count", "2026-07-02T08:00:00", count=2)
        with open_store(self.database) as connection, connection:
            connection.execute("UPDATE events SET config_snapshot_id=NULL WHERE id IN (701,702)")
        model = build_habit_detail(self.database, 0, "all", self.epoch("2026-07-12T12:00:00"))
        self.assertEqual(model["total"], 2)
        self.assertEqual(model["records"]["best_day"]["value"], 2)

    def test_overview_and_time_chart_share_current_identity_boundary(self):
        self.add_habit(1, "OLD", "OLD TIMER", "time", 10)
        self.change_habit(1, "NEW", "NEW TIMER", "time", 10, valid_from=self.epoch("2026-07-10T05:00:00"))
        self.add(740, 1, "time", "2026-07-06T08:00:00", duration=99)
        self.add(741, 1, "time", "2026-07-11T08:00:00", duration=2)
        with open_store(self.database) as connection, connection:
            connection.execute("UPDATE events SET config_snapshot_id=NULL WHERE id IN (740,741)")

        overview = build_statistics_overview(self.database, "week", 0, self.epoch("2026-07-12T12:00:00"))
        chart = build_time_chart(self.database, "week", 0, self.epoch("2026-07-12T12:00:00"))

        self.assertEqual(overview["kpis"]["total_seconds"], 2)
        self.assertEqual(next(item for item in overview["habits"] if item["id"] == 1)["display_value"], "2 sec")
        self.assertEqual(chart["total_seconds"], 2)

    def test_detail_weekend_pattern_uses_tickstone_day_boundary(self):
        self.add_habit(1, "MED", "MEDITATION", "time", 10)
        for ident, stamp, duration in (
            (710, "2026-03-30T02:00:00", 100), (711, "2026-03-29T12:00:00", 100),
            (712, "2026-03-31T10:00:00", 10), (713, "2026-04-04T02:00:00", 10),
        ):
            self.add(ident, 1, "time", stamp, duration=duration)
        model = build_habit_detail(self.database, 1, "week", self.epoch("2026-07-12T14:00:00"))
        self.assertTrue(any("longer sessions on weekends" in item for item in model["patterns"]))

    def test_detail_trend_uses_only_completed_weeks(self):
        self.add_habit(1, "MED", "MEDITATION", "time", 10)
        for ident, stamp, duration in (
            (720, "2026-06-08T08:00:00", 10), (721, "2026-06-15T08:00:00", 20),
            (722, "2026-06-22T08:00:00", 30), (723, "2026-06-29T08:00:00", 40),
            (724, "2026-07-06T08:00:00", 1),
        ):
            self.add(ident, 1, "time", stamp, duration=duration)
        model = build_habit_detail(self.database, 1, "week", self.epoch("2026-07-08T12:00:00"))
        self.assertEqual(model["trend_summary"]["title"], "Trending up")
        self.assertIn("completed weeks", model["trend_summary"]["text"])

    def test_detail_week_record_uses_last_contributing_day_and_ties_do_not_create_patterns(self):
        self.add_habit(1, "MED", "MEDITATION", "time", 10)
        for ident, stamp in ((730, "2026-06-29T08:00:00"), (731, "2026-07-01T08:00:00"),
                             (732, "2026-07-06T08:00:00"), (733, "2026-07-08T08:00:00")):
            self.add(ident, 1, "time", stamp, duration=10)
        model = build_habit_detail(self.database, 1, "all", self.epoch("2026-07-12T12:00:00"))
        self.assertEqual(model["records"]["best_week"]["date"], "2026-07-01")
        self.assertFalse(any("mest konsekventa dag" in item for item in model["patterns"]))

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
                                                "tone": "up", "label": "+50% compared with last week"})
        self.assertEqual(comparisons["month"]["label"], "+300% compared with last month")

        empty_database = self.root / "empty.sqlite3"
        with open_store(empty_database):
            pass
        empty = build_overview_comparisons(empty_database, self.epoch("2026-07-12T12:00:00"))
        self.assertEqual(empty["week"]["label"], "Same level as last week")
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

    def test_time_chart_uses_real_seconds_and_ignores_count_habits(self):
        self.add_habit(1, "MED", "MEDITATION", "time", default_minutes=10)
        self.add_habit(2, "STA", "STÄDA", "time", default_minutes=10)
        self.add(101, 0, "count", "2026-07-11T08:00:00", count=1)
        self.add(102, 1, "time", "2026-07-11T09:00:00", duration=5)
        self.add(103, 2, "time", "2026-07-11T10:00:00", duration=3)

        chart = build_time_chart(self.database, "week", 0, self.epoch("2026-07-12T12:00:00"))

        self.assertEqual(chart["unit"], "seconds")
        self.assertEqual(len(chart["labels"]), 7)
        self.assertEqual([series["id"] for series in chart["series"]], [1, 2])
        self.assertEqual(next(series for series in chart["series"] if series["id"] == 1)["values"], [0, 0, 0, 0, 0, 5, 0])
        self.assertEqual(next(series for series in chart["series"] if series["id"] == 2)["values"], [0, 0, 0, 0, 0, 3, 0])
        self.assertEqual(chart["total_seconds"], 8)

    def test_month_comparison_reports_new_activity_without_fake_infinity(self):
        self.add(60, 0, "count", "2026-07-12T08:00:00", count=1)
        comparison = build_overview_comparisons(self.database, self.epoch("2026-07-12T12:00:00"))["month"]
        self.assertEqual(comparison["percent"], None)
        self.assertEqual(comparison["tone"], "up")
        self.assertEqual(comparison["label"], "New activity this month")
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
        self.assertEqual(model["period_label"], "July 6–12, 2026")
        self.assertEqual(model["navigation"], {"previous_offset": -1, "next_offset": None})
        self.assertEqual((previous["period_start"], previous["period_end"]), ("2026-06-29", "2026-07-05"))
        self.assertEqual(model["kpis"]["active_days"], 2)
        self.assertEqual(model["kpis"]["possible_days"], 7)
        self.assertNotIn("completion_percent", model["kpis"])
        self.assertEqual(model["kpis"]["total_sessions"], 4)
        self.assertEqual(model["kpis"]["total_seconds"], 900)
        self.assertEqual(model["kpis"]["comparison"]["label"], "+300% compared with last week")
        self.assertNotIn("activity", model)

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
        self.assertEqual((meditation["type_label"], meditation["display_value"]), ("Time", "10 min"))
        self.assertNotIn("progress_percent", meditation)
        self.assertEqual(len(model["heatmap"]["cells"]), 84)
        self.assertEqual(model["heatmap"]["weeks"], 12)
        self.assertTrue(all(0 <= cell["level"] <= 5 for cell in model["heatmap"]["cells"]))
        self.assertTrue(model["insights"])
        self.assertTrue(all(item["text"] and item["kind"] in ("calendar", "trend", "consistency", "record", "milestone")
                            for item in model["insights"]))
        self.assertIn("week", meditation["comparisons"])
        self.assertIn("month", meditation["comparisons"])
        model["habits"][0]["comparisons"] = {
            "week": {"display": "+4%", "tone": "up"},
            "month": {"display": "-7%", "tone": "down"},
        }

        rendered = render_statistics_dashboard(model)
        model["habits"][0]["current_streak"] = 1
        singular_rendered = render_statistics_dashboard(model)
        self.assertIn("1-day streak", singular_rendered)
        self.assertNotIn("1 days streak", singular_rendered)
        for marker in ('class="workspace-brand"', 'Your statistics', 'Time activity', 'Your habits',
                       'Activity over the last 12 weeks', 'Insights', 'period-switcher', 'habit-performance',
                       'id="time-chart"', 'data-chart-type="bar"', 'data-chart-type="line"',
                       'aria-label="Select time-based habits"'):
            self.assertIn(marker, rendered)
        self.assertNotIn('class="app-sidebar"', rendered)
        self.assertIn('href="/?period=month&amp;offset=0"', rendered)
        self.assertIn('aria-label="Previous period"', rendered)
        self.assertIn('momentum-card', rendered)
        self.assertNotIn('mål', rendered.lower())
        for swedish_ui in (
            "Din statistik", "Vecka", "Månad", "All tid", "aktiva dagar", "loggar",
            "Tidsaktivitet", "Dina vanor", "Insikter", "Föregående period", "Nästa period",
        ):
            self.assertNotIn(swedish_ui, rendered)
        self.assertIn('comparison-pair', rendered)
        self.assertIn('>W: <', rendered)
        self.assertIn('>M: <', rendered)
        self.assertIn('class="compare-up">+4%</em>', rendered)
        self.assertIn('class="compare-down">-7%</em>', rendered)
        self.assertNotIn('<span>Typ</span>', rendered)
        self.assertIn('class="habit-streak" title="0-day streak">0</span>', rendered)
        self.assertNotIn('class="stack-count"', rendered)
        self.assertNotIn("https://", rendered)
        model["insights"] = [{"kind": "record", "text": "New record: 12 min meditation"}]
        record_rendered = render_statistics_dashboard(model)
        self.assertIn('class="record-insight"', record_rendered)
        self.assertIn("New record: 12 min meditation", record_rendered)

    def test_reference_overview_supports_month_year_all_and_rejects_future_offsets(self):
        month = build_statistics_overview(self.database, "month", 0, self.epoch("2024-02-29T12:00:00"))
        year = build_statistics_overview(self.database, "year", 0, self.epoch("2024-02-29T12:00:00"))
        all_time = build_statistics_overview(self.database, "all", 0, self.epoch("2024-02-29T12:00:00"))
        self.assertEqual((month["period_start"], month["period_end"]),
                         ("2024-02-01", "2024-02-29"))
        self.assertEqual((year["period_start"], year["period_end"]),
                         ("2024-01-01", "2024-12-31"))
        self.assertNotIn("activity", month)
        self.assertNotIn("activity", year)
        self.assertEqual(all_time["period_label"], "All saved history")
        with self.assertRaises(ValueError):
            build_statistics_overview(self.database, "week", 1, self.epoch("2026-07-12T12:00:00"))
        with self.assertRaises(ValueError):
            build_statistics_overview(self.database, "decade", 0, self.epoch("2026-07-12T12:00:00"))

    def test_intelligence_uses_same_elapsed_week_and_month_cutoffs(self):
        self.add_habit(1, "STA", "STADA", "time", default_minutes=10)
        self.add(100, 0, "count", "2026-07-06T08:00:00", count=2)
        self.add(101, 0, "count", "2026-07-12T10:00:00", count=4)
        self.add(102, 1, "time", "2026-07-11T10:00:00", duration=600)
        self.add(103, 0, "count", "2026-07-05T10:00:00", count=4)
        self.add(104, 2, "count", "2026-07-05T13:00:00", count=100)
        self.add(105, 1, "time", "2026-07-04T10:00:00", duration=300)
        self.add(106, 0, "count", "2026-06-01T08:00:00", count=6)
        self.add(107, 0, "count", "2026-06-12T10:00:00", count=6)
        self.add(108, 0, "count", "2026-06-12T13:00:00", count=100)
        self.add(109, 1, "time", "2026-06-10T10:00:00", duration=1200)

        model = build_dashboard_intelligence(self.database, self.epoch("2026-07-12T12:00:00"))
        count = next(item for item in model["habit_comparisons"] if item["id"] == 0)
        timed = next(item for item in model["habit_comparisons"] if item["id"] == 1)

        self.assertEqual(count["week"], {"current": 6, "previous": 4, "percent": 50, "display": "+50%", "tone": "up"})
        self.assertEqual(count["month"], {"current": 10, "previous": 12, "percent": -17, "display": "-17%", "tone": "down"})
        self.assertEqual(timed["week"]["display"], "+100%")
        self.assertEqual(timed["month"]["display"], "-25%")
        self.assertEqual(model["cutoffs"]["week"]["current_end"], self.epoch("2026-07-12T12:00:00"))
        self.assertEqual(model["cutoffs"]["week"]["previous_end"], self.epoch("2026-07-05T12:00:00"))

    def test_intelligence_preserves_local_wall_clock_across_dst(self):
        model = build_dashboard_intelligence(self.database, self.epoch("2026-04-05T12:00:00"))
        self.assertEqual(model["cutoffs"]["week"]["previous_end"], self.epoch("2026-03-29T12:00:00"))
        self.assertEqual(model["cutoffs"]["month"]["previous_end"], self.epoch("2026-03-05T12:00:00"))

    def test_intelligence_builds_momentum_records_and_relevant_milestone(self):
        self.add_habit(1, "MED", "MEDITATION", "time", default_minutes=10)
        self.add(120, 0, "count", "2026-06-22T08:00:00", count=3)
        self.add(121, 0, "count", "2026-06-23T08:00:00", count=1)
        self.add(122, 1, "time", "2026-06-22T09:00:00", duration=600)
        self.add(123, 1, "time", "2026-06-23T09:00:00", duration=300)
        self.add(124, 0, "count", "2026-06-29T08:00:00", count=1)
        self.add(125, 0, "count", "2026-07-06T08:00:00", count=4)
        self.add(126, 1, "time", "2026-07-07T09:00:00", duration=720)
        self.add(127, 0, "count", "2026-07-08T08:00:00", count=1)

        model = build_dashboard_intelligence(self.database, self.epoch("2026-07-08T12:00:00"))

        self.assertEqual(model["momentum"]["label"], "Trending up")
        self.assertIn("increased", model["momentum"]["detail"])
        records = model["personal_records"]
        self.assertEqual(records["longest_streak"]["value"], 2)
        self.assertEqual(records["best_week"]["value"], 4)
        self.assertEqual(records["most_count_day"]["value"], 4)
        self.assertEqual(records["longest_time_session"]["value"], 720)
        self.assertEqual(records["most_total_time_week"]["value"], 900)
        self.assertIn("longest_time_session", {item["kind"] for item in model["new_records"]})
        self.assertTrue(model["record_insight"]["text"].startswith("New record:"))
        self.assertEqual(model["milestone"]["remaining"], 181)
        self.assertIn("3 min 1 sec left to beat your personal best", model["milestone"]["text"])

    def test_intelligence_resets_baseline_when_slot_type_changes(self):
        self.add(140, 0, "count", "2026-07-05T10:00:00", count=2)
        self.change_habit(0, "MED", "MEDITATION", "time", default_minutes=10,
                          valid_from=self.epoch("2026-07-06T05:00:00"))
        self.add(141, 0, "time", "2026-07-12T10:00:00", duration=600)

        model = build_dashboard_intelligence(self.database, self.epoch("2026-07-12T12:00:00"))
        habit = next(item for item in model["habit_comparisons"] if item["id"] == 0)
        self.assertEqual(habit["week"], {"current": 600, "previous": 0, "percent": None,
                                         "display": "New", "tone": "up"})
        self.assertIsNone(model["milestone"])

    def test_intelligence_resets_baseline_when_slot_identity_changes_with_same_type(self):
        self.add(142, 0, "count", "2026-07-05T10:00:00", count=8)
        self.change_habit(0, "RUN", "LOPNING", "count", valid_from=self.epoch("2026-07-06T05:00:00"))
        self.add(143, 0, "count", "2026-07-12T10:00:00", count=3)
        model = build_dashboard_intelligence(self.database, self.epoch("2026-07-12T12:00:00"))
        habit = next(item for item in model["habit_comparisons"] if item["id"] == 0)
        self.assertEqual((habit["week"]["current"], habit["week"]["previous"], habit["week"]["display"]),
                         (3, 0, "New"))

    def test_future_events_are_excluded_consistently_from_overview(self):
        self.add(150, 0, "count", "2026-07-12T15:00:00", count=3)
        self.add(151, 0, "count", "2026-07-12T16:00:00", count=9, deleted=True)
        model = build_statistics_overview(self.database, "week", 0, self.epoch("2026-07-12T12:00:00"))
        habit = next(item for item in model["habits"] if item["id"] == 0)
        self.assertEqual(habit["sessions"], 0)
        self.assertEqual(habit["display_value"], "0 times")
        self.assertEqual(model["kpis"]["active_days"], 0)
        self.assertTrue(all(cell["value"] == 0 for cell in model["heatmap"]["cells"]))

    def test_declining_week_uses_truthful_neutral_momentum(self):
        self.add(160, 0, "count", "2026-06-29T08:00:00", count=1)
        self.add(161, 0, "count", "2026-06-30T08:00:00", count=1)
        self.add(162, 0, "count", "2026-07-01T08:00:00", count=1)
        self.add(163, 0, "count", "2026-07-06T08:00:00", count=1)
        model = build_dashboard_intelligence(self.database, self.epoch("2026-07-08T12:00:00"))
        self.assertEqual(model["momentum"]["label"], "No positive trend yet")
        self.assertIn("2 fewer logs", model["momentum"]["detail"])

    def test_inactive_habits_do_not_drive_current_intelligence(self):
        self.add(170, 0, "count", "2026-06-22T08:00:00", count=3)
        self.add(171, 0, "count", "2026-07-06T08:00:00", count=4)
        with open_store(self.database) as connection, connection:
            connection.execute("UPDATE habits SET active=0 WHERE slot_id=0")
        model = build_dashboard_intelligence(self.database, self.epoch("2026-07-06T12:00:00"))
        self.assertEqual(model["habit_comparisons"], [])
        self.assertEqual(model["new_records"], [])
        self.assertIsNone(model["record_insight"])
        self.assertIsNone(model["milestone"])

    def test_milestone_requires_beating_not_tying_previous_best(self):
        self.add_habit(1, "MED", "MEDITATION", "time", default_minutes=10)
        self.add(180, 1, "time", "2026-06-22T09:00:00", duration=900)
        self.add(181, 1, "time", "2026-07-06T09:00:00", duration=720)
        model = build_dashboard_intelligence(self.database, self.epoch("2026-07-06T12:00:00"))
        self.assertEqual(model["milestone"]["remaining"], 181)
        self.assertIn("3 min 1 sec left", model["milestone"]["text"])

    def test_noncurrent_views_do_not_mix_in_current_week_intelligence(self):
        self.add(190, 0, "count", "2026-07-06T08:00:00", count=4)
        previous_week = build_statistics_overview(self.database, "week", -1, self.epoch("2026-07-08T12:00:00"))
        month = build_statistics_overview(self.database, "month", 0, self.epoch("2026-07-08T12:00:00"))
        year = build_statistics_overview(self.database, "year", 0, self.epoch("2026-07-08T12:00:00"))
        all_time = build_statistics_overview(self.database, "all", 0, self.epoch("2026-07-08T12:00:00"))
        for model in (previous_week, month, year, all_time):
            self.assertEqual(model["kpis"]["momentum"]["kind"], "selected-period")
            self.assertFalse(any(item["kind"] in ("record", "milestone") for item in model["insights"]))

    def test_intelligence_requires_a_prior_baseline_before_announcing_record(self):
        self.add(130, 0, "count", "2026-07-06T08:00:00", count=1)
        model = build_dashboard_intelligence(self.database, self.epoch("2026-07-06T12:00:00"))
        self.assertEqual(model["new_records"], [])
        self.assertIsNone(model["record_insight"])
        self.assertIsNone(model["milestone"])


class DashboardRenderTest(unittest.TestCase):
    def test_render_is_semantic_local_responsive_and_accessible(self):
        model = {
            "generated_at": "July 12, 2026 12:00",
            "metadata_status": "synced",
            "comparisons": {
                "week": {"current": 3, "previous": 2, "percent": 50, "tone": "up", "label": "+50% compared with last week"},
                "month": {"current": 3, "previous": 0, "percent": None, "tone": "up", "label": "New activity this month"},
            },
            "summary": {"today": 2, "week": 3, "minutes": 2, "streak": 2},
            "days": [{"label": label, "value": index, "height": index * 10} for index, label in enumerate("MTWTFSS")],
            "habits": [{"id": 0, "name": "MEDITATION", "code": "MED", "total": 3, "minutes": 0,
                        "display_value": 3, "display_unit": "times"}],
            "recent": [{"id": 1, "name": "MEDITATION", "kind": "2 times", "when": "Today 08:00"}],
        }

        html = render_dashboard(model)

        for marker in ("<main", "<header", "<section", "aria-label=", "TickStone", "Recent activity"):
            self.assertIn(marker, html)
        self.assertIn('/assets/styles.css', html)
        self.assertIn('/assets/app.js', html)
        self.assertIn('+50% compared with last week', html)
        self.assertIn('id="timeline-chart"', html)
        self.assertIn('data-range="week"', html)
        self.assertIn('aria-label="Select habits in the line chart"', html)
        self.assertNotIn('https://', html)
        self.assertNotIn('http://', html)

        css = (ROOT / "tools" / "tickstone_dashboard_web" / "styles.css").read_text()
        self.assertIn("@media (max-width: 720px)", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn(":focus-visible", css)
        self.assertIn("overflow-x: hidden", css)
        self.assertIn("38px minmax(82px,1.2fr) minmax(48px,.6fr)", css)
        self.assertIn("grid-template-columns: repeat(12,minmax(0,1fr))", css)
        self.assertIn("--paper: #f4f2ed", css)
        self.assertIn("width: min(1800px", css)
        self.assertIn(".record-insight", css)
        self.assertIn("@keyframes record-accent", css)
        self.assertIn("--heat-row: clamp(12px", css)
        self.assertGreaterEqual(css.count("grid-template-rows: repeat(7,var(--heat-row))"), 2)
        self.assertIn("--stat-height: clamp(72px", css)
        self.assertIn(".time-activity-card .chart-loading { min-height: var(--chart-height)", css)
        self.assertIn("@media (min-width: 761px)", css)
        self.assertIn("grid-template-columns: repeat(4,minmax(0,1fr))", css)
        self.assertIn("--chart-height: clamp(150px", css)
        self.assertIn("--heat-row: clamp(12px", css)
        symmetric_columns = "grid-template-columns: minmax(0,1.7fr) minmax(390px,.9fr)"
        self.assertGreaterEqual(css.count(symmetric_columns), 2)
        self.assertIn("30px minmax(76px,1fr) minmax(70px,.75fr) 38px 74px 14px", css)
        script = (ROOT / "tools" / "tickstone_dashboard_web" / "app.js").read_text()
        self.assertIn("labelStep", script)
        self.assertIn('data.period === "month"', script)
        self.assertIn("getComputedStyle(chart).height", script)
        self.assertIn("Math.min(4, maximum)", script)
        self.assertIn("tickCount", script)

    def test_detail_render_escapes_metadata_and_has_period_navigation(self):
        model = {"habit": {"id": 0, "code": "<X", "name": "<script>", "type": "count"},
                 "period": "week", "period_start": "2026-07-06", "period_end": "2026-07-12",
                 "metadata_status": "synced", "display_value": "2", "display_unit": "times",
                 "active_days": 1, "average_value": "2", "average_unit": "times",
                 "longest_streak": 1, "current_streak": 0, "sessions": 1, "trend": None,
                 "best_day": "2026-07-07", "best_period": "2026-07-07",
                 "points": [{"label": "2026-07-07", "value": 2, "height": 100}]}
        rendered = render_habit_detail(model)
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;Script&gt;", rendered)
        self.assertIn('/habit/0?period=month', rendered)
        self.assertIn('aria-current=page', rendered)
        self.assertIn('statistics-app', rendered)
        self.assertNotIn('class="app-sidebar"', rendered)
        self.assertIn('class="workspace-brand"', rendered)
        self.assertIn('rich-detail-workspace', rendered)
        self.assertIn('id="detail-chart"', rendered)
        self.assertIn('data-detail-chart-type="bar"', rendered)
        self.assertIn('data-detail-chart-type="line"', rendered)
        self.assertIn('data-chart-mode="day"', rendered)
        self.assertIn('data-chart-mode="week"', rendered)
        self.assertIn('data-chart-mode="month"', rendered)
        self.assertIn('data-y-label="Occurrences"', rendered)
        self.assertIn('data-chart-modes=', rendered)
        self.assertIn('Personal bests', rendered)
        self.assertIn('Weekly change', rendered)
        self.assertIn('Best week', rendered)
        self.assertIn('Quietest active week', rendered)
        self.assertIn('Your patterns', rendered)
        self.assertIn('habit-calendar-grid', rendered)
        self.assertIn('Recent logs', rendered)
        self.assertNotIn('veckomålet', rendered)
        self.assertNotIn('måluppfyllelse', rendered.lower())
        self.assertIn('/assets/detail-chart.js', rendered)
        detail_script = (ROOT / "tools" / "tickstone_dashboard_web" / "detail-chart.js").read_text()
        self.assertIn("Math.min(4, Math.floor(maximum))", detail_script)
        self.assertNotIn("} st`", detail_script)
        self.assertIn('count === 1 ? "time" : "times"', detail_script)
        for swedish_ui in (
            "Personliga rekord", "Dina mönster", "Senaste loggar", "Välj en dag",
            "Tillfällen", "Tidsupplösning", "Stapeldiagram", "sessioner", "skrivskyddad",
        ):
            self.assertNotIn(swedish_ui, rendered + detail_script)
        self.assertIn('<html lang="en">', rendered)


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
                                   ("/assets/app.js", "text/javascript"),
                                   ("/assets/detail-chart.js", "text/javascript")):
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
        self.assertIn(b"Your statistics", body)
        self.assertEqual(self.request("GET", "/?period=decade")[0], 400)
        self.assertEqual(self.request("GET", "/?period=week&offset=1")[0], 400)
        self.assertEqual(self.request("GET", "/?period=week&offset=not-a-number")[0], 400)
        self.assertEqual((self.database.stat().st_mtime_ns, self.database.stat().st_size), before)

    def test_time_chart_api_is_bounded_read_only_and_ignores_count_series(self):
        before = (self.database.stat().st_mtime_ns, self.database.stat().st_size)
        status, headers, body = self.request("GET", "/api/time-chart?period=week&offset=0")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        payload = json.loads(body)
        self.assertEqual(payload["unit"], "seconds")
        self.assertEqual(payload["series"], [])
        self.assertEqual(self.request("GET", "/api/time-chart?period=week&offset=1")[0], 400)
        self.assertEqual(self.request("GET", "/api/time-chart?period=decade&offset=0")[0], 400)
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
