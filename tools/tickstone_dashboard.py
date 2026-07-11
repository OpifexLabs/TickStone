#!/usr/bin/env python3
"""Read-only local web dashboard for TickStone history."""

import argparse
import html
import json
import re
import sqlite3
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


def _readonly_connection(database):
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


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


def render_habit_detail(model):
    habit = model["habit"]
    tabs = "".join(f'<a href="/habit/{habit["id"]}?period={period}" class="period-tab{" selected" if model["period"] == period else ""}"{" aria-current=page" if model["period"] == period else ""}>{label}</a>' for period, label in (("week","Vecka"),("month","Månad"),("year","År"),("all","Allt")))
    trend = model.get("trend_label") or ("Ingen jämförelse ännu" if model["trend"] is None else f'{model["trend"]:+d}% jämfört med föregående period')
    points = "".join(f'<div class="detail-point" aria-label="{html.escape(point["label"])}: {point["value"]}"><div style="--height:{point["height"]}%"></div><span>{html.escape(point["label"][-5:])}</span></div>' for point in model["points"])
    if not points:
        points = '<p class="empty">Ingen aktivitet under perioden.</p>'
    metrics = (("Totalt", model["display_value"], model["display_unit"]), ("Aktiva dagar", model["active_days"], "dagar"),
               ("Snitt", model["average_value"], model["average_unit"]), ("Längsta följd", model["longest_streak"], "dagar"))
    metric_html = "".join(f'<article class="metric"><span>{label}</span><strong>{html.escape(str(value))}</strong><small>{html.escape(unit)}</small></article>' for label,value,unit in metrics)
    return f'''<!doctype html><html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(habit["name"])} · TickStone</title><link rel="stylesheet" href="/assets/styles.css"></head><body><a class="skip-link" href="#content">Hoppa till innehåll</a><main id="content" class="shell"><header class="topbar"><a class="back-link" href="/">← Översikt</a><div class="brand"><strong>TickStone</strong></div></header><section class="detail-intro"><p class="eyebrow">{html.escape(habit["code"])}</p><h1>{html.escape(habit["name"].title())}</h1><p>{html.escape(model["period_start"])} – {html.escape(model["period_end"])}</p></section><nav class="period-tabs" aria-label="Period">{tabs}</nav><section class="metrics detail-metrics" aria-label="Habitstatistik">{metric_html}</section><section class="panel detail-chart"><div class="panel-heading"><div><p class="eyebrow">UTVECKLING</p><h2>Aktivitet</h2></div><span>{html.escape(trend)}</span></div><div class="detail-points" role="img" aria-label="Aktivitet per kalenderperiod">{points}</div><div class="detail-facts"><span>{model["sessions"]} aktivitetstillfällen</span><span>Nuvarande följd: {model["current_streak"]} dagar</span><span>Bästa period: {html.escape(model["best_period"] or "—")}</span></div></section><p class="metadata-note">{html.escape(_metadata_note(model["metadata_status"]))}</p></main></body></html>'''


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
                    self._send(200, "text/html; charset=utf-8", render_dashboard(build_dashboard(database)).encode(), head)
                elif re.fullmatch(r"/habit/[0-9]", path):
                    period = parse_qs(parsed.query).get("period", ["week"])[0]
                    if period not in PERIODS:
                        self._send(400, "text/plain; charset=utf-8", b"Invalid period\n", head); return
                    model = build_habit_detail(database, int(path[-1]), period)
                    if model is None:
                        self._send(404, "text/plain; charset=utf-8", b"Not found\n", head)
                    else:
                        self._send(200, "text/html; charset=utf-8", render_habit_detail(model).encode(), head)
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
