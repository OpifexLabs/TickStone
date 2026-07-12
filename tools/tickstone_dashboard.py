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
SWEDISH_WEEKDAYS = ("måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag")
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
                  FROM events WHERE deleted=0 AND started_at<? AND tickstone_day>=? AND tickstone_day<?
                 GROUP BY habit_id,bucket ORDER BY habit_id,bucket""",
            (now_epoch, start.isoformat(), end.isoformat()),
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
                  FROM events WHERE deleted=0 AND type='time' AND started_at<? AND tickstone_day>=? AND tickstone_day<?
                 GROUP BY habit_id,bucket ORDER BY habit_id,bucket""",
            (now_epoch, start.isoformat(), end.isoformat()),
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
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"


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


def _elapsed_period_cutoffs(now_epoch):
    local_now = datetime.fromtimestamp(now_epoch, timezone.utc).astimezone(STOCKHOLM)
    logical_now = local_now - timedelta(hours=5)

    week_start_day = logical_now.date() - timedelta(days=logical_now.weekday())
    week_start = datetime.combine(week_start_day, datetime.min.time(), STOCKHOLM) + timedelta(hours=5)
    previous_week_start = week_start - timedelta(days=7)
    previous_week_end = local_now - timedelta(days=7)

    month_start_logical = datetime(logical_now.year, logical_now.month, 1, tzinfo=STOCKHOLM)
    if logical_now.month == 1:
        previous_month_start_logical = datetime(logical_now.year - 1, 12, 1, tzinfo=STOCKHOLM)
    else:
        previous_month_start_logical = datetime(logical_now.year, logical_now.month - 1, 1, tzinfo=STOCKHOLM)
    elapsed = logical_now - month_start_logical
    previous_month_end_logical = month_start_logical
    previous_month_cutoff_logical = min(previous_month_start_logical + elapsed, previous_month_end_logical)

    return {
        "week": {"current_start": int(week_start.timestamp()), "current_end": now_epoch,
                 "previous_start": int(previous_week_start.timestamp()),
                 "previous_end": int(previous_week_end.timestamp())},
        "month": {"current_start": int((month_start_logical + timedelta(hours=5)).timestamp()),
                  "current_end": now_epoch,
                  "previous_start": int((previous_month_start_logical + timedelta(hours=5)).timestamp()),
                  "previous_end": int((previous_month_cutoff_logical + timedelta(hours=5)).timestamp())},
    }


def _fair_comparison(current, previous):
    current, previous = int(current or 0), int(previous or 0)
    if previous == 0:
        if current:
            return {"current": current, "previous": previous, "percent": None, "display": "Ny", "tone": "up"}
        return {"current": current, "previous": previous, "percent": 0, "display": "0%", "tone": "flat"}
    percent = round((current - previous) / previous * 100)
    return {"current": current, "previous": previous, "percent": percent,
            "display": f'{"+" if percent > 0 else ""}{percent}%',
            "tone": "up" if percent > 0 else "down" if percent < 0 else "flat"}


def _week_key(day_string):
    day_value = date.fromisoformat(day_string)
    return (day_value - timedelta(days=day_value.weekday())).isoformat()


def _record_duration(value):
    return _duration_compact(value)


def _milestone_duration(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} sek"
    minutes, remainder = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {remainder} sek" if remainder else f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    suffix = f" {minutes} min" if minutes else ""
    if remainder:
        suffix += f" {remainder} sek"
    return f"{hours} h{suffix}"


