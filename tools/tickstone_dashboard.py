#!/usr/bin/env python3
"""Read-only local web dashboard for TickStone history."""

import argparse
import html
import json
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

WEB_ROOT = Path(__file__).with_name("tickstone_dashboard_web")
STOCKHOLM = ZoneInfo("Europe/Stockholm")
SWEDISH_MONTHS = (
    "januari", "februari", "mars", "april", "maj", "juni",
    "juli", "augusti", "september", "oktober", "november", "december",
)
DAY_LABELS = ("M", "T", "O", "T", "F", "L", "S")


def _readonly_connection(database):
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _format_when(epoch, today):
    local = datetime.fromtimestamp(epoch, timezone.utc).astimezone(STOCKHOLM)
    if local.date() == today:
        prefix = "Idag"
    elif local.date() == today - timedelta(days=1):
        prefix = "Igår"
    else:
        prefix = f"{local.day} {SWEDISH_MONTHS[local.month - 1][:3]}"
    return f"{prefix} {local:%H:%M}"


def _habit_name(row):
    return row["name"] or f"Habit {row['habit_id'] + 1}"


def build_dashboard(database, now_epoch=None):
    now_epoch = int(datetime.now(timezone.utc).timestamp()) if now_epoch is None else int(now_epoch)
    now = datetime.fromtimestamp(now_epoch, timezone.utc).astimezone(STOCKHOLM)
    today = (now - timedelta(hours=5)).date()
    first_day = today - timedelta(days=6)
    with _readonly_connection(database) as connection:
        rows = connection.execute(
            """SELECT e.id, e.habit_id, e.type, e.started_at, e.duration_seconds,
                      e.count, e.tickstone_day, h.code, h.name
                 FROM events e LEFT JOIN habits h ON h.slot_id=e.habit_id
                WHERE e.deleted=0 ORDER BY e.started_at DESC, e.id DESC"""
        ).fetchall()

    weekly = [row for row in rows if first_day.isoformat() <= row["tickstone_day"] <= today.isoformat()]
    daily_counts = defaultdict(int)
    for row in weekly:
        daily_counts[row["tickstone_day"]] += 1
    peak = max(daily_counts.values(), default=1)
    days = []
    for offset in range(7):
        current = first_day + timedelta(days=offset)
        value = daily_counts[current.isoformat()]
        days.append({
            "date": current.isoformat(),
            "label": DAY_LABELS[current.weekday()],
            "value": value,
            "height": 8 if value == 0 else max(22, round(value / peak * 100)),
            "today": current == today,
        })

    per_habit = {}
    for row in rows:
        item = per_habit.setdefault(row["habit_id"], {
            "id": row["habit_id"], "name": _habit_name(row), "code": row["code"] or "",
            "total": 0, "minutes": 0, "seconds": 0, "sessions": 0,
        })
        item["sessions"] += 1
        if row["type"] == "count":
            item["total"] += row["count"]
        else:
            item["seconds"] += row["duration_seconds"]
            item["minutes"] = round(item["seconds"] / 60)
    habits = sorted(per_habit.values(), key=lambda item: (-item["sessions"], item["id"]))
    for item in habits:
        if item["total"]:
            item["display_value"], item["display_unit"] = item["total"], "gånger"
        elif item["seconds"] < 60:
            item["display_value"], item["display_unit"] = item["seconds"], "sekunder"
        else:
            item["display_value"], item["display_unit"] = item["minutes"], "minuter"

    active_days = {row["tickstone_day"] for row in rows}
    streak = 0
    cursor = today
    while cursor.isoformat() in active_days:
        streak += 1
        cursor -= timedelta(days=1)

    recent = []
    for row in rows[:8]:
        if row["type"] == "count":
            kind = f"{row['count']} gång" if row["count"] == 1 else f"{row['count']} gånger"
        else:
            seconds = row["duration_seconds"]
            kind = f"{seconds} sek" if seconds < 60 else f"{round(seconds / 60)} min"
        recent.append({
            "id": row["id"], "name": _habit_name(row), "kind": kind,
            "when": _format_when(row["started_at"], now.date()),
        })

    return {
        "generated_at": f"{now.day} {SWEDISH_MONTHS[now.month - 1]} {now:%Y %H:%M}",
        "summary": {
            "today": daily_counts[today.isoformat()],
            "week": len(weekly),
            "minutes": round(sum(row["duration_seconds"] for row in weekly if row["type"] == "time") / 60),
            "streak": streak,
        },
        "days": days,
        "habits": habits,
        "recent": recent,
    }


