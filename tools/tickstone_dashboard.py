#!/usr/bin/env python3
"""Read-only local web dashboard for TickStone history."""

import argparse
import html
import json
import re
import sqlite3
from contextlib import contextmanager
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

WEB_ROOT = Path(__file__).with_name("tickstone_dashboard_web")
STOCKHOLM = ZoneInfo("Europe/Stockholm")
SWEDISH_MONTHS = ("januari", "februari", "mars", "april", "maj", "juni", "juli",
                  "augusti", "september", "oktober", "november", "december")
DAY_LABELS = ("M", "T", "O", "T", "F", "L", "S")
PERIODS = ("week", "month", "year", "all")
TIMELINE_RANGES = ("week", "month", "year")
SERIES_COLORS = ("#496d55", "#b06f4f", "#5f7296", "#92705f", "#7a6f9b",
                 "#4f8581", "#b28a3f", "#7d8550", "#965e6d", "#66717a")


@contextmanager
def _readonly_connection(database):
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA foreign_keys=ON")
        yield connection
    finally:
        connection.close()


def _today(now_epoch):
    now = datetime.fromtimestamp(now_epoch, timezone.utc).astimezone(STOCKHOLM)
    return now, (now - timedelta(hours=5)).date()


def _format_when(epoch, today):
    local = datetime.fromtimestamp(epoch, timezone.utc).astimezone(STOCKHOLM)
    prefix = "Idag" if local.date() == today else "Igår" if local.date() == today - timedelta(days=1) \
        else f"{local.day} {SWEDISH_MONTHS[local.month - 1][:3]}"
    return f"{prefix} {local:%H:%M}"


def _format_value(value, kind):
    if kind == "count":
        return value, "gång" if value == 1 else "gånger"
    if value < 60:
        return value, "sekunder"
    if value < 3600:
        minutes = round(value / 60)
        return minutes, "minut" if minutes == 1 else "minuter"
    hours = value // 3600
    minutes = (value % 3600) // 60
    return f"{hours}h {minutes}m" if minutes else f"{hours}h", "tid"


def _metadata_status(connection):
    known = connection.execute(
        "SELECT 1 FROM habit_snapshots WHERE protocol_version>0 LIMIT 1"
    ).fetchone()
    if not known:
        return "legacy"
    uncertain = connection.execute(
        "SELECT 1 FROM events WHERE config_snapshot_id IS NULL LIMIT 1"
    ).fetchone()
    return "mixed" if uncertain else "synced"


def _calendar_comparison_bounds(today, period):
    if period == "week":
        current_start = today - timedelta(days=today.weekday())
        current_end = current_start + timedelta(days=7)
        previous_start = current_start - timedelta(days=7)
    elif period == "month":
        current_start = today.replace(day=1)
        current_end = date(current_start.year + (current_start.month == 12),
                           1 if current_start.month == 12 else current_start.month + 1, 1)
        previous_start = date(current_start.year - (current_start.month == 1),
                              12 if current_start.month == 1 else current_start.month - 1, 1)
    else:
        raise ValueError("invalid comparison period")
    return current_start, current_end, previous_start


def _comparison_result(current, previous, period):
    previous_name = "förra veckan" if period == "week" else "förra månaden"
    current_name = "den här veckan" if period == "week" else "den här månaden"
    if previous == 0:
        if current == 0:
            return {"current": current, "previous": previous, "percent": 0, "tone": "flat",
                    "label": f"Samma nivå som {previous_name}"}
        return {"current": current, "previous": previous, "percent": None, "tone": "up",
                "label": f"Ny aktivitet {current_name}"}
    percent = round((current - previous) / previous * 100)
    tone = "up" if percent > 0 else "down" if percent < 0 else "flat"
    prefix = "+" if percent > 0 else ""
    label = f"{prefix}{percent}% jämfört med {previous_name}" if percent else f"Samma nivå som {previous_name}"
    return {"current": current, "previous": previous, "percent": percent, "tone": tone, "label": label}


def _detail_trend_label(current, previous, period):
    if period == "all":
        return "Hela den sparade historiken"
    if period in ("week", "month"):
        return _comparison_result(current, previous, period)["label"]
    if previous == 0:
        return "Ny aktivitet i år" if current else "Samma nivå som förra året"
    percent = round((current - previous) / previous * 100)
    if percent == 0:
        return "Samma nivå som förra året"
    return f'{"+" if percent > 0 else ""}{percent}% jämfört med förra året'


def build_overview_comparisons(database, now_epoch=None):
    now_epoch = int(datetime.now(timezone.utc).timestamp()) if now_epoch is None else int(now_epoch)
    _, today = _today(now_epoch)
    result = {}
    with _readonly_connection(database) as connection:
        for period in ("week", "month"):
            current_start, current_end, previous_start = _calendar_comparison_bounds(today, period)
            row = connection.execute(
                """SELECT
                    SUM(CASE WHEN tickstone_day>=? AND tickstone_day<? THEN 1 ELSE 0 END) AS current_count,
                    SUM(CASE WHEN tickstone_day>=? AND tickstone_day<? THEN 1 ELSE 0 END) AS previous_count
                   FROM events WHERE deleted=0 AND tickstone_day>=? AND tickstone_day<?""",
                (current_start.isoformat(), current_end.isoformat(), previous_start.isoformat(),
                 current_start.isoformat(), previous_start.isoformat(), current_end.isoformat()),
            ).fetchone()
            result[period] = _comparison_result(row["current_count"] or 0, row["previous_count"] or 0, period)
    return result


