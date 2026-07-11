#!/usr/bin/env python3
import argparse
import json
import re
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tickstone_usb import SerialLine, find_port, get_config


WEB_ROOT = Path(__file__).with_name("tickstone_settings_web")
CODE_RE = re.compile(r"^[A-Z0-9]{1,3}$")
NAME_RE = re.compile(r"^[A-Z0-9 ]{1,15}$")
MODES = {"count": (0, "c"), "time": (1, "t")}


def validate_habits(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 10:
        raise ValueError("Du maste ha mellan 1 och 10 habits.")
    clean = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Ogiltig habit.")
        ident = item.get("id")
        if type(ident) is not int or not 0 <= ident < 10 or ident in seen:
            raise ValueError("Varje habit maste ha en unik plats mellan 1 och 10.")
        seen.add(ident)
        code = str(item.get("code", "")).strip().upper()
        name = " ".join(str(item.get("name", "")).strip().upper().split())
        mode = item.get("mode")
        if not CODE_RE.fullmatch(code):
            raise ValueError(f"Habit {ident + 1}: koden ska vara 1-3 tecken, A-Z eller 0-9.")
        if not NAME_RE.fullmatch(name):
            raise ValueError(f"Habit {ident + 1}: namnet ska vara 1-15 tecken, A-Z, 0-9 eller mellanslag.")
        if mode not in MODES:
            raise ValueError(f"Habit {ident + 1}: okand typ.")
        minutes = item.get("minutes", 1)
        if type(minutes) is not int or not 1 <= minutes <= 99:
            raise ValueError(f"Habit {ident + 1}: tiden ska vara 1-99 minuter.")
        clean.append({"id": ident, "code": code, "name": name, "mode": mode,
                      "minutes": 1 if mode == "count" else minutes})
    return sorted(clean, key=lambda habit: habit["id"])


def encode_habits(habits):
    fields = []
    for habit in validate_habits(habits):
        _, wire_mode = MODES[habit["mode"]]
        ident = habit["id"]
        fields.extend(((f"n{ident}", habit["code"]), (f"f{ident}", habit["name"]),
                       (f"t{ident}", wire_mode), (f"d{ident}", str(habit["minutes"]))))
    return urllib.parse.urlencode(fields)


def habits_from_device(habits):
    names = {0: "count", 1: "time", 2: "time"}
    return [{"id": habit["id"], "code": habit["code"], "name": habit["name"],
             "mode": names[habit["mode"]], "minutes": habit["minutes"]} for habit in habits]


class USBDevice:
    def __init__(self, explicit_port=None):
        self.explicit_port = explicit_port
        self.serial = None
        self.port = None
        self.lock = threading.Lock()

    def _close(self):
        if self.serial is not None:
            self.serial.close()
        self.serial = None

    def _connect(self):
        self._close()
        self.port = find_port(self.explicit_port)
        self.serial = SerialLine(self.port)
        time.sleep(2)
        for attempt in range(3):
            self.serial.write(f"TS1 TIME {int(time.time())}")
            try:
                self.serial.response(timeout=3)
                return
            except RuntimeError:
                if attempt == 2:
                    raise
                time.sleep(0.5)

    def _run(self, operation):
        with self.lock:
            for attempt in range(2):
                try:
                    if self.serial is None:
                        self._connect()
                    return operation(self.serial)
                except (OSError, RuntimeError):
                    self._close()
                    if attempt:
                        raise RuntimeError("Kunde inte kommunicera med TickStone via USB.")

    def read(self):
        return self._run(lambda serial: habits_from_device(get_config(serial)))

    def write(self, habits):
        clean = validate_habits(habits)

        def operation(serial):
            serial.write("TS1 SET " + encode_habits(clean))
            lines = serial.response()
            if "@TS1 OK CONFIG" not in lines:
                raise RuntimeError("TickStone avvisade installningarna.")
            stored = habits_from_device(get_config(serial))
            if stored != clean:
                raise RuntimeError("Installningarna kunde inte verifieras efter skrivning.")
            return stored

        return self._run(operation)

    def sync(self):
        def operation(serial):
            serial.write("TS1 SYNC")
            if "@TS1 OK SYNC" not in serial.response():
                raise RuntimeError("TickStone kunde inte starta Bluetooth-synk.")
        self._run(operation)


def make_handler(device, token):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TickStoneSettings/1"

        def log_message(self, format_string, *args):
            return

        def _json(self, status, payload):
            body = json.dumps(payload, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status, error):
            self._json(status, {"error": str(error)})

        def _authorized(self):
            return secrets.compare_digest(self.headers.get("X-TickStone-Token", ""), token)

        def _read_json(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as error:
                raise ValueError("Ogiltig forfragan.") from error
            if not 0 < length <= 16384:
                raise ValueError("Ogiltig datamangd.")
            try:
                return json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("Ogiltig JSON.") from error

        def do_GET(self):
            if self.path == "/api/config":
                try:
                    self._json(200, {"habits": device.read(), "token": token,
                                     "port": device.port})
                except (OSError, RuntimeError, SystemExit) as error:
                    self._error(503, error)
                return
            files = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/styles.css": ("styles.css", "text/css; charset=utf-8"),
                     "/app.js": ("app.js", "text/javascript; charset=utf-8")}
            item = files.get(self.path)
            if item is None:
                self.send_error(404)
                return
            body = (WEB_ROOT / item[0]).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", item[1])
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_PUT(self):
            if self.path != "/api/config":
                self.send_error(404)
                return
            if not self._authorized():
                self._error(403, "Sessionen ar inte giltig. Ladda om sidan.")
                return
            try:
                payload = self._read_json()
                self._json(200, {"habits": device.write(payload.get("habits"))})
            except (AttributeError, ValueError) as error:
                self._error(400, error)
            except (OSError, RuntimeError, SystemExit) as error:
                self._error(503, error)

        def do_POST(self):
            if self.path != "/api/sync":
                self.send_error(404)
                return
            if not self._authorized():
                self._error(403, "Sessionen ar inte giltig. Ladda om sidan.")
                return
            try:
                device.sync()
                self._json(200, {"ok": True})
            except (OSError, RuntimeError, SystemExit) as error:
                self._error(503, error)

    return Handler


def create_server(device, host="127.0.0.1", port=8787):
    token = secrets.token_urlsafe(24)
    return ThreadingHTTPServer((host, port), make_handler(device, token))


def main():
    parser = argparse.ArgumentParser(description="TickStone-installningar i webblasaren")
    parser.add_argument("--serial", help="USB-port, exempelvis /dev/cu.usbmodem21201")
    parser.add_argument("--port", type=int, default=8787, help="lokal webbport")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = create_server(USBDevice(args.serial), port=args.port)
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"TickStone-installningar: {url}")
    print("Avsluta med Ctrl+C.")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