def render_dashboard(model):
    summary = model["summary"]
    cards = (
        ("Idag", summary["today"], "aktiviteter"),
        ("Den här veckan", summary["week"], "aktiviteter"),
        ("Fokustid", summary["minutes"], "minuter"),
        ("Följd", summary["streak"], "dagar"),
    )
    cards_html = "".join(
        f'<article class="metric"><span>{html.escape(label)}</span><strong>{value}</strong><small>{unit}</small></article>'
        for label, value, unit in cards
    )
    days_html = "".join(
        f'<div class="day{" is-today" if day.get("today") else ""}" aria-label="{day.get("date", day["label"])}: {day["value"]} aktiviteter">'
        f'<div class="bar-track"><div class="bar" style="--height:{day["height"]}%"></div></div>'
        f'<span>{html.escape(day["label"])}</span></div>' for day in model["days"]
    )
    if model["habits"]:
        habits_html = "".join(
            '<li class="habit-row"><div class="habit-mark" aria-hidden="true"></div><div class="habit-copy">'
            f'<strong>{html.escape(item["name"].title())}</strong><span>{html.escape(item["code"])}</span></div>'
            f'<div class="habit-value"><strong>{item["display_value"]}</strong>'
            f'<span>{item["display_unit"]}</span></div></li>'
            for item in model["habits"]
        )
    else:
        habits_html = '<li class="empty">Dina habits visas här efter första synken.</li>'
    if model["recent"]:
        recent_html = "".join(
            '<li class="recent-row"><div><strong>' + html.escape(item["name"].title()) + '</strong>'
            f'<span>{html.escape(item["kind"])}</span></div><time>{html.escape(item["when"])}</time></li>'
            for item in model["recent"]
        )
    else:
        recent_html = '<li class="empty">Ingen aktivitet ännu. Logga något på TickStone.</li>'

    return f"""<!doctype html>
<html lang="sv">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta name="theme-color" content="#f4f2ed">
  <title>TickStone</title>
  <link rel="stylesheet" href="/assets/styles.css">
  <script src="/assets/app.js" defer></script>
</head>
<body>
  <a class="skip-link" href="#content">Hoppa till innehåll</a>
  <main id="content" class="shell">
    <header class="topbar">
      <div class="brand"><span class="brand-stone" aria-hidden="true"></span><div><strong>TickStone</strong><span>Din rytm, samlad.</span></div></div>
      <div class="sync-state" aria-label="Synkstatus"><span aria-hidden="true"></span>Synkad <time id="updated">{html.escape(model["generated_at"])}</time></div>
    </header>

    <section class="intro" aria-labelledby="overview-title">
      <p class="eyebrow">ÖVERSIKT</p>
      <h1 id="overview-title">Små steg.<br><em>Synliga framsteg.</em></h1>
    </section>

    <section class="metrics" aria-label="Sammanfattning">{cards_html}</section>

    <div class="dashboard-grid">
      <section class="panel activity-panel" aria-labelledby="activity-title">
        <div class="panel-heading"><div><p class="eyebrow">SENASTE 7 DAGARNA</p><h2 id="activity-title">Aktivitet</h2></div><span>{summary["week"]} totalt</span></div>
        <div class="chart" role="img" aria-label="Aktiviteter per dag">{days_html}</div>
      </section>

      <section class="panel habits-panel" aria-labelledby="habits-title">
        <div class="panel-heading"><div><p class="eyebrow">ALLA HABITS</p><h2 id="habits-title">Vanor</h2></div></div>
        <ul class="habit-list">{habits_html}</ul>
      </section>

      <section class="panel recent-panel" aria-labelledby="recent-title">
        <div class="panel-heading"><div><p class="eyebrow">HISTORIK</p><h2 id="recent-title">Senaste aktivitet</h2></div></div>
        <ul class="recent-list">{recent_html}</ul>
      </section>
    </div>
    <footer><span>TickStone</span><span>Data stannar på din Pi.</span></footer>
  </main>
</body>
</html>"""


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_handler(database):
    database = Path(database)

    class Handler(BaseHTTPRequestHandler):
        server_version = "TickStoneDashboard/1"

        def log_message(self, format, *args):
            return

        def _send(self, status, content_type, body=b"", head=False, extra_headers=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            for key, value in (extra_headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def _route(self, head=False):
            path = urlsplit(self.path).path
            if path == "/":
                body = render_dashboard(build_dashboard(database)).encode()
                self._send(200, "text/html; charset=utf-8", body, head)
            elif path == "/healthz":
                try:
                    with _readonly_connection(database) as connection:
                        connection.execute("SELECT 1").fetchone()
                    body = b'{"status":"ok"}\n'
                    self._send(200, "application/json; charset=utf-8", body, head)
                except sqlite3.Error:
                    self._send(503, "application/json; charset=utf-8", b'{"status":"error"}\n', head)
            elif path in ("/assets/styles.css", "/assets/app.js"):
                name = path.rsplit("/", 1)[1]
                content_type = "text/css; charset=utf-8" if name.endswith(".css") else "text/javascript; charset=utf-8"
                self._send(200, content_type, (WEB_ROOT / name).read_bytes(), head)
            else:
                self._send(404, "text/plain; charset=utf-8", b"Not found\n", head)

        def do_GET(self):
            self._route()

        def do_HEAD(self):
            self._route(head=True)

        def _method_not_allowed(self):
            self._send(405, "text/plain; charset=utf-8", b"Method not allowed\n", extra_headers={"Allow": "GET, HEAD"})

        do_POST = do_PUT = do_PATCH = do_DELETE = _method_not_allowed

    return Handler


def main():
    parser = argparse.ArgumentParser(description="TickStone lokal statistikdashboard")
    parser.add_argument("--database", type=Path, default=Path.home() / ".local/share/tickstone/tickstone.sqlite3")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8750)
    args = parser.parse_args()
    server = DashboardServer((args.host, args.port), make_handler(args.database.expanduser()))
    print(f"TickStone dashboard: http://{args.host}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