def build_timeline(database, timeline_range="month", now_epoch=None):
    if timeline_range not in TIMELINE_RANGES:
        raise ValueError("invalid timeline range")
    now_epoch = int(datetime.now(timezone.utc).timestamp()) if now_epoch is None else int(now_epoch)
    _, today = _today(now_epoch)
    if timeline_range == "week":
        start = today - timedelta(days=today.weekday()); end = start + timedelta(days=7)
        labels = [(start + timedelta(days=offset)).isoformat() for offset in range(7)]
        bucket_sql = "tickstone_day"
    elif timeline_range == "month":
        start = today.replace(day=1)
        end = date(start.year + (start.month == 12), 1 if start.month == 12 else start.month + 1, 1)
        labels = []
        cursor = start
        while cursor < end:
            labels.append(cursor.isoformat()); cursor += timedelta(days=1)
        bucket_sql = "tickstone_day"
    else:
        start = date(today.year, 1, 1); end = date(today.year + 1, 1, 1)
        labels = [f"{today.year}-{month:02d}" for month in range(1, 13)]
        bucket_sql = "substr(tickstone_day,1,7)"
    with _readonly_connection(database) as connection:
        identities = connection.execute(
            """SELECT h.slot_id AS id,h.name,h.code FROM habits h WHERE h.active=1
               UNION SELECT e.habit_id,NULL,NULL FROM events e
                WHERE e.deleted=0 AND NOT EXISTS(SELECT 1 FROM habits h WHERE h.slot_id=e.habit_id)
               ORDER BY id"""
        ).fetchall()
        rows = connection.execute(
            f"""SELECT habit_id,{bucket_sql} AS bucket,COUNT(*) AS sessions
                  FROM events WHERE deleted=0 AND tickstone_day>=? AND tickstone_day<?
                 GROUP BY habit_id,bucket ORDER BY habit_id,bucket""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    values = {(row["habit_id"], row["bucket"]): row["sessions"] for row in rows}
    series = [{"id": row["id"], "name": row["name"] or f"Habit {row['id'] + 1}",
               "code": row["code"] or "", "color": SERIES_COLORS[row["id"] % len(SERIES_COLORS)],
               "values": [values.get((row["id"], label), 0) for label in labels]}
              for row in identities]
    return {"range": timeline_range, "labels": labels, "series": series,
            "unit": "aktivitetstillfällen"}


def _shift_month(year, month, delta):
    absolute = year * 12 + month - 1 + delta
    return absolute // 12, absolute % 12 + 1


def _statistics_bounds(today, period, offset, earliest=None):
    if period not in ("week", "month", "year", "all") or type(offset) is not int or offset > 0:
        raise ValueError("invalid period or offset")
    if period == "week":
        start = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
        end = start + timedelta(days=7)
        previous = (start - timedelta(days=7), start)
    elif period == "month":
        year, month = _shift_month(today.year, today.month, offset)
        start = date(year, month, 1)
        next_year, next_month = _shift_month(year, month, 1)
        end = date(next_year, next_month, 1)
        previous_year, previous_month = _shift_month(year, month, -1)
        previous = (date(previous_year, previous_month, 1), start)
    elif period == "year":
        start = date(today.year + offset, 1, 1)
        end = date(start.year + 1, 1, 1)
        previous = (date(start.year - 1, 1, 1), start)
    else:
        if offset != 0:
            raise ValueError("all-time does not support offset")
        start = earliest or today
        end = today + timedelta(days=1)
        previous = (start, start)
    return start, end, previous


def build_time_chart(database, period="week", offset=0, now_epoch=None):
    now_epoch = int(datetime.now(timezone.utc).timestamp()) if now_epoch is None else int(now_epoch)
    _, today = _today(now_epoch)
    with _readonly_connection(database) as connection:
        earliest_row = connection.execute("SELECT MIN(tickstone_day) FROM events WHERE deleted=0 AND type='time'").fetchone()[0]
        earliest = date.fromisoformat(earliest_row) if earliest_row else today
        start, end, _ = _statistics_bounds(today, period, offset, earliest)
        identities = connection.execute(
            """SELECT h.slot_id AS id,h.name,h.code FROM habits h WHERE h.active=1 AND h.type='time'
               UNION SELECT e.habit_id,NULL,NULL FROM events e
                WHERE e.deleted=0 AND e.type='time' AND NOT EXISTS(SELECT 1 FROM habits h WHERE h.slot_id=e.habit_id)
               ORDER BY id"""
        ).fetchall()
        bucket_sql = "substr(tickstone_day,1,7)" if period in ("year", "all") else "tickstone_day"
        rows = connection.execute(
            f"""SELECT habit_id,{bucket_sql} AS bucket,SUM(duration_seconds) AS seconds
                  FROM events WHERE deleted=0 AND type='time' AND tickstone_day>=? AND tickstone_day<?
                 GROUP BY habit_id,bucket ORDER BY habit_id,bucket""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    if period in ("year", "all"):
        labels = []
        cursor = date(start.year, start.month, 1)
        while cursor < end:
            labels.append(f"{cursor.year}-{cursor.month:02d}")
            year, month = _shift_month(cursor.year, cursor.month, 1)
            cursor = date(year, month, 1)
    else:
        labels = []
        cursor = start
        while cursor < end:
            labels.append(cursor.isoformat()); cursor += timedelta(days=1)
    values = {(row["habit_id"], row["bucket"]): int(row["seconds"] or 0) for row in rows}
    series = [{"id": row["id"], "name": row["name"] or f"Habit {row['id'] + 1}",
               "code": row["code"] or "", "color": SERIES_COLORS[row["id"] % len(SERIES_COLORS)],
               "values": [values.get((row["id"], label), 0) for label in labels]}
              for row in identities]
    return {"period": period, "offset": offset, "labels": labels, "series": series,
            "unit": "seconds", "total_seconds": sum(sum(item["values"]) for item in series)}


def _swedish_period_label(start, end, period):
    if period == "week":
        last = end - timedelta(days=1)
        if start.month == last.month:
            return f"{start.day}–{last.day} {SWEDISH_MONTHS[last.month - 1]} {last.year}"
        return f"{start.day} {SWEDISH_MONTHS[start.month - 1][:3]}–{last.day} {SWEDISH_MONTHS[last.month - 1][:3]} {last.year}"
    if period == "month":
        return f"{SWEDISH_MONTHS[start.month - 1].capitalize()} {start.year}"
    if period == "year":
        return str(start.year)
    return "All sparad tid"


def _duration_compact(seconds):
    seconds = int(seconds or 0)
    if seconds < 60:
        return f"{seconds} sek"
    if seconds < 3600:
        return f"{round(seconds / 60)} min"
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    return f"{hours} h {minutes:02d} min" if minutes else f"{hours} h"


def _streak_label(days):
    return "1 dags streak" if days == 1 else f"{days} dagars streak"


def _compact_comparison_label(label):
    if label.startswith("Ny aktivitet"):
        return "Ny"
    if label.startswith("Samma nivå"):
        return "Samma"
    return label.split(" jämfört", 1)[0]


def _period_comparison(current, previous, period):
    if period == "all":
        return {"current": current, "previous": previous, "percent": None, "tone": "flat",
                "label": "Hela historiken", "delta": ""}
    if period in ("week", "month"):
        result = _comparison_result(current, previous, period)
    else:
        if previous == 0:
            result = {"current": current, "previous": previous, "percent": None,
                      "tone": "up" if current else "flat",
                      "label": "Ny aktivitet i år" if current else "Samma nivå som förra året"}
        else:
            percent = round((current - previous) / previous * 100)
            result = {"current": current, "previous": previous, "percent": percent,
                      "tone": "up" if percent > 0 else "down" if percent < 0 else "flat",
                      "label": f'{"+" if percent > 0 else ""}{percent}% jämfört med förra året' if percent else "Samma nivå som förra året"}
    result["delta"] = f'{current - previous:+d} aktivitetstillfällen' if current != previous else "Oförändrat"
    return result


def build_statistics_overview(database, period="week", offset=0, now_epoch=None):
    now_epoch = int(datetime.now(timezone.utc).timestamp()) if now_epoch is None else int(now_epoch)
    now, today = _today(now_epoch)
    with _readonly_connection(database) as connection:
        earliest_row = connection.execute(
            "SELECT MIN(tickstone_day) FROM events WHERE deleted=0"
        ).fetchone()[0]
        earliest = date.fromisoformat(earliest_row) if earliest_row else today
        start, end, previous = _statistics_bounds(today, period, offset, earliest)
        visible_end = min(end, today + timedelta(days=1)) if offset == 0 else end
        possible_days = max(1, (visible_end - start).days)
        identities = connection.execute(
            """SELECT h.slot_id AS id,h.code,h.name,h.type,h.default_minutes
                 FROM habits h WHERE h.active=1
                UNION SELECT e.habit_id,NULL,NULL,MIN(e.type),1 FROM events e
                 WHERE e.deleted=0 AND NOT EXISTS(SELECT 1 FROM habits h WHERE h.slot_id=e.habit_id)
                GROUP BY e.habit_id ORDER BY id"""
        ).fetchall()
        current_rows = connection.execute(
            """SELECT habit_id,tickstone_day,type,COUNT(*) AS sessions,
                      COALESCE(SUM(CASE WHEN type='count' THEN count ELSE 0 END),0) AS count_total,
                      COALESCE(SUM(CASE WHEN type='time' THEN duration_seconds ELSE 0 END),0) AS seconds
                 FROM events WHERE deleted=0 AND tickstone_day>=? AND tickstone_day<?
                GROUP BY habit_id,tickstone_day,type ORDER BY tickstone_day,habit_id""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        previous_rows = connection.execute(
            """SELECT habit_id,type,COUNT(*) AS sessions,
                      COALESCE(SUM(CASE WHEN type='count' THEN count ELSE 0 END),0) AS count_total,
                      COALESCE(SUM(CASE WHEN type='time' THEN duration_seconds ELSE 0 END),0) AS seconds
                 FROM events WHERE deleted=0 AND tickstone_day>=? AND tickstone_day<?
                GROUP BY habit_id,type""", (previous[0].isoformat(), previous[1].isoformat()),
        ).fetchall()
        heat_end = min(end - timedelta(days=1), today)
        heat_end += timedelta(days=6 - heat_end.weekday())
        heat_start = heat_end - timedelta(days=83)
        heat_rows = connection.execute(
            """SELECT tickstone_day,COUNT(*) AS sessions FROM events
                WHERE deleted=0 AND tickstone_day>=? AND tickstone_day<=? GROUP BY tickstone_day""",
            (heat_start.isoformat(), heat_end.isoformat()),
        ).fetchall()
        streak_rows = connection.execute(
            "SELECT habit_id,tickstone_day FROM events WHERE deleted=0 GROUP BY habit_id,tickstone_day ORDER BY habit_id,tickstone_day"
        ).fetchall()
        metadata_status = _metadata_status(connection)

    identity_by_id = {row["id"]: row for row in identities}
    current_by_day_habit = {(row["tickstone_day"], row["habit_id"]): row for row in current_rows}
    current_sessions = sum(row["sessions"] for row in current_rows)
    previous_sessions = sum(row["sessions"] for row in previous_rows)
    active_days = len({row["tickstone_day"] for row in current_rows})
    total_seconds = sum(row["seconds"] for row in current_rows)
    count_ids = [row["id"] for row in identities if row["type"] == "count"]
    time_ids = [row["id"] for row in identities if row["type"] == "time"]

    achieved = 0.0
    for day_offset in range(possible_days):
        day_string = (start + timedelta(days=day_offset)).isoformat()
        for identity in identities:
            row = current_by_day_habit.get((day_string, identity["id"]))
            raw = 0 if not row else row["count_total"] if identity["type"] == "count" else row["seconds"]
            target = 1 if identity["type"] == "count" else max(60, (identity["default_minutes"] or 1) * 60)
            achieved += min(1, raw / target)
    possible_targets = possible_days * len(identities)
    completion_percent = round(achieved / possible_targets * 100) if possible_targets else 0

    def daily_percent(day_string, ids):
        if not ids:
            return 0
        total = 0.0
        for habit_id in ids:
            identity = identity_by_id[habit_id]
            row = current_by_day_habit.get((day_string, habit_id))
            raw = 0 if not row else row["count_total"] if identity["type"] == "count" else row["seconds"]
            target = 1 if identity["type"] == "count" else max(60, (identity["default_minutes"] or 1) * 60)
            total += min(1, raw / target)
        return round(total / len(ids) * 100)

    daily_activity = []
    cursor = start
    while cursor < end:
        key = cursor.isoformat()
        daily_activity.append({"date": key, "label": DAY_LABELS[cursor.weekday()],
                               "count_percent": daily_percent(key, count_ids),
                               "time_percent": daily_percent(key, time_ids)})
        cursor += timedelta(days=1)
    if period in ("year", "all"):
        grouped = {}
        for item in daily_activity:
            month_key = item["date"][:7]
            bucket = grouped.setdefault(month_key, {"count": [], "time": []})
            bucket["count"].append(item["count_percent"]); bucket["time"].append(item["time_percent"])
        activity = [{"date": key, "label": SWEDISH_MONTHS[int(key[-2:]) - 1][:3].capitalize(),
                     "count_percent": round(sum(values["count"]) / len(values["count"])),
                     "time_percent": round(sum(values["time"]) / len(values["time"]))}
                    for key, values in sorted(grouped.items())]
    else:
        activity = daily_activity

    previous_by_habit = {row["habit_id"]: row for row in previous_rows}
    streak_by_habit = defaultdict(list)
    for row in streak_rows:
        streak_by_habit[row["habit_id"]].append(row["tickstone_day"])
    habits = []
    for identity in identities:
        rows = [row for row in current_rows if row["habit_id"] == identity["id"]]
        sessions = sum(row["sessions"] for row in rows)
        raw_value = sum(row["count_total"] if identity["type"] == "count" else row["seconds"] for row in rows)
        target = 1 if identity["type"] == "count" else max(60, (identity["default_minutes"] or 1) * 60)
        normalized = sum(min(1, (row["count_total"] if identity["type"] == "count" else row["seconds"]) / target) for row in rows)
        progress = round(normalized / possible_days * 100)
        previous_row = previous_by_habit.get(identity["id"])
        previous_value = 0 if not previous_row else previous_row["count_total"] if identity["type"] == "count" else previous_row["seconds"]
        comparison = _period_comparison(raw_value, previous_value, period)
        current_streak, longest_streak = _longest_streak(streak_by_habit[identity["id"]], today)
        display_value = f"{raw_value} {'gång' if raw_value == 1 else 'gånger'}" if identity["type"] == "count" else _duration_compact(raw_value)
        habits.append({"id": identity["id"], "code": identity["code"] or "",
                       "name": identity["name"] or f"Habit {identity['id'] + 1}",
                       "type": identity["type"], "type_label": "Tillfällen" if identity["type"] == "count" else "Tid",
                       "sessions": sessions, "display_value": display_value,
                       "progress_percent": progress, "current_streak": current_streak,
                       "longest_streak": longest_streak, "comparison": comparison,
                       "color": SERIES_COLORS[identity["id"] % len(SERIES_COLORS)]})

    heat_values = {row["tickstone_day"]: row["sessions"] for row in heat_rows}
    heat_peak = max(heat_values.values(), default=1)
    heat_cells = []
    cursor = heat_start
    while cursor <= heat_end:
        value = heat_values.get(cursor.isoformat(), 0)
        level = 0 if value == 0 else max(1, min(5, round(value / heat_peak * 5)))
        heat_cells.append({"date": cursor.isoformat(), "value": value, "level": level,
                           "weekday": cursor.weekday(), "future": cursor > today})
        cursor += timedelta(days=1)

    weekday_counts = defaultdict(int)
    for row in current_rows:
        weekday_counts[date.fromisoformat(row["tickstone_day"]).weekday()] += row["sessions"]
    insights = []
    if weekday_counts:
        best_weekday = max(weekday_counts, key=lambda key: (weekday_counts[key], -key))
        weekday_names = ("måndagar", "tisdagar", "onsdagar", "torsdagar", "fredagar", "lördagar", "söndagar")
        insights.append({"kind": "calendar", "text": f"Du är mest konsekvent på {weekday_names[best_weekday]}."})
    strongest = max(habits, key=lambda row: row["progress_percent"], default=None)
    if strongest and strongest["sessions"]:
        insights.append({"kind": "consistency", "text": f"{strongest['name'].title()} leder perioden med {strongest['progress_percent']}% av målet."})
    if not insights:
        insights.append({"kind": "trend", "text": "Logga några aktiviteter för att låsa upp personliga insikter."})

    previous_offset = offset - 1 if period != "all" else None
    next_offset = offset + 1 if period != "all" and offset < 0 else None
    return {"generated_at": f"{now:%Y-%m-%d %H:%M}", "period": period, "offset": offset,
            "period_start": start.isoformat(), "period_end": (end - timedelta(days=1)).isoformat(),
            "period_label": _swedish_period_label(start, end, period),
            "navigation": {"previous_offset": previous_offset, "next_offset": next_offset},
            "metadata_status": metadata_status,
            "kpis": {"active_days": active_days, "possible_days": possible_days,
                     "completion_percent": completion_percent, "total_seconds": total_seconds,
                     "comparison": _period_comparison(current_sessions, previous_sessions, period)},
            "activity": activity, "habits": habits,
            "heatmap": {"weeks": 12, "start": heat_start.isoformat(), "end": heat_end.isoformat(),
                        "cells": heat_cells},
            "insights": insights}


def build_dashboard(database, now_epoch=None):
    now_epoch = int(datetime.now(timezone.utc).timestamp()) if now_epoch is None else int(now_epoch)
    now, today = _today(now_epoch)
    first_day = today - timedelta(days=6)
    with _readonly_connection(database) as connection:
        daily_rows = connection.execute(
            """SELECT tickstone_day, COUNT(*) AS events,
                      SUM(CASE WHEN type='time' THEN duration_seconds ELSE 0 END) AS seconds
                 FROM events WHERE deleted=0 AND tickstone_day BETWEEN ? AND ?
                GROUP BY tickstone_day""", (first_day.isoformat(), today.isoformat())
        ).fetchall()
        aggregate = {row["tickstone_day"]: row for row in daily_rows}
        habits_rows = connection.execute(
            """SELECT h.slot_id AS habit_id, h.code, h.name, COALESCE(h.type,MIN(e.type)) AS type,
                      COUNT(e.id) AS sessions,
                      COALESCE(SUM(CASE WHEN e.type='count' THEN e.count ELSE 0 END),0) AS count_total,
                      COALESCE(SUM(CASE WHEN e.type='time' THEN e.duration_seconds ELSE 0 END),0) AS seconds
                 FROM habits h LEFT JOIN events e ON e.habit_id=h.slot_id AND e.deleted=0
                WHERE h.active=1 GROUP BY h.slot_id
                UNION ALL
               SELECT e.habit_id, NULL, NULL, MIN(e.type), COUNT(e.id),
                      SUM(CASE WHEN e.type='count' THEN e.count ELSE 0 END),
                      SUM(CASE WHEN e.type='time' THEN e.duration_seconds ELSE 0 END)
                 FROM events e LEFT JOIN habits h ON h.slot_id=e.habit_id
                WHERE e.deleted=0 AND h.slot_id IS NULL GROUP BY e.habit_id"""
        ).fetchall()
        recent_rows = connection.execute(
            """SELECT e.id, e.habit_id, e.type, e.started_at, e.duration_seconds, e.count,
                      COALESCE(se.code,h.code) AS code, COALESCE(se.name,h.name) AS name,
                      CASE WHEN se.name IS NOT NULL THEN 'exact'
                           WHEN h.name IS NOT NULL THEN 'fallback' ELSE 'missing' END AS metadata_status
                 FROM events e
                 LEFT JOIN habit_snapshot_entries se
                   ON se.snapshot_id=e.config_snapshot_id AND se.slot_id=e.habit_id AND se.active=1
                 LEFT JOIN habits h ON h.slot_id=e.habit_id
                WHERE e.deleted=0 ORDER BY e.started_at DESC,e.id DESC LIMIT 8"""
        ).fetchall()
        metadata_status = _metadata_status(connection)

    peak = max((row["events"] for row in daily_rows), default=1)
    days = []
    for offset in range(7):
        current = first_day + timedelta(days=offset)
        value = aggregate.get(current.isoformat(), {"events": 0})["events"]
        days.append({"date": current.isoformat(), "label": DAY_LABELS[current.weekday()],
                     "value": value, "height": 8 if not value else max(22, round(value / peak * 100)),
                     "today": current == today})
    habits = []
    for row in habits_rows:
        kind = row["type"] or "count"
        value = row["count_total"] if kind == "count" else row["seconds"]
        display, unit = _format_value(value, kind)
        habits.append({"id": row["habit_id"], "name": row["name"] or f"Habit {row['habit_id'] + 1}",
                       "code": row["code"] or "", "type": kind, "sessions": row["sessions"],
                       "total": row["count_total"], "seconds": row["seconds"],
                       "minutes": round(row["seconds"] / 60), "display_value": display,
                       "display_unit": unit})
    habits.sort(key=lambda item: (-item["sessions"], item["id"]))
    active_days = {key for key, row in aggregate.items() if row["events"]}
    streak = 0
    cursor = today
    while cursor.isoformat() in active_days:
        streak += 1
        cursor -= timedelta(days=1)
    recent = []
    for row in recent_rows:
        value = row["count"] if row["type"] == "count" else row["duration_seconds"]
        shown, unit = _format_value(value, row["type"])
        recent.append({"id": row["id"], "habit_id": row["habit_id"],
                       "name": row["name"] or f"Habit {row['habit_id'] + 1}",
                       "kind": f"{shown} {unit}", "when": _format_when(row["started_at"], now.date()),
                       "metadata_status": row["metadata_status"]})
    week_events = sum(row["events"] for row in daily_rows)
    week_seconds = sum(row["seconds"] for row in daily_rows)
    comparisons = build_overview_comparisons(database, now_epoch)
    return {"generated_at": f"{now.day} {SWEDISH_MONTHS[now.month - 1]} {now:%Y %H:%M}",
            "metadata_status": metadata_status, "comparisons": comparisons,
            "summary": {"today": aggregate.get(today.isoformat(), {"events": 0})["events"],
                        "week": week_events, "minutes": round(week_seconds / 60), "streak": streak},
            "days": days, "habits": habits, "recent": recent}


def _period_bounds(today, period):
    if period == "week":
        start = today - timedelta(days=today.weekday()); end = start + timedelta(days=7)
        previous = (start - timedelta(days=7), start)
    elif period == "month":
        start = today.replace(day=1)
        end = date(start.year + (start.month == 12), 1 if start.month == 12 else start.month + 1, 1)
        previous_start = date(start.year - (start.month == 1), 12 if start.month == 1 else start.month - 1, 1)
        previous = (previous_start, start)
    elif period == "year":
        start = date(today.year, 1, 1); end = date(today.year + 1, 1, 1)
        previous = (date(today.year - 1, 1, 1), start)
    else:
        start = date(1970, 1, 1); end = today + timedelta(days=1); previous = (start, start)
    return start, end, previous


def _longest_streak(day_strings, today):
    days = sorted({date.fromisoformat(value) for value in day_strings})
    longest = run = 0
    previous = None
    for current in days:
        run = run + 1 if previous and current == previous + timedelta(days=1) else 1
        longest = max(longest, run); previous = current
    current_run = 0; cursor = today
    known = set(days)
    if cursor not in known and cursor - timedelta(days=1) in known:
        cursor -= timedelta(days=1)
    while cursor in known:
        current_run += 1; cursor -= timedelta(days=1)
    return current_run, longest


def build_habit_detail(database, habit_id, period="week", now_epoch=None):
    if type(habit_id) is not int or not 0 <= habit_id <= 9 or period not in PERIODS:
        raise ValueError("invalid habit or period")
    now_epoch = int(datetime.now(timezone.utc).timestamp()) if now_epoch is None else int(now_epoch)
    now, today = _today(now_epoch)
    start, end, previous = _period_bounds(today, period)
    with _readonly_connection(database) as connection:
        habit = connection.execute(
            "SELECT slot_id,code,name,type,current_snapshot_id FROM habits WHERE slot_id=?", (habit_id,)
        ).fetchone()
        if not habit:
            exists = connection.execute("SELECT type FROM events WHERE habit_id=? LIMIT 1", (habit_id,)).fetchone()
            if not exists:
                return None
            identity = {"id": habit_id, "code": "", "name": f"Habit {habit_id + 1}", "type": exists[0]}
            exact_filter, identity_params = "", []
        else:
            identity = {"id": habit_id, "code": habit["code"] or "", "name": habit["name"] or f"Habit {habit_id + 1}", "type": habit["type"] or "count"}
            exact_filter = """AND (e.config_snapshot_id IS NULL OR EXISTS(
                SELECT 1 FROM habit_snapshot_entries se WHERE se.snapshot_id=e.config_snapshot_id
                 AND se.slot_id=e.habit_id AND se.active=1 AND se.code=? AND se.name=? AND se.type=?))"""
            identity_params = [identity["code"], identity["name"], identity["type"]]
        base = f"FROM events e WHERE e.deleted=0 AND e.habit_id=? AND e.type=? {exact_filter}"
        params = [habit_id, identity["type"], *identity_params]
        daily_rows = connection.execute(
            f"""SELECT tickstone_day, COUNT(*) AS sessions,
                       SUM(CASE WHEN e.type='count' THEN e.count ELSE e.duration_seconds END) AS value
                  {base} AND tickstone_day>=? AND tickstone_day<? GROUP BY tickstone_day ORDER BY tickstone_day""",
            (*params, start.isoformat(), end.isoformat())).fetchall()
        previous_value = connection.execute(
            f"""SELECT COALESCE(SUM(CASE WHEN e.type='count' THEN e.count ELSE e.duration_seconds END),0)
                  {base} AND tickstone_day>=? AND tickstone_day<?""",
            (*params, previous[0].isoformat(), previous[1].isoformat())).fetchone()[0]
        all_days = [row[0] for row in connection.execute(
            f"SELECT DISTINCT tickstone_day {base} ORDER BY tickstone_day", params).fetchall()]
        metadata_status = _metadata_status(connection)
    total = sum(row["value"] for row in daily_rows)
    sessions = sum(row["sessions"] for row in daily_rows)
    active_days = len(daily_rows)
    current_streak, longest_streak = _longest_streak(all_days, today)
    trend = None if previous_value == 0 else round((total - previous_value) / previous_value * 100)
    best = max(daily_rows, key=lambda row: row["value"], default=None)
    values_by_day = {row["tickstone_day"]: row["value"] for row in daily_rows}
    if period in ("week", "month"):
        labels = []
        cursor = start
        while cursor < end:
            labels.append(cursor.isoformat()); cursor += timedelta(days=1)
        grouped = [(label, values_by_day.get(label, 0)) for label in labels]
    else:
        monthly = {}
        for label, value in values_by_day.items():
            monthly[label[:7]] = monthly.get(label[:7], 0) + value
        if period == "year":
            grouped = [(f"{today.year}-{month:02d}", monthly.get(f"{today.year}-{month:02d}", 0))
                       for month in range(1, 13)]
        else:
            grouped = sorted(monthly.items())
    peak = max((value for _, value in grouped), default=1) or 1
    points = [{"label": label, "value": value,
               "height": 0 if value == 0 else max(5, round(value / peak * 100))}
              for label, value in grouped]
    best_period = max(grouped, key=lambda item: item[1], default=(None, 0))
    display, unit = _format_value(total, identity["type"])
    average, average_unit = _format_value(round(total / active_days) if active_days else 0, identity["type"])
    return {"generated_at": f"{now:%Y-%m-%d %H:%M}", "habit": identity, "period": period,
            "period_start": start.isoformat(), "period_end": (end - timedelta(days=1)).isoformat(),
            "metadata_status": metadata_status, "total": total, "display_value": display,
            "display_unit": unit, "sessions": sessions, "active_days": active_days,
            "average_value": average, "average_unit": average_unit, "current_streak": current_streak,
            "longest_streak": longest_streak, "previous_total": previous_value, "trend": trend,
            "trend_label": _detail_trend_label(total, previous_value, period),
            "best_day": best["tickstone_day"] if best else None,
            "best_value": best["value"] if best else 0, "best_period": best_period[0],
            "points": points}


def _metadata_note(status):
    if status == "synced":
        return "Habitmetadata synkas automatiskt via Bluetooth."
    if status == "mixed":
        return "Ny metadata är verifierad. Äldre importerade events visas som osäker fallback."
    return "Legacy-läge: events saknar säker historisk habitmetadata."


def _stat_icon(kind):
    paths = {
        "calendar": '<rect x="4" y="6" width="16" height="14" rx="2"/><path d="M8 3v6M16 3v6M4 10h16"/>',
        "check": '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
        "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v6l4 2"/>',
        "trend": '<path d="m4 17 6-6 4 4 6-8"/><path d="M15 7h5v5"/>',
        "grid": '<rect x="4" y="4" width="6" height="6"/><rect x="14" y="4" width="6" height="6"/><rect x="4" y="14" width="6" height="6"/><rect x="14" y="14" width="6" height="6"/>',
        "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1"/>',
        "history": '<path d="M4 20V10h4v10M10 20V4h4v16M16 20v-7h4v7M3 20h18"/>',
        "settings": '<circle cx="12" cy="12" r="3"/><path d="M19 13.5v-3l-2-.7-.5-1.2.9-1.9-2.1-2.1-1.9.9-1.2-.5L11.5 3h-3l-.7 2-1.2.5-1.9-.9-2.1 2.1.9 1.9L3 9.8l-2 .7v3l2 .7.5 1.2-.9 1.9 2.1 2.1 1.9-.9 1.2.5.7 2h3l.7-2 1.2-.5 1.9.9 2.1-2.1-.9-1.9.5-1.2z"/>',
        "bulb": '<path d="M9 18h6M10 21h4M8.5 14.5A6 6 0 1 1 15.5 14.5C14.5 15.2 14 16 14 17h-4c0-1-.5-1.8-1.5-2.5z"/>',
    }
    return f'<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{paths.get(kind, paths["check"])}</svg>'


def _render_statistics_dashboard_legacy(model):
    period_labels = (("week", "Vecka"), ("month", "Månad"), ("year", "År"), ("all", "All tid"))
    tabs = "".join(
        f'<a href="/?period={key}&amp;offset=0" class="period-option{" selected" if model["period"] == key else ""}"'
        f'{" aria-current=page" if model["period"] == key else ""}>{label}</a>'
        for key, label in period_labels
    )
    previous = model["navigation"]["previous_offset"]
    next_offset = model["navigation"]["next_offset"]
    previous_link = (f'<a class="period-arrow" aria-label="Föregående period" href="/?period={model["period"]}&amp;offset={previous}">‹</a>'
                     if previous is not None else '<span class="period-arrow disabled" aria-hidden="true">‹</span>')
    next_link = (f'<a class="period-arrow" aria-label="Nästa period" href="/?period={model["period"]}&amp;offset={next_offset}">›</a>'
                 if next_offset is not None else '<span class="period-arrow disabled" aria-label="Ingen senare period">›</span>')
    kpis = model["kpis"]
    comparison = kpis["comparison"]
    if comparison["percent"] is None and comparison["tone"] == "up":
        trend_value = "Ny"
        trend_label = {"week": "aktivitet den här veckan", "month": "aktivitet den här månaden",
                       "year": "aktivitet i år"}.get(model["period"], "aktivitet")
    elif comparison["percent"] is not None:
        trend_value = f'{"+" if comparison["percent"] > 0 else ""}{comparison["percent"]}%'
        trend_label = {"week": "jämfört med förra veckan", "month": "jämfört med förra månaden",
                       "year": "jämfört med förra året"}.get(model["period"], "förändring")
    else:
        trend_value, trend_label = "—", comparison["label"]
    kpi_cards = (
        ("calendar", str(kpis["active_days"]), "aktiva dagar", f'av {kpis["possible_days"]} möjliga', f'{round(kpis["active_days"] / kpis["possible_days"] * 100) if kpis["possible_days"] else 0}%'),
        ("check", f'{kpis["completion_percent"]}%', "genomfört", "normaliserat mot dina mål", ""),
        ("clock", _duration_compact(kpis["total_seconds"]), "total tid", "i tidsbaserade vanor", ""),
        ("trend", trend_value, trend_label, comparison["delta"], ""),
    )
    cards_html = "".join(
        f'<article class="stat-card"><div class="stat-icon stat-icon-{kind}">{_stat_icon(kind)}</div><div class="stat-copy"><strong>{html.escape(value)}</strong><span>{html.escape(label)}</span><small>{html.escape(detail)}</small></div>'
        f'{f"<b>{html.escape(badge)}</b>" if badge else ""}</article>'
        for kind, value, label, detail, badge in kpi_cards
    )
    bars = "".join(
        f'<div class="stack-column" aria-label="{html.escape(item["date"])}: {item["count_percent"]}% tillfällen, {item["time_percent"]}% tid">'
        f'<div class="stack-space"><span class="stack-count" style="--value:{item["count_percent"]}"></span><span class="stack-time" style="--value:{item["time_percent"]}"></span></div>'
        f'<small>{html.escape(item["label"])}</small></div>' for item in model["activity"]
    ) or '<p class="empty-state">Ingen aktivitet i perioden.</p>'
    habit_rows = "".join(
        f'<a class="habit-performance" href="/habit/{habit["id"]}?period={model["period"] if model["period"] != "all" else "all"}">'
        f'<span class="habit-symbol" style="--habit-color:{habit["color"]}">{html.escape((habit["code"] or habit["name"][:1]).upper())}</span>'
        f'<strong>{html.escape(habit["name"].title())}</strong><span class="habit-type">{html.escape(habit["type_label"])}</span>'
        f'<span class="habit-progress"><b>{html.escape(habit["display_value"])}</b><i><u style="--progress:{min(100, habit["progress_percent"])}"></u></i></span>'
        f'<span class="habit-streak">{_streak_label(habit["current_streak"])}</span>'
        f'<span class="habit-compare compare-{habit["comparison"]["tone"]}" title="{html.escape(habit["comparison"]["label"])}">{html.escape(_compact_comparison_label(habit["comparison"]["label"]))}</span><span class="chevron">›</span></a>'
        for habit in model["habits"]
    ) or '<p class="empty-state">Dina habits visas här efter första synken.</p>'
    heat_cells = "".join(
        f'<span class="heat-cell level-{cell["level"]}{" future" if cell["future"] else ""}" title="{cell["date"]}: {cell["value"]} aktiviteter" aria-label="{cell["date"]}: {cell["value"]} aktiviteter"></span>'
        for cell in model["heatmap"]["cells"]
    )
    week_labels = []
    heat_start = date.fromisoformat(model["heatmap"]["start"])
    for week in range(12):
        label_date = heat_start + timedelta(weeks=week)
        week_labels.append(f'<span>{label_date.day} {SWEDISH_MONTHS[label_date.month - 1][:3]}</span>')
    insight_html = "".join(
        f'<li><span class="insight-icon">{_stat_icon("calendar" if item["kind"] == "calendar" else "trend")}</span><p>{html.escape(item["text"])}</p></li>'
        for item in model["insights"]
    )
    return f'''<!doctype html><html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#f7f8f6"><title>Din statistik · TickStone</title><link rel="stylesheet" href="/assets/styles.css"><script src="/assets/app.js" defer></script></head><body class="statistics-app"><a class="skip-link" href="#main-content">Hoppa till innehåll</a><aside class="app-sidebar"><a class="sidebar-brand" href="/">{_stat_icon("check")}<strong>TickStone</strong></a><nav aria-label="Huvudnavigation"><a class="active" href="#overview">{_stat_icon("grid")}<span>Översikt</span></a><a href="#habits">{_stat_icon("target")}<span>Vanor</span></a><a href="#history">{_stat_icon("history")}<span>Historik</span></a><a href="#settings">{_stat_icon("settings")}<span>Inställningar</span></a></nav><footer><span>TickStone lokal</span><small>Data stannar på din Pi</small></footer></aside><main id="main-content" class="app-main"><header class="app-header" id="overview"><h1>Din statistik</h1><div class="header-controls"><nav class="period-switcher" aria-label="Statistikperiod">{tabs}</nav><div class="date-navigator">{previous_link}<span>{_stat_icon("calendar")}{html.escape(model["period_label"])}</span>{next_link}</div></div></header><section class="stat-cards" aria-label="Periodens nyckeltal">{cards_html}</section><div class="primary-grid"><section class="dashboard-card activity-card" aria-labelledby="activity-heading"><div class="card-heading"><h2 id="activity-heading">{"Veckans" if model["period"] == "week" else "Periodens"} aktivitet</h2><span class="info-dot" title="Normaliserat mot varje habits dagliga mål">i</span></div><div class="stack-chart" role="img" aria-label="Normaliserad aktivitet uppdelad på tillfällen och tid"><div class="chart-y"><span>200</span><span>150</span><span>100</span><span>50</span><span>0</span></div><div class="chart-bars">{bars}</div></div><div class="chart-legend"><span><i class="legend-count"></i>Tillfällen (normaliserat)</span><span><i class="legend-time"></i>Tid (normaliserat)</span><small>100 = ett dagligt mål uppnått</small></div></section><section class="dashboard-card habits-card" id="habits" aria-labelledby="habits-heading"><div class="card-heading"><h2 id="habits-heading">Dina vanor</h2></div><div class="habit-columns" aria-hidden="true"><span></span><span></span><span>Typ</span><span>Progress</span><span>Streak</span><span>Jämfört</span><span></span></div><div class="habit-table">{habit_rows}</div></section></div><div class="secondary-grid"><section class="dashboard-card heatmap-card" id="history" aria-labelledby="heatmap-heading"><div class="card-heading"><h2 id="heatmap-heading">Aktivitet senaste 12 veckorna</h2></div><div class="heatmap-wrap"><div class="heat-week-labels">{''.join(week_labels)}</div><div class="heat-body"><div class="heat-day-labels"><span>Mån</span><span>Tis</span><span>Ons</span><span>Tor</span><span>Fre</span><span>Lör</span><span>Sön</span></div><div class="heat-grid" role="img" aria-label="Aktivitetskalender för de senaste 12 veckorna">{heat_cells}</div></div><div class="heat-legend"><span>Mindre aktivitet</span>{''.join(f'<i class="level-{level}"></i>' for level in range(6))}<span>Mer aktivitet</span></div></div></section><section class="dashboard-card insights-card" aria-labelledby="insights-heading"><div class="card-heading"><h2 id="insights-heading">Insikter</h2><span class="bulb">{_stat_icon("bulb")}</span></div><ul>{insight_html}</ul></section></div><section id="settings" class="sync-footnote"><strong>Synkstatus</strong><span>{html.escape(_metadata_note(model["metadata_status"]))}</span><time>Uppdaterad {html.escape(model["generated_at"])}</time></section></main></body></html>'''


def render_statistics_dashboard(model):
    period_labels = (("week", "Vecka"), ("month", "Månad"), ("year", "År"), ("all", "All tid"))
    tabs = "".join(f'<a href="/?period={key}&amp;offset=0" class="period-option{" selected" if model["period"] == key else ""}"{" aria-current=page" if model["period"] == key else ""}>{label}</a>' for key, label in period_labels)
    previous = model["navigation"]["previous_offset"]
    next_offset = model["navigation"]["next_offset"]
    previous_link = f'<a class="period-arrow" aria-label="Föregående period" href="/?period={model["period"]}&amp;offset={previous}">‹</a>' if previous is not None else '<span class="period-arrow disabled" aria-hidden="true">‹</span>'
    next_link = f'<a class="period-arrow" aria-label="Nästa period" href="/?period={model["period"]}&amp;offset={next_offset}">›</a>' if next_offset is not None else '<span class="period-arrow disabled" aria-label="Ingen senare period">›</span>'
    kpis = model["kpis"]
    comparison = kpis["comparison"]
    if comparison["percent"] is None and comparison["tone"] == "up":
        trend_value = "Ny"
        trend_label = {"week": "aktivitet den här veckan", "month": "aktivitet den här månaden", "year": "aktivitet i år"}.get(model["period"], "aktivitet")
    elif comparison["percent"] is not None:
        trend_value = f'{"+" if comparison["percent"] > 0 else ""}{comparison["percent"]}%'
        trend_label = {"week": "jämfört med förra veckan", "month": "jämfört med förra månaden", "year": "jämfört med förra året"}.get(model["period"], "förändring")
    else:
        trend_value, trend_label = "—", comparison["label"]
    kpi_cards = (("calendar", str(kpis["active_days"]), "aktiva dagar", f'av {kpis["possible_days"]} möjliga', f'{round(kpis["active_days"] / kpis["possible_days"] * 100) if kpis["possible_days"] else 0}%'),
                 ("check", f'{kpis["completion_percent"]}%', "genomfört", "normaliserat mot dina mål", ""),
                 ("clock", _duration_compact(kpis["total_seconds"]), "total tid", "i tidsbaserade vanor", ""),
                 ("trend", trend_value, trend_label, comparison["delta"], ""))
    cards_html = "".join(f'<article class="stat-card"><div class="stat-icon stat-icon-{kind}">{_stat_icon(kind)}</div><div class="stat-copy"><strong>{html.escape(value)}</strong><span>{html.escape(label)}</span><small>{html.escape(detail)}</small></div>{f"<b>{html.escape(badge)}</b>" if badge else ""}</article>' for kind,value,label,detail,badge in kpi_cards)
    habit_rows = "".join(f'<a class="habit-performance" href="/habit/{habit["id"]}?period={model["period"]}"><span class="habit-symbol" style="--habit-color:{habit["color"]}">{html.escape((habit["code"] or habit["name"][:1]).upper())}</span><strong>{html.escape(habit["name"].title())}</strong><span class="habit-type">{html.escape(habit["type_label"])}</span><span class="habit-progress"><b>{html.escape(habit["display_value"])}</b><i><u style="--progress:{min(100,habit["progress_percent"])}"></u></i></span><span class="habit-streak">{_streak_label(habit["current_streak"])}</span><span class="habit-compare compare-{habit["comparison"]["tone"]}" title="{html.escape(habit["comparison"]["label"])}">{html.escape(_compact_comparison_label(habit["comparison"]["label"]))}</span><span class="chevron">›</span></a>' for habit in model["habits"]) or '<p class="empty-state">Dina habits visas här efter första synken.</p>'
    time_toggles = "".join(f'<label class="time-series-toggle"><input type="checkbox" data-series-id="{habit["id"]}" checked><i style="--series-color:{habit["color"]}"></i>{html.escape(habit["name"].title())}</label>' for habit in model["habits"] if habit["type_label"] == "Tid") or '<span class="empty-series">Inga tidsbaserade vanor ännu.</span>'
    heat_cells = "".join(f'<span class="heat-cell level-{cell["level"]}{" future" if cell["future"] else ""}" title="{cell["date"]}: {cell["value"]} aktiviteter" aria-label="{cell["date"]}: {cell["value"]} aktiviteter"></span>' for cell in model["heatmap"]["cells"])
    heat_start = date.fromisoformat(model["heatmap"]["start"])
    week_labels = "".join(f'<span>{(heat_start + timedelta(weeks=week)).day} {SWEDISH_MONTHS[(heat_start + timedelta(weeks=week)).month - 1][:3]}</span>' for week in range(12))
    insight_html = "".join(f'<li><span class="insight-icon">{_stat_icon("calendar" if item["kind"] == "calendar" else "trend")}</span><p>{html.escape(item["text"])}</p></li>' for item in model["insights"])
    return f'''<!doctype html><html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#f4f2ed"><title>Din statistik · TickStone</title><link rel="stylesheet" href="/assets/styles.css"><script src="/assets/app.js" defer></script></head><body class="statistics-app"><a class="skip-link" href="#main-content">Hoppa till innehåll</a><div class="workspace-shell"><header class="workspace-brand"><a href="/">{_stat_icon("check")}<strong>TickStone</strong></a><span>Din rytm, samlad.</span></header><main id="main-content" class="app-main"><header class="app-header" id="overview"><h1>Din statistik</h1><div class="header-controls"><nav class="period-switcher" aria-label="Statistikperiod">{tabs}</nav><div class="date-navigator">{previous_link}<span>{_stat_icon("calendar")}{html.escape(model["period_label"])}</span>{next_link}</div></div></header><section class="stat-cards" aria-label="Periodens nyckeltal">{cards_html}</section><div class="primary-grid"><section class="dashboard-card activity-card time-activity-card" aria-labelledby="activity-heading"><div class="card-heading"><div><p class="eyebrow">UTVECKLING</p><h2 id="activity-heading">Tidsaktivitet</h2></div><div class="chart-type-switch" role="group" aria-label="Diagramtyp"><button type="button" class="selected" data-chart-type="bar" aria-pressed="true">Staplar</button><button type="button" data-chart-type="line" aria-pressed="false">Linje</button></div></div><fieldset class="time-series-toggles" aria-label="Välj tidsbaserade vanor"><legend class="sr-only">Välj vanor</legend>{time_toggles}</fieldset><div id="time-chart" data-period="{model["period"]}" data-offset="{model["offset"]}" role="img" aria-label="Tid per vald vana"><p class="chart-loading">Laddar tidsaktivitet…</p></div><p class="chart-caption">Visar faktisk registrerad tid. Tillfällen ingår inte i grafen.</p></section><section class="dashboard-card habits-card" id="habits" aria-labelledby="habits-heading"><div class="card-heading"><h2 id="habits-heading">Dina vanor</h2></div><div class="habit-columns" aria-hidden="true"><span></span><span></span><span>Typ</span><span>Progress</span><span>Streak</span><span>Jämfört</span><span></span></div><div class="habit-table">{habit_rows}</div></section></div><div class="secondary-grid"><section class="dashboard-card heatmap-card" id="history" aria-labelledby="heatmap-heading"><div class="card-heading"><h2 id="heatmap-heading">Aktivitet senaste 12 veckorna</h2></div><div class="heatmap-wrap"><div class="heat-week-labels">{week_labels}</div><div class="heat-body"><div class="heat-day-labels"><span>Mån</span><span>Tis</span><span>Ons</span><span>Tor</span><span>Fre</span><span>Lör</span><span>Sön</span></div><div class="heat-grid" role="img" aria-label="Aktivitetskalender för de senaste 12 veckorna">{heat_cells}</div></div><div class="heat-legend"><span>Mindre aktivitet</span><i class="level-0"></i><i class="level-1"></i><i class="level-2"></i><i class="level-3"></i><i class="level-4"></i><i class="level-5"></i><span>Mer aktivitet</span></div></div></section><section class="dashboard-card insights-card" aria-labelledby="insights-heading"><div class="card-heading"><h2 id="insights-heading">Insikter</h2><span class="bulb">{_stat_icon("bulb")}</span></div><ul>{insight_html}</ul></section></div><section id="settings" class="sync-footnote"><strong>Synkstatus</strong><span>{html.escape(_metadata_note(model["metadata_status"]))}</span><time>Uppdaterad {html.escape(model["generated_at"])}</time></section></main></div></body></html>'''


def render_dashboard(model):
    summary = model["summary"]
    cards = (("Idag", summary["today"], "aktiviteter"), ("Den här veckan", summary["week"], "aktiviteter"),
             ("Fokustid", summary["minutes"], "minuter"), ("Följd", summary["streak"], "dagar"))
    cards_html = "".join(f'<article class="metric"><span>{html.escape(label)}</span><strong>{value}</strong><small>{unit}</small></article>' for label, value, unit in cards)
    days_html = "".join(f'<div class="day{" is-today" if day.get("today") else ""}" aria-label="{day.get("date",day["label"])}: {day["value"]} aktiviteter"><div class="bar-track"><div class="bar" style="--height:{day["height"]}%"></div></div><span>{day["label"]}</span></div>' for day in model["days"])
    habits_html = "".join(
        f'<li><a class="habit-row" href="/habit/{item["id"]}?period=week"><span class="habit-mark" aria-hidden="true"></span><span class="habit-copy"><strong>{html.escape(item["name"].title())}</strong><small>{html.escape(item["code"])}</small></span><span class="habit-value"><strong>{html.escape(str(item["display_value"]))}</strong><small>{html.escape(item["display_unit"])}</small></span><span class="row-arrow" aria-hidden="true">›</span></a></li>' for item in model["habits"]
    ) or '<li class="empty">Dina habits visas här efter första synken.</li>'
    recent_html = "".join(f'<li class="recent-row"><div><strong>{html.escape(item["name"].title())}</strong><span>{html.escape(item["kind"])}</span></div><time>{html.escape(item["when"])}</time></li>' for item in model["recent"]) or '<li class="empty">Ingen aktivitet ännu.</li>'
    comparisons_html = "".join(
        f'<div class="comparison comparison-{item["tone"]}"><span>{"Vecka" if period == "week" else "Månad"}</span>'
        f'<strong>{html.escape(item["label"])}</strong><small>{item["current"]} nu · {item["previous"]} tidigare</small></div>'
        for period, item in (("week", model["comparisons"]["week"]), ("month", model["comparisons"]["month"]))
    )
    timeline_html = '''<section class="panel timeline-panel" aria-labelledby="timeline-title">
      <div class="panel-heading timeline-heading"><div><p class="eyebrow">JÄMFÖR HABITS</p><h2 id="timeline-title">Utveckling över tid</h2></div>
      <div class="range-tabs" role="group" aria-label="Välj tidsperiod">
        <button type="button" class="range-tab selected" data-range="week" aria-pressed="true">Vecka</button>
        <button type="button" class="range-tab" data-range="month" aria-pressed="false">Månad</button>
        <button type="button" class="range-tab" data-range="year" aria-pressed="false">År</button>
      </div></div>
      <fieldset id="timeline-series" class="series-toggles" aria-label="Välj habits i linjegrafen"><legend class="sr-only">Välj habits</legend></fieldset>
      <div id="timeline-chart" class="line-chart" role="img" aria-label="Linjegraf över aktivitetstillfällen"><p class="chart-loading">Laddar utveckling…</p></div>
      <p class="chart-caption">Varje punkt visar antal aktivitetstillfällen. Välj eller dölj habits ovan.</p>
    </section>'''
    return f'''<!doctype html><html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#f4f2ed"><title>TickStone</title><link rel="stylesheet" href="/assets/styles.css"><script src="/assets/app.js" defer></script></head><body><a class="skip-link" href="#content">Hoppa till innehåll</a><main id="content" class="shell"><header class="topbar"><div class="brand"><span class="brand-stone" aria-hidden="true"></span><div><strong>TickStone</strong><span>Din rytm, samlad.</span></div></div><div class="sync-state"><span aria-hidden="true"></span>Synkad <time id="updated">{html.escape(model["generated_at"])}</time></div></header><section class="intro"><p class="eyebrow">ÖVERSIKT</p><h1>Små steg.<br><em>Synliga framsteg.</em></h1><p class="metadata-note">{html.escape(_metadata_note(model["metadata_status"]))}</p></section><section class="metrics" aria-label="Sammanfattning">{cards_html}</section><section class="comparisons" aria-label="Jämförelse med föregående period">{comparisons_html}</section>{timeline_html}<div class="dashboard-grid"><section class="panel activity-panel"><div class="panel-heading"><div><p class="eyebrow">SENASTE 7 DAGARNA</p><h2>Aktivitet</h2></div><span>{summary["week"]} totalt</span></div><div class="chart" role="img" aria-label="Aktiviteter per dag">{days_html}</div></section><section class="panel habits-panel"><div class="panel-heading"><div><p class="eyebrow">ALLA HABITS</p><h2>Vanor</h2></div></div><ul class="habit-list">{habits_html}</ul></section><section class="panel recent-panel"><div class="panel-heading"><div><p class="eyebrow">HISTORIK</p><h2>Senaste aktivitet</h2></div></div><ul class="recent-list">{recent_html}</ul></section></div><footer><span>TickStone</span><span>Data stannar på din Pi.</span></footer></main></body></html>'''


def _render_habit_detail_with_sidebar(model):
    habit = model["habit"]
    tabs = "".join(f'<a href="/habit/{habit["id"]}?period={period}" class="period-option{" selected" if model["period"] == period else ""}"{" aria-current=page" if model["period"] == period else ""}>{label}</a>' for period, label in (("week","Vecka"),("month","Månad"),("year","År"),("all","All tid")))
    trend = model.get("trend_label") or ("Ingen jämförelse ännu" if model["trend"] is None else f'{model["trend"]:+d}% jämfört med föregående period')
    points = "".join(f'<div class="detail-point" aria-label="{html.escape(point["label"])}: {point["value"]}"><div style="--height:{point["height"]}%"></div><span>{html.escape(point["label"][-5:])}</span></div>' for point in model["points"])
    if not points:
        points = '<p class="empty-state">Ingen aktivitet under perioden.</p>'
    metrics = (("Totalt", model["display_value"], model["display_unit"], "target"),
               ("Aktiva dagar", model["active_days"], "dagar", "calendar"),
               ("Snitt", model["average_value"], model["average_unit"], "trend"),
               ("Längsta streak", model["longest_streak"], "dagar", "check"))
    metric_html = "".join(f'<article class="stat-card"><div class="stat-icon">{_stat_icon(icon)}</div><div class="stat-copy"><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong><small>{html.escape(unit)}</small></div></article>' for label,value,unit,icon in metrics)
    return f'''<!doctype html><html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#f7f8f6"><title>{html.escape(habit["name"])} · TickStone</title><link rel="stylesheet" href="/assets/styles.css"></head><body class="statistics-app"><a class="skip-link" href="#main-content">Hoppa till innehåll</a><aside class="app-sidebar"><a class="sidebar-brand" href="/">{_stat_icon("check")}<strong>TickStone</strong></a><nav aria-label="Huvudnavigation"><a href="/">{_stat_icon("grid")}<span>Översikt</span></a><a class="active" href="#habit-detail">{_stat_icon("target")}<span>Vanor</span></a><a href="/#history">{_stat_icon("history")}<span>Historik</span></a><a href="/#settings">{_stat_icon("settings")}<span>Inställningar</span></a></nav><footer><span>TickStone lokal</span><small>Data stannar på din Pi</small></footer></aside><main id="main-content" class="app-main detail-workspace"><header class="detail-header" id="habit-detail"><div><a class="back-link" href="/">← Översikt</a><p>{html.escape(habit["code"])}</p><h1>{html.escape(habit["name"].title())}</h1><span>{html.escape(model["period_start"])} – {html.escape(model["period_end"])}</span></div><nav class="period-switcher" aria-label="Period">{tabs}</nav></header><section class="stat-cards" aria-label="Habitstatistik">{metric_html}</section><section class="dashboard-card modern-detail-chart"><div class="card-heading"><h2>Aktivitet</h2><strong class="detail-trend">{html.escape(trend)}</strong></div><div class="detail-points" role="img" aria-label="Aktivitet per kalenderperiod">{points}</div><div class="detail-facts"><span>{model["sessions"]} aktivitetstillfällen</span><span>Nuvarande streak: {model["current_streak"]} dagar</span><span>Bästa period: {html.escape(model["best_period"] or "—")}</span></div></section><section class="sync-footnote"><strong>Metadata</strong><span>{html.escape(_metadata_note(model["metadata_status"]))}</span></section></main></body></html>'''


def render_habit_detail(model):
    rendered = _render_habit_detail_with_sidebar(model)
    aside_start = rendered.index('<aside class="app-sidebar">')
    main_start = rendered.index('<main id="main-content"', aside_start)
    brand = f'<div class="workspace-shell"><header class="workspace-brand"><a href="/">{_stat_icon("check")}<strong>TickStone</strong></a><span>Din rytm, samlad.</span></header>'
    rendered = rendered[:aside_start] + brand + rendered[main_start:]
    return rendered.replace('</main></body></html>', '</main></div></body></html>')


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_handler(database):
    database = Path(database)

    class Handler(BaseHTTPRequestHandler):
        server_version = "TickStoneDashboard"
        sys_version = ""

        def version_string(self):
            return self.server_version

        def log_message(self, format, *args):
            return

        def _send(self, status, content_type, body=b"", head=False, extra_headers=None):
            self.send_response(status)
            headers = {"Content-Type": content_type, "Content-Length": str(len(body)), "Cache-Control": "no-store",
                       "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
                       "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                       "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"}
            headers.update(extra_headers or {})
            for key, value in headers.items(): self.send_header(key, value)
            self.end_headers()
            if not head: self.wfile.write(body)

        def _route(self, head=False):
            parsed = urlsplit(self.path); path = parsed.path
            try:
                if path == "/":
                    query = parse_qs(parsed.query)
                    period = query.get("period", ["week"])[0]
                    try:
                        offset = int(query.get("offset", ["0"])[0])
                        model = build_statistics_overview(database, period, offset)
                    except (ValueError, TypeError):
                        self._send(400, "text/plain; charset=utf-8", b"Invalid period or offset\n", head); return
                    self._send(200, "text/html; charset=utf-8", render_statistics_dashboard(model).encode(), head)
                elif re.fullmatch(r"/habit/[0-9]", path):
                    period = parse_qs(parsed.query).get("period", ["week"])[0]
                    if period not in PERIODS:
                        self._send(400, "text/plain; charset=utf-8", b"Invalid period\n", head); return
                    model = build_habit_detail(database, int(path[-1]), period)
                    if model is None:
                        self._send(404, "text/plain; charset=utf-8", b"Not found\n", head)
                    else:
                        self._send(200, "text/html; charset=utf-8", render_habit_detail(model).encode(), head)
                elif path == "/api/time-chart":
                    query = parse_qs(parsed.query)
                    period = query.get("period", ["week"])[0]
                    try:
                        offset = int(query.get("offset", ["0"])[0])
                        payload = json.dumps(build_time_chart(database, period, offset), ensure_ascii=False, separators=(",", ":")).encode()
                    except (ValueError, TypeError):
                        self._send(400, "text/plain; charset=utf-8", b"Invalid period or offset\n", head); return
                    self._send(200, "application/json; charset=utf-8", payload, head)
                elif path == "/api/timeline":
                    timeline_range = parse_qs(parsed.query).get("range", ["month"])[0]
                    if timeline_range not in TIMELINE_RANGES:
                        self._send(400, "application/json; charset=utf-8", b'{"error":"invalid range"}\n', head); return
                    body = (json.dumps(build_timeline(database, timeline_range), ensure_ascii=False,
                                       separators=(",", ":")) + "\n").encode()
                    self._send(200, "application/json; charset=utf-8", body, head)
                elif path == "/healthz":
                    with _readonly_connection(database) as connection: connection.execute("SELECT 1").fetchone()
                    self._send(200, "application/json; charset=utf-8", b'{"status":"ok"}\n', head)
                elif path in ("/assets/styles.css", "/assets/app.js"):
                    name = path.rsplit("/", 1)[1]
                    kind = "text/css; charset=utf-8" if name.endswith(".css") else "text/javascript; charset=utf-8"
                    self._send(200, kind, (WEB_ROOT / name).read_bytes(), head)
                else:
                    self._send(404, "text/plain; charset=utf-8", b"Not found\n", head)
            except sqlite3.Error:
                self._send(503, "text/plain; charset=utf-8", b"Database unavailable\n", head)

        def do_GET(self): self._route()
        def do_HEAD(self): self._route(head=True)
        def _method_not_allowed(self):
            self._send(405, "text/plain; charset=utf-8", b"Method not allowed\n", extra_headers={"Allow": "GET, HEAD"})
        do_POST = do_PUT = do_PATCH = do_DELETE = _method_not_allowed

    return Handler


def main():
    parser = argparse.ArgumentParser(description="TickStone lokal statistikdashboard")
    parser.add_argument("--database", type=Path, default=Path.home() / ".local/share/tickstone/tickstone.sqlite3")
    parser.add_argument("--host", default="127.0.0.1"); parser.add_argument("--port", type=int, default=8750)
    args = parser.parse_args(); server = DashboardServer((args.host, args.port), make_handler(args.database.expanduser()))
    print(f"TickStone dashboard: http://{args.host}:{server.server_port}", flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__ == "__main__": main()