def build_dashboard_intelligence(database, now_epoch=None):
    now_epoch = int(datetime.now(timezone.utc).timestamp()) if now_epoch is None else int(now_epoch)
    _, today = _today(now_epoch)
    cutoffs = _elapsed_period_cutoffs(now_epoch)
    current_week_start = date.fromisoformat(datetime.fromtimestamp(
        cutoffs["week"]["current_start"], timezone.utc).astimezone(STOCKHOLM).date().isoformat())

    with _readonly_connection(database) as connection:
        identities = connection.execute(
            "SELECT slot_id AS id,code,name,type,current_snapshot_id FROM habits WHERE active=1 ORDER BY slot_id"
        ).fetchall()
        events = connection.execute(
            """SELECT e.habit_id,e.type,e.started_at,e.duration_seconds,e.count,e.tickstone_day
                 FROM events e JOIN habits h ON h.slot_id=e.habit_id
                WHERE e.deleted=0 AND e.started_at<? AND h.active=1 AND h.type=e.type
                  AND ((e.config_snapshot_id IS NOT NULL AND EXISTS(
                        SELECT 1 FROM habit_snapshot_entries se
                         WHERE se.snapshot_id=e.config_snapshot_id AND se.slot_id=e.habit_id
                           AND se.active=1 AND se.code=h.code AND se.name=h.name AND se.type=h.type))
                    OR (e.config_snapshot_id IS NULL AND e.started_at>=COALESCE((
                        SELECT hs.valid_from FROM habit_snapshots hs WHERE hs.id=h.current_snapshot_id),0)))
                ORDER BY e.started_at,e.id""", (now_epoch,),
        ).fetchall()

    identity_by_id = {row["id"]: {"id": row["id"], "name": row["name"] or f"Habit {row['id'] + 1}",
                                  "type": row["type"] or "count"} for row in identities}

    def metric(event):
        return event["count"] if event["type"] == "count" else event["duration_seconds"]

    habit_comparisons = []
    period_values = {period: defaultdict(lambda: [0, 0]) for period in ("week", "month")}
    for event in events:
        for period, bounds in cutoffs.items():
            if bounds["current_start"] <= event["started_at"] < bounds["current_end"]:
                period_values[period][event["habit_id"]][0] += metric(event)
            elif bounds["previous_start"] <= event["started_at"] < bounds["previous_end"]:
                period_values[period][event["habit_id"]][1] += metric(event)
    for identity in identity_by_id.values():
        habit_comparisons.append({"id": identity["id"],
                                  "week": _fair_comparison(*period_values["week"][identity["id"]]),
                                  "month": _fair_comparison(*period_values["month"][identity["id"]])})

    current_week_events = [event for event in events if cutoffs["week"]["current_start"] <= event["started_at"] < now_epoch]
    previous_week_events = [event for event in events if cutoffs["week"]["previous_start"] <= event["started_at"] < cutoffs["week"]["previous_end"]]
    current_days = {event["tickstone_day"] for event in current_week_events}
    previous_days = {event["tickstone_day"] for event in previous_week_events}
    momentum_candidates = []
    log_delta = len(current_week_events) - len(previous_week_events)
    if log_delta > 0:
        improvement = log_delta / max(1, len(previous_week_events))
        momentum_candidates.append((improvement, 2, 0, {"label": "På väg upp",
                                               "detail": f"{log_delta} fler loggar än vid samma tid förra veckan",
                                               "kind": "logs"}))
    day_delta = len(current_days) - len(previous_days)
    if day_delta > 0:
        improvement = day_delta / max(1, len(previous_days))
        momentum_candidates.append((improvement, 3, 0, {"label": "Veckans vinst",
                                                        "detail": f"Du var aktiv {day_delta} fler {'dag' if day_delta == 1 else 'dagar'}",
                                                        "kind": "days"}))
    for comparison in habit_comparisons:
        weekly = comparison["week"]
        if weekly["percent"] is not None and weekly["percent"] > 0:
            identity = identity_by_id[comparison["id"]]
            momentum_candidates.append((weekly["percent"] / 100, 4, -comparison["id"], {"label": "På väg upp",
                                                                "detail": f"{identity['name'].title()} ökade med {weekly['percent']}%",
                                                                "kind": "habit"}))
    for identity in identity_by_id.values():
        current_count = sum(1 for event in current_week_events if event["habit_id"] == identity["id"])
        prior_equivalents = []
        local_now = datetime.fromtimestamp(now_epoch, timezone.utc).astimezone(STOCKHOLM)
        for weeks_back in range(1, 5):
            end = int((local_now - timedelta(days=7 * weeks_back)).timestamp())
            start = int((datetime.fromtimestamp(cutoffs["week"]["current_start"], timezone.utc)
                         .astimezone(STOCKHOLM) - timedelta(days=7 * weeks_back)).timestamp())
            prior_equivalents.append(sum(1 for event in events if event["habit_id"] == identity["id"] and start <= event["started_at"] < end))
        if current_count and any(prior_equivalents) and current_count > max(prior_equivalents):
            prior_peak = max(prior_equivalents)
            improvement = (current_count - prior_peak) / prior_peak
            momentum_candidates.append((improvement, 1, -identity["id"], {"label": "Veckans vinst",
                                                                 "detail": f"{identity['name'].title()} hade sin bästa vecka på en månad",
                                                                 "kind": "best-month"}))
    if momentum_candidates:
        momentum = max(momentum_candidates, key=lambda item: (item[0], item[1], item[2]))[3]
    elif log_delta < 0:
        amount = abs(log_delta)
        momentum = {"label": "Ingen positiv trend ännu",
                    "detail": f"{amount} färre loggar än vid samma tid förra veckan", "kind": "down"}
    elif day_delta < 0:
        amount = abs(day_delta)
        momentum = {"label": "Ingen positiv trend ännu",
                    "detail": f"{amount} färre aktiva {'dag' if amount == 1 else 'dagar'} än förra veckan", "kind": "down"}
    else:
        momentum = {"label": "I takt", "detail": "Samma nivå som vid samma tid förra veckan", "kind": "flat"}

    weekly_sessions = defaultdict(int)
    weekly_time = defaultdict(int)
    weekly_habit_values = defaultdict(lambda: defaultdict(int))
    daily_count = defaultdict(int)
    days_by_habit = defaultdict(set)
    for event in events:
        week = _week_key(event["tickstone_day"])
        weekly_sessions[week] += 1
        weekly_habit_values[event["habit_id"]][week] += metric(event)
        if event["type"] == "time":
            weekly_time[week] += event["duration_seconds"]
        else:
            daily_count[(event["habit_id"], event["tickstone_day"])] += event["count"]
        days_by_habit[event["habit_id"]].add(event["tickstone_day"])

    longest_streak_value, longest_streak_habit = 0, None
    for habit_id, days in days_by_habit.items():
        _, longest = _longest_streak(sorted(days), today)
        if longest > longest_streak_value:
            longest_streak_value, longest_streak_habit = longest, habit_id
    best_week = max(weekly_sessions.items(), key=lambda item: (item[1], item[0]), default=(None, 0))
    most_count = max(daily_count.items(), key=lambda item: (item[1], item[0]), default=((None, None), 0))
    time_events = [event for event in events if event["type"] == "time"]
    longest_time = max(time_events, key=lambda event: (event["duration_seconds"], event["started_at"]), default=None)
    best_time_week = max(weekly_time.items(), key=lambda item: (item[1], item[0]), default=(None, 0))
    personal_records = {
        "longest_streak": {"value": longest_streak_value, "habit_id": longest_streak_habit},
        "best_week": {"value": best_week[1], "week": best_week[0]},
        "most_count_day": {"value": most_count[1], "habit_id": most_count[0][0], "date": most_count[0][1]},
        "longest_time_session": {"value": longest_time["duration_seconds"] if longest_time else 0,
                                 "habit_id": longest_time["habit_id"] if longest_time else None},
        "most_total_time_week": {"value": best_time_week[1], "week": best_time_week[0]},
    }

    current_week_key = current_week_start.isoformat()
    before_week = [event for event in events if event["tickstone_day"] < current_week_key]
    current_week_all = [event for event in events if event["tickstone_day"] >= current_week_key]
    previous_week_sessions = defaultdict(int)
    previous_week_time = defaultdict(int)
    previous_daily_count = defaultdict(int)
    previous_days_by_habit = defaultdict(set)
    for event in before_week:
        week = _week_key(event["tickstone_day"])
        previous_week_sessions[week] += 1
        if event["type"] == "time":
            previous_week_time[week] += event["duration_seconds"]
        else:
            previous_daily_count[(event["habit_id"], event["tickstone_day"])] += event["count"]
        previous_days_by_habit[event["habit_id"]].add(event["tickstone_day"])
    new_records = []
    prior_best_week = max(previous_week_sessions.values(), default=0)
    if prior_best_week and len(current_week_all) > prior_best_week:
        new_records.append({"kind": "best_week", "value": len(current_week_all), "text": "Din bästa vecka hittills"})
    prior_best_count = max(previous_daily_count.values(), default=0)
    current_count_days = defaultdict(int)
    for event in current_week_all:
        if event["type"] == "count":
            current_count_days[(event["habit_id"], event["tickstone_day"])] += event["count"]
    current_best_count = max(current_count_days.values(), default=0)
    if prior_best_count and current_best_count > prior_best_count:
        new_records.append({"kind": "most_count_day", "value": current_best_count,
                            "text": f"Nytt rekord: {current_best_count} tillfällen på en dag"})
    prior_longest_time = max((event["duration_seconds"] for event in before_week if event["type"] == "time"), default=0)
    current_longest_event = max((event for event in current_week_all if event["type"] == "time"),
                                key=lambda event: event["duration_seconds"], default=None)
    if current_longest_event and prior_longest_time and current_longest_event["duration_seconds"] > prior_longest_time:
        identity = identity_by_id.get(current_longest_event["habit_id"], {"name": "vana"})
        new_records.append({"kind": "longest_time_session", "value": current_longest_event["duration_seconds"],
                            "text": f"Nytt rekord: {_record_duration(current_longest_event['duration_seconds'])} {identity['name'].title()}"})
    prior_best_time_week = max(previous_week_time.values(), default=0)
    current_time_total = sum(event["duration_seconds"] for event in current_week_all if event["type"] == "time")
    if prior_best_time_week and current_time_total > prior_best_time_week:
        new_records.append({"kind": "most_total_time_week", "value": current_time_total,
                            "text": f"Nytt rekord: {_record_duration(current_time_total)} totalt den här veckan"})
    prior_longest_streak = max((_longest_streak(sorted(days), current_week_start - timedelta(days=1))[1]
                                for days in previous_days_by_habit.values()), default=0)
    if prior_longest_streak and longest_streak_value > prior_longest_streak:
        new_records.append({"kind": "longest_streak", "value": longest_streak_value,
                            "text": f"Nytt rekord: {longest_streak_value} dagars streak"})

    priority = {"longest_time_session": 5, "most_total_time_week": 4, "most_count_day": 3,
                "best_week": 2, "longest_streak": 1}
    record_insight = max(new_records, key=lambda item: (priority[item["kind"]], item["value"]), default=None)

    milestone_candidates = []
    for identity in identity_by_id.values():
        values = weekly_habit_values[identity["id"]]
        current_value = values.get(current_week_key, 0)
        previous_best = max((value for week, value in values.items() if week < current_week_key), default=0)
        if current_value > 0 and previous_best >= current_value:
            target = previous_best + 1
            remaining = target - current_value
            shown = _milestone_duration(remaining) if identity["type"] == "time" else f"{remaining} {'tillfälle' if remaining == 1 else 'tillfällen'}"
            milestone_candidates.append((remaining / previous_best, remaining, {
                "habit_id": identity["id"], "remaining": remaining,
                "text": f"{shown} kvar till nytt personbästa i {identity['name'].title()}"}))
    milestone = min(milestone_candidates, key=lambda item: (item[0], item[1], item[2]["habit_id"]))[2] if milestone_candidates else None

    return {"cutoffs": cutoffs, "habit_comparisons": habit_comparisons, "momentum": momentum,
            "personal_records": personal_records, "new_records": new_records,
            "record_insight": record_insight, "milestone": milestone}


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
            """SELECT h.slot_id AS id,h.code,h.name,h.type
                 FROM habits h WHERE h.active=1
                UNION SELECT e.habit_id,NULL,NULL,MIN(e.type) FROM events e
                 WHERE e.deleted=0 AND NOT EXISTS(SELECT 1 FROM habits h WHERE h.slot_id=e.habit_id)
                GROUP BY e.habit_id ORDER BY id"""
        ).fetchall()
        current_rows = connection.execute(
            """SELECT habit_id,tickstone_day,type,COUNT(*) AS sessions,
                      COALESCE(SUM(CASE WHEN type='count' THEN count ELSE 0 END),0) AS count_total,
                      COALESCE(SUM(CASE WHEN type='time' THEN duration_seconds ELSE 0 END),0) AS seconds
                 FROM events WHERE deleted=0 AND started_at<? AND tickstone_day>=? AND tickstone_day<?
                GROUP BY habit_id,tickstone_day,type ORDER BY tickstone_day,habit_id""",
            (now_epoch, start.isoformat(), end.isoformat()),
        ).fetchall()
        previous_rows = connection.execute(
            """SELECT habit_id,type,COUNT(*) AS sessions,
                      COALESCE(SUM(CASE WHEN type='count' THEN count ELSE 0 END),0) AS count_total,
                      COALESCE(SUM(CASE WHEN type='time' THEN duration_seconds ELSE 0 END),0) AS seconds
                 FROM events WHERE deleted=0 AND started_at<? AND tickstone_day>=? AND tickstone_day<?
                GROUP BY habit_id,type""", (now_epoch, previous[0].isoformat(), previous[1].isoformat()),
        ).fetchall()
        heat_end = min(end - timedelta(days=1), today)
        heat_end += timedelta(days=6 - heat_end.weekday())
        heat_start = heat_end - timedelta(days=83)
        heat_rows = connection.execute(
            """SELECT tickstone_day,COUNT(*) AS sessions FROM events
                WHERE deleted=0 AND started_at<? AND tickstone_day>=? AND tickstone_day<=? GROUP BY tickstone_day""",
            (now_epoch, heat_start.isoformat(), heat_end.isoformat()),
        ).fetchall()
        streak_rows = connection.execute(
            "SELECT habit_id,tickstone_day FROM events WHERE deleted=0 AND started_at<? GROUP BY habit_id,tickstone_day ORDER BY habit_id,tickstone_day",
            (now_epoch,),
        ).fetchall()
        metadata_status = _metadata_status(connection)

    intelligence = build_dashboard_intelligence(database, now_epoch)
    fair_by_habit = {row["id"]: row for row in intelligence["habit_comparisons"]}

    current_sessions = sum(row["sessions"] for row in current_rows)
    previous_sessions = sum(row["sessions"] for row in previous_rows)
    active_days = len({row["tickstone_day"] for row in current_rows})
    total_seconds = sum(row["seconds"] for row in current_rows)

    previous_by_habit = {row["habit_id"]: row for row in previous_rows}
    streak_by_habit = defaultdict(list)
    for row in streak_rows:
        streak_by_habit[row["habit_id"]].append(row["tickstone_day"])
    habits = []
    for identity in identities:
        rows = [row for row in current_rows if row["habit_id"] == identity["id"]]
        sessions = sum(row["sessions"] for row in rows)
        raw_value = sum(row["count_total"] if identity["type"] == "count" else row["seconds"] for row in rows)

        previous_row = previous_by_habit.get(identity["id"])
        previous_value = 0 if not previous_row else previous_row["count_total"] if identity["type"] == "count" else previous_row["seconds"]
        comparison = _period_comparison(raw_value, previous_value, period)
        current_streak, longest_streak = _longest_streak(streak_by_habit[identity["id"]], today)
        display_value = f"{raw_value} {'gång' if raw_value == 1 else 'gånger'}" if identity["type"] == "count" else _duration_compact(raw_value)
        habits.append({"id": identity["id"], "code": identity["code"] or "",
                       "name": identity["name"] or f"Habit {identity['id'] + 1}",
                       "type": identity["type"], "type_label": "Tillfällen" if identity["type"] == "count" else "Tid",
                       "sessions": sessions, "display_value": display_value,
                       "current_streak": current_streak,
                       "longest_streak": longest_streak, "comparison": comparison,
                       "comparisons": fair_by_habit.get(identity["id"], {
                           "week": _fair_comparison(0, 0), "month": _fair_comparison(0, 0)}),
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
    strongest = max(habits, key=lambda row: (row["sessions"], -row["id"]), default=None)
    if strongest and strongest["sessions"]:
        insights.append({"kind": "consistency", "text": f"{strongest['name'].title()} leder perioden med {strongest['sessions']} loggar."})
    if not insights:
        insights.append({"kind": "trend", "text": "Logga några aktiviteter för att låsa upp personliga insikter."})
    if period == "week" and offset == 0:
        highlighted = []
        if intelligence["record_insight"]:
            highlighted.append({"kind": "record", "text": intelligence["record_insight"]["text"]})
        if intelligence["milestone"]:
            highlighted.append({"kind": "milestone", "text": intelligence["milestone"]["text"]})
        insights = (highlighted + insights)[:2]

    period_comparison = _period_comparison(current_sessions, previous_sessions, period)
    if period == "week" and offset == 0:
        momentum_card = intelligence["momentum"]
    else:
        percent = period_comparison["percent"]
        label = ("Hela historiken" if period == "all" else
                 "Ny period" if percent is None and period_comparison["tone"] == "up" else
                 f'{"+" if percent and percent > 0 else ""}{percent}%' if percent is not None else "Periodjämförelse")
        momentum_card = {"label": label, "detail": period_comparison["label"], "kind": "selected-period"}

    previous_offset = offset - 1 if period != "all" else None
    next_offset = offset + 1 if period != "all" and offset < 0 else None
    return {"generated_at": f"{now:%Y-%m-%d %H:%M}", "period": period, "offset": offset,
            "period_start": start.isoformat(), "period_end": (end - timedelta(days=1)).isoformat(),
            "period_label": _swedish_period_label(start, end, period),
            "navigation": {"previous_offset": previous_offset, "next_offset": next_offset},
            "metadata_status": metadata_status,
            "kpis": {"active_days": active_days, "possible_days": possible_days,
                     "total_seconds": total_seconds,
                     "total_sessions": current_sessions,
                     "comparison": period_comparison,
                     "momentum": momentum_card},
            "personal_records": intelligence["personal_records"],
            "new_records": intelligence["new_records"],
            "habits": habits,
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


def _streak_record(days, today):
    ordered = sorted({date.fromisoformat(value) for value in days})
    longest = current = 0
    longest_end = previous = None
    for item in ordered:
        current = current + 1 if previous and item == previous + timedelta(days=1) else 1
        if current > longest:
            longest, longest_end = current, item
        previous = item
    current_streak, _ = _longest_streak([item.isoformat() for item in ordered], today)
    return current_streak, longest, longest_end.isoformat() if longest_end else None


def _event_source(raw_json):
    try:
        payload = json.loads(raw_json or "{}")
    except (TypeError, ValueError):
        return "TickStone"
    source = str(payload.get("source") or payload.get("mode") or "").strip().lower()
    return {"timer": "Timer", "stopwatch": "Tidtagare", "timing": "Tidtagare"}.get(source, "TickStone")


def _detail_chart_modes(daily_values, today):
    day_start = today - timedelta(days=13)
    day = [{"label": (day_start + timedelta(days=index)).isoformat(),
            "value": daily_values.get((day_start + timedelta(days=index)).isoformat(), 0)}
           for index in range(14)]
    current_week = today - timedelta(days=today.weekday())
    week = []
    for offset in range(-7, 1):
        start = current_week + timedelta(weeks=offset)
        value = sum(daily_values.get((start + timedelta(days=index)).isoformat(), 0) for index in range(7))
        week.append({"label": start.isoformat(), "value": value})
    current_month = today.replace(day=1)
    month = []
    for offset in range(-11, 1):
        year, number = _shift_month(current_month.year, current_month.month, offset)
        key = f"{year}-{number:02d}"
        month.append({"label": key, "value": sum(value for label, value in daily_values.items() if label.startswith(key))})
    return {"day": day, "week": week, "month": month}


def build_habit_detail(database, habit_id, period="week", now_epoch=None):
    if type(habit_id) is not int or not 0 <= habit_id <= 9 or period not in PERIODS:
        raise ValueError("invalid habit or period")
    now_epoch = int(datetime.now(timezone.utc).timestamp()) if now_epoch is None else int(now_epoch)
    now, today = _today(now_epoch)
    start, end, previous = _period_bounds(today, period)
    calendar_start = today - timedelta(days=today.weekday()) - timedelta(weeks=11)
    cutoffs = _elapsed_period_cutoffs(now_epoch)
    with _readonly_connection(database) as connection:
        habit = connection.execute(
            """SELECT h.slot_id,h.code,h.name,h.type,h.current_snapshot_id,s.valid_from
                 FROM habits h LEFT JOIN habit_snapshots s ON s.id=h.current_snapshot_id
                WHERE h.slot_id=?""", (habit_id,)
        ).fetchone()
        if not habit:
            exists = connection.execute("SELECT type FROM events WHERE habit_id=? LIMIT 1", (habit_id,)).fetchone()
            if not exists:
                return None
            identity = {"id": habit_id, "code": "", "name": f"Habit {habit_id + 1}", "type": exists[0]}
            exact_filter, identity_params = "", []
        else:
            identity = {"id": habit_id, "code": habit["code"] or "", "name": habit["name"] or f"Habit {habit_id + 1}", "type": habit["type"] or "count"}
            exact_filter = """AND ((e.config_snapshot_id IS NOT NULL AND EXISTS(
                SELECT 1 FROM habit_snapshot_entries se WHERE se.snapshot_id=e.config_snapshot_id
                 AND se.slot_id=e.habit_id AND se.active=1 AND se.code=? AND se.name=? AND se.type=?))
                OR (e.config_snapshot_id IS NULL AND (? IS NULL OR e.started_at>=?)))"""
            identity_params = [identity["code"], identity["name"], identity["type"],
                               habit["valid_from"], habit["valid_from"]]
        metric_column = "e.duration_seconds" if identity["type"] == "time" else "e.count"
        daily_rows = connection.execute(
            f"""SELECT e.tickstone_day,COUNT(*) AS sessions,COALESCE(SUM({metric_column}),0) AS value
                  FROM events e WHERE e.deleted=0 AND e.habit_id=? AND e.type=? AND e.started_at<? {exact_filter}
                 GROUP BY e.tickstone_day ORDER BY e.tickstone_day""",
            (habit_id, identity["type"], now_epoch, *identity_params)).fetchall()
        pattern_rows = connection.execute(
            f"""SELECT e.id,e.started_at,e.duration_seconds,e.count,e.tickstone_day
                  FROM events e WHERE e.deleted=0 AND e.habit_id=? AND e.type=? AND e.started_at<? {exact_filter}
                 ORDER BY e.started_at DESC,e.id DESC LIMIT 500""",
            (habit_id, identity["type"], now_epoch, *identity_params)).fetchall()[::-1]
        longest = connection.execute(
            f"""SELECT e.id,e.started_at,e.duration_seconds,e.tickstone_day FROM events e
                 WHERE e.deleted=0 AND e.habit_id=? AND e.type=? AND e.started_at<? {exact_filter}
                 ORDER BY e.duration_seconds DESC,e.started_at,e.id LIMIT 1""",
            (habit_id, identity["type"], now_epoch, *identity_params)).fetchone() if identity["type"] == "time" else None
        comparison_values = {}
        for key in ("week", "month"):
            bounds = cutoffs[key]
            comparison_values[key] = connection.execute(
                f"""SELECT COALESCE(SUM(CASE WHEN e.started_at>=? AND e.started_at<? THEN {metric_column} ELSE 0 END),0) AS current,
                           COALESCE(SUM(CASE WHEN e.started_at>=? AND e.started_at<? THEN {metric_column} ELSE 0 END),0) AS previous
                      FROM events e WHERE e.deleted=0 AND e.habit_id=? AND e.type=? AND e.started_at<? {exact_filter}""",
                (bounds["current_start"], bounds["current_end"], bounds["previous_start"], bounds["previous_end"],
                 habit_id, identity["type"], now_epoch, *identity_params)).fetchone()
        recent_rows = connection.execute(
            f"""SELECT e.id,e.started_at,e.duration_seconds,e.count,e.tickstone_day,e.raw_json
                  FROM events e WHERE e.deleted=0 AND e.habit_id=? AND e.type=? AND e.started_at<?
                   AND e.tickstone_day>=? {exact_filter}
                 ORDER BY e.started_at,e.id""",
            (habit_id, identity["type"], now_epoch, calendar_start.isoformat(), *identity_params)).fetchall()
        metadata_status = _metadata_status(connection)

    def metric(row):
        return int(row["duration_seconds"] if identity["type"] == "time" else row["count"])

    daily_values = defaultdict(int)
    for row in daily_rows:
        daily_values[row["tickstone_day"]] = int(row["value"])
    daily_events = defaultdict(list)
    for row in recent_rows:
        local_time = datetime.fromtimestamp(row["started_at"], timezone.utc).astimezone(STOCKHOLM)
        value, unit = _format_value(metric(row), identity["type"])
        daily_events[row["tickstone_day"]].append({
            "id": row["id"], "time": local_time.strftime("%H:%M"), "value": metric(row),
            "display": f"{value} {unit}".strip(), "source": _event_source(row["raw_json"]),
        })

    selected_days = {label: value for label, value in daily_values.items()
                     if start.isoformat() <= label < end.isoformat()}
    total = sum(selected_days.values())
    sessions = sum(int(row["sessions"]) for row in daily_rows
                   if start.isoformat() <= row["tickstone_day"] < end.isoformat())
    active_days = len(selected_days)
    all_days = sorted(daily_values)
    current_streak, longest_streak, longest_streak_date = _streak_record(all_days, today)

    comparisons = {
        key: _fair_comparison(int(comparison_values[key]["current"]), int(comparison_values[key]["previous"]))
        for key in ("week", "month")
    }

    previous_total = sum(value for label, value in daily_values.items()
                         if previous[0].isoformat() <= label < previous[1].isoformat())
    if period == "week":
        previous_total = comparisons["week"]["previous"]
    elif period == "month":
        previous_total = comparisons["month"]["previous"]
    trend = None if previous_total == 0 else round((total - previous_total) / previous_total * 100)

    if period in ("week", "month"):
        labels, cursor = [], start
        while cursor < end:
            labels.append(cursor.isoformat()); cursor += timedelta(days=1)
        grouped = [(label, daily_values.get(label, 0)) for label in labels]
    else:
        monthly = defaultdict(int)
        for label, value in daily_values.items(): monthly[label[:7]] += value
        if period == "year":
            grouped = [(f"{today.year}-{month:02d}", monthly.get(f"{today.year}-{month:02d}", 0)) for month in range(1, 13)]
        else:
            grouped = sorted(monthly.items())
    peak = max((value for _, value in grouped), default=1) or 1
    points = [{"label": label, "value": value, "height": 0 if value == 0 else max(5, round(value / peak * 100))}
              for label, value in grouped]

    chart_modes = _detail_chart_modes(daily_values, today)
    weekly_values = defaultdict(int)
    for label, value in daily_values.items():
        item = date.fromisoformat(label); weekly_values[(item - timedelta(days=item.weekday())).isoformat()] += value
    current_week_key = (today - timedelta(days=today.weekday())).isoformat()
    previous_week_best = max((value for key, value in weekly_values.items() if key < current_week_key), default=0)
    current_week_value = weekly_values.get(current_week_key, 0)
    milestone = None
    if current_week_value > 0 and previous_week_best >= current_week_value:
        remaining = previous_week_best + 1 - current_week_value
        shown = _milestone_duration(remaining) if identity["type"] == "time" else f"{remaining} {'tillfälle' if remaining == 1 else 'tillfällen'}"
        milestone = {"remaining": remaining, "text": f"{shown} kvar till nytt personbästa"}

    best_day_value = max(daily_values.values(), default=0)
    best_day_key = min((label for label, value in daily_values.items() if value == best_day_value), default=None)
    best_week_value = max(weekly_values.values(), default=0)
    best_week_key = min((label for label, value in weekly_values.items() if value == best_week_value), default=None)
    best_week_achievement = max(
        (label for label, value in daily_values.items() if value and best_week_key and
         (date.fromisoformat(label) - timedelta(days=date.fromisoformat(label).weekday())).isoformat() == best_week_key),
        default=None)
    records = {
        "best_day": {"value": best_day_value, "date": best_day_key},
        "best_week": {"value": best_week_value, "date": best_week_achievement},
        "longest_streak": {"value": longest_streak, "date": longest_streak_date},
    }
    if identity["type"] == "time":
        longest_value = int(longest["duration_seconds"]) if longest else 0
        records["longest_session"] = {"value": longest_value,
                                      "date": longest["tickstone_day"] if longest else None}
    else:
        records["most_count_day"] = {"value": best_day_value, "date": best_day_key}
    records["latest_record_date"] = max((item["date"] for item in records.values() if isinstance(item, dict) and item.get("date")), default=None)

    def supported_winner(counts, minimum_total):
        if sum(counts.values()) < minimum_total or not counts:
            return None
        ranked = sorted(counts.items(), key=lambda item: (-item[1], str(item[0])))
        lead = ranked[0][1] - (ranked[1][1] if len(ranked) > 1 else 0)
        return ranked[0][0] if ranked[0][1] >= 2 and lead >= 2 else None

    weekday_counts = defaultdict(int)
    for label in all_days: weekday_counts[date.fromisoformat(label).weekday()] += 1
    patterns = []
    weekday = supported_winner(weekday_counts, 4)
    if weekday is not None:
        patterns.append(f"{SWEDISH_WEEKDAYS[weekday].capitalize()} är din mest konsekventa dag.")
    if len(pattern_rows) >= 5:
        dayparts = defaultdict(int)
        for row in pattern_rows:
            hour = datetime.fromtimestamp(row["started_at"], timezone.utc).astimezone(STOCKHOLM).hour
            part = "morgonen" if 5 <= hour < 12 else "eftermiddagen" if 12 <= hour < 17 else "kvällen" if 17 <= hour < 24 else "natten"
            dayparts[part] += 1
        common = supported_winner(dayparts, 5)
        if common is not None:
            patterns.append(f"Du loggar {identity['name'].title()} oftast på {common}.")
    weekday_metrics = [metric(row) for row in pattern_rows if date.fromisoformat(row["tickstone_day"]).weekday() < 5]
    weekend_metrics = [metric(row) for row in pattern_rows if date.fromisoformat(row["tickstone_day"]).weekday() >= 5]
    if len(weekday_metrics) >= 2 and len(weekend_metrics) >= 2 and sum(weekday_metrics):
        weekday_average = sum(weekday_metrics) / len(weekday_metrics); weekend_average = sum(weekend_metrics) / len(weekend_metrics)
        difference = round(abs(weekend_average - weekday_average) / weekday_average * 100)
        if difference >= 10:
            direction = "längre" if identity["type"] == "time" and weekend_average > weekday_average else "kortare" if identity["type"] == "time" else "fler" if weekend_average > weekday_average else "färre"
            patterns.append(f"Du registrerar {difference}% {direction} {'sessioner' if identity['type'] == 'time' else 'tillfällen'} på helger.")
    if len(pattern_rows) >= 3 and len(patterns) < 3:
        intervals = [pattern_rows[index]["started_at"] - pattern_rows[index - 1]["started_at"] for index in range(1, len(pattern_rows))]
        hours = round(sum(intervals) / len(intervals) / 3600)
        patterns.append(f"Det går i snitt {hours} timmar mellan dina loggar.")

    calendar_peak = max((daily_values.get((calendar_start + timedelta(days=offset)).isoformat(), 0)
                         for offset in range(84)), default=1) or 1
    calendar_cells = []
    for offset in range(84):
        item = calendar_start + timedelta(days=offset); label = item.isoformat(); value = daily_values.get(label, 0)
        event_items = daily_events.get(label, [])
        day_display = _detail_value(value, identity["type"])
        calendar_cells.append({"date": label, "value": value, "display": day_display,
                               "short_value": round(value / 60) if identity["type"] == "time" and value else value,
                               "sessions": len(event_items), "events": event_items,
                               "future": item > today, "level": 0 if not value else min(4, 1 + round(value / calendar_peak * 3))})
    log_groups = [{"date": label, "value": daily_values[label], "events": list(reversed(daily_events[label]))}
                  for label in sorted(daily_events, reverse=True)[:90]]

    completed_weeks = [item["value"] for item in chart_modes["week"][:-1]]
    recent_pairs = [(previous, current) for previous, current in zip(completed_weeks[-5:-1], completed_weeks[-4:])
                    if previous > 0 or current > 0]
    improved = sum(current > previous for previous, current in recent_pairs)
    if len(recent_pairs) < 3:
        trend_title = "Ny rytm"
        trend_text = "Mer historik behövs för en säker utvecklingstrend."
    else:
        trend_title = "På väg upp" if improved >= 3 else "Stabil utveckling" if improved >= 2 else "Lugnare utveckling"
        trend_text = f"{improved} av de senaste {len(recent_pairs)} avslutade veckorna var bättre än veckan före."
    active_weeks = [item for item in chart_modes["week"] if item["value"] > 0]
    trend_summary = {"title": trend_title, "text": trend_text,
                     "best": max(active_weeks, key=lambda item: item["value"], default={"label": "—", "value": 0}),
                     "weakest": min(active_weeks, key=lambda item: item["value"], default={"label": "—", "value": 0})}

    display, unit = _format_value(total, identity["type"])
    average, average_unit = _format_value(round(total / active_days) if active_days else 0, identity["type"])
    session_average, session_average_unit = _format_value(round(total / sessions) if sessions else 0, identity["type"])
    best_period = max(grouped, key=lambda item: item[1], default=(None, 0))
    return {"generated_at": f"{now:%Y-%m-%d %H:%M}", "habit": identity, "period": period,
            "period_start": start.isoformat(), "period_end": (end - timedelta(days=1)).isoformat(),
            "metadata_status": metadata_status, "total": total, "display_value": display, "display_unit": unit,
            "sessions": sessions, "active_days": active_days, "average_value": average, "average_unit": average_unit,
            "session_average_value": session_average, "session_average_unit": session_average_unit,
            "current_streak": current_streak, "longest_streak": longest_streak, "previous_total": previous_total,
            "trend": trend, "trend_label": _detail_trend_label(total, previous_total, period), "comparisons": comparisons,
            "milestone": milestone, "records": records, "patterns": patterns[:3], "calendar": {"start": calendar_start.isoformat(), "cells": calendar_cells},
            "log_groups": log_groups, "chart_modes": chart_modes, "trend_summary": trend_summary,
            "best_day": best_day_key, "best_value": best_day_value, "best_period": best_period[0], "points": points}



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
        ("check", str(kpis.get("total_sessions", 0)), "loggar", "i vald period", ""),
        ("clock", _duration_compact(kpis["total_seconds"]), "total tid", "i tidsbaserade vanor", ""),
        ("trend", trend_value, trend_label, comparison["delta"], ""),
    )
    cards_html = "".join(
        f'<article class="stat-card"><div class="stat-icon stat-icon-{kind}">{_stat_icon(kind)}</div><div class="stat-copy"><strong>{html.escape(value)}</strong><span>{html.escape(label)}</span><small>{html.escape(detail)}</small></div>'
        f'{f"<b>{html.escape(badge)}</b>" if badge else ""}</article>'
        for kind, value, label, detail, badge in kpi_cards
    )
    bars = '<p class="empty-state">Aktivitetsdiagrammet visas i den aktuella vyn.</p>'
    habit_rows = "".join(
        f'<a class="habit-performance" href="/habit/{habit["id"]}?period={model["period"] if model["period"] != "all" else "all"}">'
        f'<span class="habit-symbol" style="--habit-color:{habit["color"]}">{html.escape((habit["code"] or habit["name"][:1]).upper())}</span>'
        f'<strong>{html.escape(habit["name"].title())}</strong><span class="habit-type">{html.escape(habit["type_label"])}</span>'
        f'<span class="habit-progress"><b>{html.escape(habit["display_value"])}</b></span>'
        f'<span class="habit-streak" title="{_streak_label(habit["current_streak"])}">{habit["current_streak"]}</span>'
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
    return f'''<!doctype html><html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#f7f8f6"><title>Din statistik · TickStone</title><link rel="stylesheet" href="/assets/styles.css"><script src="/assets/app.js" defer></script></head><body class="statistics-app"><a class="skip-link" href="#main-content">Hoppa till innehåll</a><aside class="app-sidebar"><a class="sidebar-brand" href="/">{_stat_icon("check")}<strong>TickStone</strong></a><nav aria-label="Huvudnavigation"><a class="active" href="#overview">{_stat_icon("grid")}<span>Översikt</span></a><a href="#habits">{_stat_icon("target")}<span>Vanor</span></a><a href="#history">{_stat_icon("history")}<span>Historik</span></a><a href="#settings">{_stat_icon("settings")}<span>Inställningar</span></a></nav><footer><span>TickStone lokal</span><small>Data stannar på din Pi</small></footer></aside><main id="main-content" class="app-main"><header class="app-header" id="overview"><h1>Din statistik</h1><div class="header-controls"><nav class="period-switcher" aria-label="Statistikperiod">{tabs}</nav><div class="date-navigator">{previous_link}<span>{_stat_icon("calendar")}{html.escape(model["period_label"])}</span>{next_link}</div></div></header><section class="stat-cards" aria-label="Periodens nyckeltal">{cards_html}</section><div class="primary-grid"><section class="dashboard-card activity-card" aria-labelledby="activity-heading"><div class="card-heading"><h2 id="activity-heading">{"Veckans" if model["period"] == "week" else "Periodens"} aktivitet</h2><span class="info-dot" title="Normaliserat mot varje habits dagliga mål">i</span></div><div class="stack-chart" role="img" aria-label="Normaliserad aktivitet uppdelad på tillfällen och tid"><div class="chart-y"><span>200</span><span>150</span><span>100</span><span>50</span><span>0</span></div><div class="chart-bars">{bars}</div></div><div class="chart-legend"><span><i class="legend-count"></i>Tillfällen (normaliserat)</span><span><i class="legend-time"></i>Tid (normaliserat)</span><small>100 = ett dagligt mål uppnått</small></div></section><section class="dashboard-card habits-card" id="habits" aria-labelledby="habits-heading"><div class="card-heading"><h2 id="habits-heading">Dina vanor</h2></div><div class="habit-columns" aria-hidden="true"><span></span><span></span><span>Progress</span><span>Streak</span><span>Jämförelse</span><span></span></div><div class="habit-table">{habit_rows}</div></section></div><div class="secondary-grid"><section class="dashboard-card heatmap-card" id="history" aria-labelledby="heatmap-heading"><div class="card-heading"><h2 id="heatmap-heading">Aktivitet senaste 12 veckorna</h2></div><div class="heatmap-wrap"><div class="heat-week-labels">{''.join(week_labels)}</div><div class="heat-body"><div class="heat-day-labels"><span>Mån</span><span>Tis</span><span>Ons</span><span>Tor</span><span>Fre</span><span>Lör</span><span>Sön</span></div><div class="heat-grid" role="img" aria-label="Aktivitetskalender för de senaste 12 veckorna">{heat_cells}</div></div><div class="heat-legend"><span>Mindre aktivitet</span>{''.join(f'<i class="level-{level}"></i>' for level in range(6))}<span>Mer aktivitet</span></div></div></section><section class="dashboard-card insights-card" aria-labelledby="insights-heading"><div class="card-heading"><h2 id="insights-heading">Insikter</h2><span class="bulb">{_stat_icon("bulb")}</span></div><ul>{insight_html}</ul></section></div><section id="settings" class="sync-footnote"><strong>Synkstatus</strong><span>{html.escape(_metadata_note(model["metadata_status"]))}</span><time>Uppdaterad {html.escape(model["generated_at"])}</time></section></main></body></html>'''


def _habit_comparison_html(habit):
    comparisons = habit["comparisons"]
    week, month = comparisons["week"], comparisons["month"]
    title = (f"Vecka {week['display']}; månad {month['display']}. "
             "Jämför med samma förflutna tid i föregående period.")
    return (f'<span class="habit-compare comparison-pair" title="{html.escape(title)}">'
            f'<span><b>V: </b><em class="compare-{week["tone"]}">{html.escape(week["display"])}</em></span>'
            f'<span><b>M: </b><em class="compare-{month["tone"]}">{html.escape(month["display"])}</em></span></span>')


def render_statistics_dashboard(model):
    period_labels = (("week", "Vecka"), ("month", "Månad"), ("year", "År"), ("all", "All tid"))
    tabs = "".join(f'<a href="/?period={key}&amp;offset=0" class="period-option{" selected" if model["period"] == key else ""}"{" aria-current=page" if model["period"] == key else ""}>{label}</a>' for key, label in period_labels)
    previous = model["navigation"]["previous_offset"]
    next_offset = model["navigation"]["next_offset"]
    previous_link = f'<a class="period-arrow" aria-label="Föregående period" href="/?period={model["period"]}&amp;offset={previous}">‹</a>' if previous is not None else '<span class="period-arrow disabled" aria-hidden="true">‹</span>'
    next_link = f'<a class="period-arrow" aria-label="Nästa period" href="/?period={model["period"]}&amp;offset={next_offset}">›</a>' if next_offset is not None else '<span class="period-arrow disabled" aria-label="Ingen senare period">›</span>'
    kpis = model["kpis"]
    momentum = kpis["momentum"]
    kpi_cards = (("calendar", str(kpis["active_days"]), "aktiva dagar", f'av {kpis["possible_days"]} möjliga', f'{round(kpis["active_days"] / kpis["possible_days"] * 100) if kpis["possible_days"] else 0}%'),
                 ("check", str(kpis.get("total_sessions", 0)), "loggar", "i vald period", ""),
                 ("clock", _duration_compact(kpis["total_seconds"]), "total tid", "i tidsbaserade vanor", ""),
                 ("trend", momentum["label"], "momentum", momentum["detail"], ""))
    cards_html = "".join(f'<article class="stat-card{" momentum-card" if kind == "trend" else ""}"><div class="stat-icon stat-icon-{kind}">{_stat_icon(kind)}</div><div class="stat-copy"><strong>{html.escape(value)}</strong><span>{html.escape(label)}</span><small>{html.escape(detail)}</small></div>{f"<b>{html.escape(badge)}</b>" if badge else ""}</article>' for kind,value,label,detail,badge in kpi_cards)
    habit_rows = "".join(f'<a class="habit-performance" href="/habit/{habit["id"]}?period={model["period"]}"><span class="habit-symbol" style="--habit-color:{habit["color"]}">{html.escape((habit["code"] or habit["name"][:1]).upper())}</span><strong>{html.escape(habit["name"].title())}</strong><span class="habit-progress"><b>{html.escape(habit["display_value"])}</b></span><span class="habit-streak" title="{_streak_label(habit["current_streak"])}">{habit["current_streak"]}</span>{_habit_comparison_html(habit)}<span class="chevron">›</span></a>' for habit in model["habits"]) or '<p class="empty-state">Dina habits visas här efter första synken.</p>'
    time_toggles = "".join(f'<label class="time-series-toggle"><input type="checkbox" data-series-id="{habit["id"]}" checked><i style="--series-color:{habit["color"]}"></i>{html.escape(habit["name"].title())}</label>' for habit in model["habits"] if habit["type_label"] == "Tid") or '<span class="empty-series">Inga tidsbaserade vanor ännu.</span>'
    heat_cells = "".join(f'<span class="heat-cell level-{cell["level"]}{" future" if cell["future"] else ""}" title="{cell["date"]}: {cell["value"]} aktiviteter" aria-label="{cell["date"]}: {cell["value"]} aktiviteter"></span>' for cell in model["heatmap"]["cells"])
    heat_start = date.fromisoformat(model["heatmap"]["start"])
    week_labels = "".join(f'<span>{(heat_start + timedelta(weeks=week)).day} {SWEDISH_MONTHS[(heat_start + timedelta(weeks=week)).month - 1][:3]}</span>' for week in range(12))
    insight_html = "".join(f'<li class="{item["kind"]}-insight"><span class="insight-icon">{_stat_icon("calendar" if item["kind"] == "calendar" else "trend")}</span><p>{html.escape(item["text"])}</p></li>' for item in model["insights"])
    return f'''<!doctype html><html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#f4f2ed"><title>Din statistik · TickStone</title><link rel="stylesheet" href="/assets/styles.css"><script src="/assets/app.js" defer></script></head><body class="statistics-app"><a class="skip-link" href="#main-content">Hoppa till innehåll</a><div class="workspace-shell"><header class="workspace-brand"><a href="/">{_stat_icon("check")}<strong>TickStone</strong></a><span>Din rytm, samlad.</span></header><main id="main-content" class="app-main"><header class="app-header" id="overview"><h1>Din statistik</h1><div class="header-controls"><nav class="period-switcher" aria-label="Statistikperiod">{tabs}</nav><div class="date-navigator">{previous_link}<span>{_stat_icon("calendar")}{html.escape(model["period_label"])}</span>{next_link}</div></div></header><section class="stat-cards" aria-label="Periodens nyckeltal">{cards_html}</section><div class="primary-grid"><section class="dashboard-card activity-card time-activity-card" aria-labelledby="activity-heading"><div class="card-heading"><div><p class="eyebrow">UTVECKLING</p><h2 id="activity-heading">Tidsaktivitet</h2></div><div class="chart-type-switch" role="group" aria-label="Diagramtyp"><button type="button" class="selected" data-chart-type="bar" aria-pressed="true">Staplar</button><button type="button" data-chart-type="line" aria-pressed="false">Linje</button></div></div><fieldset class="time-series-toggles" aria-label="Välj tidsbaserade vanor"><legend class="sr-only">Välj vanor</legend>{time_toggles}</fieldset><div id="time-chart" data-period="{model["period"]}" data-offset="{model["offset"]}" role="img" aria-label="Tid per vald vana"><p class="chart-loading">Laddar tidsaktivitet…</p></div><p class="chart-caption">Visar faktisk registrerad tid. Tillfällen ingår inte i grafen.</p></section><section class="dashboard-card habits-card" id="habits" aria-labelledby="habits-heading"><div class="card-heading"><h2 id="habits-heading">Dina vanor</h2></div><div class="habit-columns" aria-hidden="true"><span></span><span></span><span>Progress</span><span>Streak</span><span>Jämförelse</span><span></span></div><div class="habit-table">{habit_rows}</div></section></div><div class="secondary-grid"><section class="dashboard-card heatmap-card" id="history" aria-labelledby="heatmap-heading"><div class="card-heading"><h2 id="heatmap-heading">Aktivitet senaste 12 veckorna</h2></div><div class="heatmap-wrap"><div class="heat-week-labels">{week_labels}</div><div class="heat-body"><div class="heat-day-labels"><span>Mån</span><span>Tis</span><span>Ons</span><span>Tor</span><span>Fre</span><span>Lör</span><span>Sön</span></div><div class="heat-grid" role="img" aria-label="Aktivitetskalender för de senaste 12 veckorna">{heat_cells}</div></div><div class="heat-legend"><span>Mindre aktivitet</span><i class="level-0"></i><i class="level-1"></i><i class="level-2"></i><i class="level-3"></i><i class="level-4"></i><i class="level-5"></i><span>Mer aktivitet</span></div></div></section><section class="dashboard-card insights-card" aria-labelledby="insights-heading"><div class="card-heading"><h2 id="insights-heading">Insikter</h2><span class="bulb">{_stat_icon("bulb")}</span></div><ul>{insight_html}</ul></section></div><section id="settings" class="sync-footnote"><strong>Synkstatus</strong><span>{html.escape(_metadata_note(model["metadata_status"]))}</span><time>Uppdaterad {html.escape(model["generated_at"])}</time></section></main></div></body></html>'''


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
    y_label = "Tid" if habit["type"] == "time" else "Tillfällen"
    value_kind = "time" if habit["type"] == "time" else "count"
    points = "".join(f'<div class="detail-point" data-label="{html.escape(point["label"])}" data-value="{point["value"]}" aria-label="{html.escape(point["label"])}: {point["value"]}"><div style="--height:{point["height"]}%"></div><span>{html.escape(point["label"][-5:])}</span></div>' for point in model["points"])
    if not points:
        points = '<p class="empty-state">Ingen aktivitet under perioden.</p>'
    metrics = (("Totalt", model["display_value"], model["display_unit"], "target"),
               ("Aktiva dagar", model["active_days"], "dagar", "calendar"),
               ("Snitt", model["average_value"], model["average_unit"], "trend"),
               ("Längsta streak", model["longest_streak"], "dagar", "check"))
    metric_html = "".join(f'<article class="stat-card"><div class="stat-icon">{_stat_icon(icon)}</div><div class="stat-copy"><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong><small>{html.escape(unit)}</small></div></article>' for label,value,unit,icon in metrics)
    return f'''<!doctype html><html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#f7f8f6"><title>{html.escape(habit["name"])} · TickStone</title><link rel="stylesheet" href="/assets/styles.css"><script src="/assets/detail-chart.js" defer></script></head><body class="statistics-app"><a class="skip-link" href="#main-content">Hoppa till innehåll</a><aside class="app-sidebar"><a class="sidebar-brand" href="/">{_stat_icon("check")}<strong>TickStone</strong></a><nav aria-label="Huvudnavigation"><a href="/">{_stat_icon("grid")}<span>Översikt</span></a><a class="active" href="#habit-detail">{_stat_icon("target")}<span>Vanor</span></a><a href="/#history">{_stat_icon("history")}<span>Historik</span></a><a href="/#settings">{_stat_icon("settings")}<span>Inställningar</span></a></nav><footer><span>TickStone lokal</span><small>Data stannar på din Pi</small></footer></aside><main id="main-content" class="app-main detail-workspace"><header class="detail-header" id="habit-detail"><div><a class="back-link" href="/">← Översikt</a><p>{html.escape(habit["code"])}</p><h1>{html.escape(habit["name"].title())}</h1><span>{html.escape(model["period_start"])} – {html.escape(model["period_end"])}</span></div><nav class="period-switcher" aria-label="Period">{tabs}</nav></header><section class="stat-cards" aria-label="Habitstatistik">{metric_html}</section><section class="dashboard-card modern-detail-chart"><div class="card-heading"><div><h2>Aktivitet</h2><strong class="detail-trend">{html.escape(trend)}</strong></div><div class="chart-type-switch" role="group" aria-label="Diagramtyp"><button type="button" class="selected" data-detail-chart-type="bar" aria-pressed="true">Staplar</button><button type="button" data-detail-chart-type="line" aria-pressed="false">Linje</button></div></div><div id="detail-chart" class="detail-points" data-habit-id="{habit["id"]}" data-value-kind="{value_kind}" data-y-label="{y_label}" role="img" aria-label="{y_label} per kalenderperiod">{points}</div><div class="detail-facts"><span>{model["sessions"]} aktivitetstillfällen</span><span>Nuvarande streak: {model["current_streak"]} dagar</span><span>Bästa period: {html.escape(model["best_period"] or "—")}</span></div></section><section class="sync-footnote"><strong>Metadata</strong><span>{html.escape(_metadata_note(model["metadata_status"]))}</span></section></main></body></html>'''


def _detail_value(value, kind):
    if kind == "time":
        return _duration_compact(int(value or 0))
    shown, unit = _format_value(int(value or 0), kind)
    return f"{shown} {unit}".strip()


def _detail_date_label(value):
    if not value:
        return "—"
    item = date.fromisoformat(value)
    return f"{item.day} {SWEDISH_MONTHS[item.month - 1]}"


def render_habit_detail(model):
    habit = model["habit"]
    habit_name = html.escape(habit["name"].title())
    kind = habit["type"]
    type_label = "Tid" if kind == "time" else "Tillfällen"
    tabs = "".join(
        f'<a href="/habit/{habit["id"]}?period={key}" class="period-option{" selected" if model["period"] == key else ""}"'
        f'{" aria-current=page" if model["period"] == key else ""}>{label}</a>'
        for key, label in (("week", "Vecka"), ("month", "Månad"), ("year", "År"), ("all", "All tid"))
    )
    comparisons = model.get("comparisons") or {
        "week": _fair_comparison(model.get("total", 0), model.get("previous_total", 0)),
        "month": {"display": "—", "tone": "flat"},
    }
    period_label = {"week": "denna vecka", "month": "denna månad", "year": "i år", "all": "totalt"}[model["period"]]
    period_date_label = _swedish_period_label(
        date.fromisoformat(model["period_start"]), date.fromisoformat(model["period_end"]) + timedelta(days=1), model["period"])
    comparison_html = "".join(
        f'<span><small>{"Förra veckan" if key == "week" else "Förra månaden"}</small>'
        f'<strong class="compare-{comparisons[key]["tone"]}">{html.escape(comparisons[key]["display"])}</strong></span>'
        for key in ("week", "month"))
    trend_summary = model.get("trend_summary") or {"title": "Stabil utveckling", "text": model.get("trend_label") or "Ingen jämförelse ännu"}
    milestone = model.get("milestone")
    milestone_text = milestone["text"] if milestone else "Fortsätt logga för att låsa upp nästa personbästa"
    milestone_class = " available" if milestone else ""
    hero_total = _detail_value(model.get("total", 0), kind)
    if kind == "time":
        average_primary, average_suffix = _duration_compact(round(model.get("total", 0) / model.get("active_days", 1))) if model.get("active_days") else "0 sek", ""
    else:
        average_primary = (f'{model.get("total", 0) / model.get("active_days", 1):.1f}'.replace(".", ",")
                           if model.get("active_days") else "0")
        average_suffix = "gånger"

    kpis = (
        ("trend", model.get("current_streak", 0), "dagar", "Nuvarande streak"),
        ("check", model.get("longest_streak", 0), "dagar", "Längsta streak"),
        ("calendar", model.get("active_days", 0), f'av {(date.fromisoformat(model["period_end"]) - date.fromisoformat(model["period_start"])).days + 1}', "Aktiva dagar"),
        ("history", average_primary, average_suffix, "Snitt per aktiv dag"),
    )
    kpi_html = "".join(
        f'<article class="detail-kpi"><span class="detail-icon">{_stat_icon(icon)}</span><div><strong>{html.escape(str(value))} <i>{html.escape(str(unit))}</i></strong><small>{html.escape(label)}</small></div></article>'
        for icon, value, unit, label in kpis)

    chart_modes = model.get("chart_modes") or {"day": model.get("points", []), "week": [], "month": []}
    chart_data = html.escape(json.dumps(chart_modes, ensure_ascii=False, separators=(",", ":")), quote=True)
    initial_chart_items = "".join(
        f'<li>{html.escape(point["label"])}: {html.escape(_detail_value(point["value"], kind))}</li>'
        for point in chart_modes.get("day", []))
    trend = trend_summary
    best_chart_period = trend.get("best") or {"label": "—", "value": 0}
    weakest_chart_period = trend.get("weakest") or {"label": "—", "value": 0}
    best_chart_label = _detail_date_label(best_chart_period["label"]) if best_chart_period["label"] != "—" else "—"
    weakest_chart_label = _detail_date_label(weakest_chart_period["label"]) if weakest_chart_period["label"] != "—" else "—"

    records = model.get("records") or {
        "best_day": {"value": model.get("best_value", 0), "date": model.get("best_day")},
        "best_week": {"value": model.get("best_value", 0), "date": model.get("best_period")},
        "longest_streak": {"value": model.get("longest_streak", 0), "date": None},
        "latest_record_date": model.get("best_day"),
    }
    record_rows = []
    if kind == "time":
        record_rows.append(("clock", "Längsta session", _detail_value((records.get("longest_session") or {}).get("value", 0), kind)))
    else:
        record_rows.append(("clock", "Flest på en dag", _detail_value((records.get("most_count_day") or records.get("best_day") or {}).get("value", 0), kind)))
    record_rows.extend((
        ("calendar", "Bästa dag", _detail_value((records.get("best_day") or {}).get("value", 0), kind)),
        ("history", "Bästa vecka", _detail_value((records.get("best_week") or {}).get("value", 0), kind)),
        ("trend", "Längsta streak", f'{(records.get("longest_streak") or {}).get("value", 0)} dagar'),
    ))
    records_html = "".join(
        f'<li><span class="detail-icon">{_stat_icon(icon)}</span><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></li>'
        for icon, label, value in record_rows)
    latest_record = _detail_date_label(records.get("latest_record_date"))

    patterns = model.get("patterns") or []
    patterns_html = "".join(
        f'<li><span class="detail-icon">{_stat_icon(("calendar", "clock", "trend")[index % 3])}</span><span>{html.escape(text)}</span></li>'
        for index, text in enumerate(patterns)) or '<p class="detail-empty">Mer historik behövs innan säkra mönster kan visas.</p>'

    calendar = model.get("calendar") or {"cells": []}
    calendar_cells = "".join(
        f'<button type="button" class="habit-day level-{cell["level"]}{" future" if cell.get("future") else ""}" {"disabled" if cell.get("future") else ""} '
        f'data-day="{cell["date"]}" data-value="{cell["value"]}" data-display="{html.escape(cell.get("display", str(cell["value"])), quote=True)}" data-sessions="{cell["sessions"]}" '
        f'data-events="{html.escape(json.dumps(cell["events"], ensure_ascii=False, separators=(",", ":")), quote=True)}" '
        f'aria-label="{cell["date"]}: {cell["sessions"]} {"session" if cell["sessions"] == 1 else "sessioner"}">{cell.get("short_value", cell["value"]) if cell["value"] else ""}</button>'
        for cell in calendar["cells"])
    calendar_weeks = "".join(
        f'<span>{(date.fromisoformat(calendar.get("start", model["period_start"])) + timedelta(weeks=index)).day} '
        f'{SWEDISH_MONTHS[(date.fromisoformat(calendar.get("start", model["period_start"])) + timedelta(weeks=index)).month - 1][:3]}</span>'
        for index in range(12)) if calendar["cells"] else ""

    log_groups = model.get("log_groups") or []
    rendered_log_groups = []
    for group in log_groups[:12]:
        event_rows = "".join(
            f'<li><time>{html.escape(event["time"])}</time><strong>{html.escape(event["display"])}</strong>'
            f'<span>{html.escape(event["source"])}</span><button type="button" class="read-only-log-action" '
            f'title="Dashboarden är skrivskyddad" aria-label="Information om loggkorrigering">•••</button></li>'
            for event in group["events"])
        rendered_log_groups.append(
            f'<details class="log-day"><summary><span>{html.escape(_detail_date_label(group["date"]))}</span>'
            f'<strong>{html.escape(_detail_value(group["value"], kind))}</strong><small>{len(group["events"])} {"session" if len(group["events"]) == 1 else "sessioner"}</small>'
            f'</summary><ul>{event_rows}</ul></details>')
    logs_html = "".join(rendered_log_groups) or '<p class="detail-empty">Inga loggar ännu.</p>'

    return f'''<!doctype html><html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#f4f2ed"><title>{habit_name} · TickStone</title><link rel="stylesheet" href="/assets/styles.css"><script src="/assets/detail-chart.js" defer></script></head>
<body class="statistics-app rich-habit-page"><a class="skip-link" href="#main-content">Hoppa till innehåll</a><div class="workspace-shell rich-detail-shell">
<header class="workspace-brand"><a href="/">{_stat_icon("check")}<strong>TickStone</strong></a><span>Din rytm, samlad.</span></header>
<main id="main-content" class="detail-workspace rich-detail-workspace">
<header class="rich-detail-header"><div><a class="back-link" href="/">← Alla vanor</a><h1>{habit_name}</h1><p>{type_label}</p></div><div class="rich-detail-controls"><nav class="period-switcher" aria-label="Period">{tabs}</nav><span class="detail-date">{_stat_icon("calendar")}{html.escape(period_date_label)}</span></div></header>
<section class="detail-hero" aria-label="Huvudresultat och jämförelser">
<article class="detail-result-card"><span class="detail-icon large">{_stat_icon("clock" if kind == "time" else "check")}</span><div class="result-total"><strong>{html.escape(hero_total)}</strong><small>{period_label}</small></div><div class="result-comparisons">{comparison_html}</div></article>
<article class="detail-rhythm-card"><span class="detail-icon large">{_stat_icon("trend")}</span><div><strong>{html.escape(trend["title"])}</strong><small>{html.escape(trend["text"])}</small></div></article>
<article class="detail-milestone-card{milestone_class}"><span class="detail-icon large trophy">{_stat_icon("history")}</span><div><strong>{html.escape(milestone_text)}</strong><small>Personligt rekord</small></div></article>
</section>
<section class="detail-kpis" aria-label="Fyra nyckeltal">{kpi_html}</section>
<div class="detail-main-grid">
<section class="dashboard-card rich-chart-card" aria-labelledby="development-title"><header><h2 id="development-title">Utveckling</h2><div class="detail-chart-mode" role="group" aria-label="Tidsupplösning"><button class="selected" data-chart-mode="day" aria-pressed="true">Dag</button><button data-chart-mode="week" aria-pressed="false">Vecka</button><button data-chart-mode="month" aria-pressed="false">Månad</button></div><div class="chart-type-switch" role="group" aria-label="Diagramtyp"><button type="button" class="selected" data-detail-chart-type="bar" aria-pressed="true">Staplar</button><button type="button" data-detail-chart-type="line" aria-pressed="false">Linje</button></div></header><div id="detail-chart" class="rich-detail-chart" data-habit-id="{habit["id"]}" data-value-kind="{kind}" data-y-label="{"Tid" if kind == "time" else "Tillfällen"}" data-chart-modes="{chart_data}" role="img" aria-label="Faktisk aktivitet" aria-describedby="detail-chart-data"></div><ul id="detail-chart-data" class="sr-only">{initial_chart_items}</ul><noscript><div class="chart-data-fallback"><strong>Aktivitet per dag</strong><ul>{initial_chart_items}</ul></div></noscript><footer class="chart-insight"><strong>{html.escape(trend["title"])}</strong><span>{html.escape(trend["text"])}</span></footer><div class="chart-period-facts"><span><small>Veckoförändring</small><strong class="compare-{comparisons["week"]["tone"]}">{html.escape(comparisons["week"]["display"])}</strong></span><span><small>Bästa vecka</small><strong>{html.escape(best_chart_label)} · {html.escape(_detail_value(best_chart_period["value"], kind))}</strong></span><span><small>Lugnaste aktiva vecka</small><strong>{html.escape(weakest_chart_label)} · {html.escape(_detail_value(weakest_chart_period["value"], kind))}</strong></span></div></section>
<details class="dashboard-card rich-records-card mobile-collapsible" open><summary><h2>Personliga rekord</h2></summary><ul>{records_html}</ul><footer>Senaste rekord: <strong>{html.escape(str(latest_record))}</strong>{f'<span>{html.escape(milestone_text)}</span>' if milestone else ''}</footer></details>
</div>
<div class="detail-lower-grid">
<details class="dashboard-card patterns-card mobile-collapsible" open><summary><h2>Dina mönster</h2></summary><ul>{patterns_html}</ul></details>
<section class="dashboard-card habit-calendar-card"><h2>Aktivitet</h2><div class="habit-calendar-head">{"".join(f"<span>{label}</span>" for label in DAY_LABELS)}</div><div class="habit-calendar-body"><div class="habit-week-labels">{calendar_weeks}</div><div class="habit-calendar-grid">{calendar_cells}</div></div><div id="habit-day-detail" class="habit-day-detail" aria-live="polite"><strong>Välj en dag</strong><span>Total, sessioner och klockslag visas här.</span></div></section>
<details class="dashboard-card detail-logs-card mobile-collapsible" open><summary><h2>Senaste loggar</h2></summary><div class="log-groups">{logs_html}</div><p class="read-only-note">Historiken är skrivskyddad. Rättningar görs inte från dashboarden för att skydda råloggen.</p></details>
</div></main></div></body></html>'''


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
                elif path in ("/assets/styles.css", "/assets/app.js", "/assets/detail-chart.js"):
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
