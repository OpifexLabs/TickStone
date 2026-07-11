#!/usr/bin/env python3
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from tickstone_settings import create_server, encode_habits, validate_habits


HABITS = [{"id": 0, "code": "STR", "name": "STRACKA", "mode": "count", "minutes": 1},
          {"id": 4, "code": "MED", "name": "MEDITATION", "mode": "time", "minutes": 10}]


class FakeDevice:
    port = "/dev/fake"

    def __init__(self):
        self.habits = HABITS
        self.synced = False

    def read(self):
        return self.habits

    def write(self, habits):
        self.habits = validate_habits(habits)
        return self.habits

    def sync(self):
        self.synced = True


def api(url, method="GET", data=None, token=None):
    headers = {}
    if data is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(data).encode()
    if token:
        headers["X-TickStone-Token"] = token
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request) as response:
        return response.status, json.load(response)


def main():
    assert validate_habits([{"id": 9, "code": "a1", "name": "  Test   Habit ",
                             "mode": "time", "minutes": 25}])[0] == {
        "id": 9, "code": "A1", "name": "TEST HABIT", "mode": "time", "minutes": 25}
    assert "n4=MED" in encode_habits(HABITS) and "t4=t" in encode_habits(HABITS)
    invalid_values = ([], HABITS + [HABITS[0]],
                      [{"id": 0, "code": "Å", "name": "TEST", "mode": "count", "minutes": 1}],
                      [{"id": 0, "code": "OK", "name": "TEST", "mode": "time", "minutes": 0}],
                      [{"id": 0, "code": "OK", "name": "TEST", "mode": "time", "minutes": 100}])
    for invalid in invalid_values:
        try:
            validate_habits(invalid)
            raise AssertionError("invalid config accepted")
        except ValueError:
            pass

    device = FakeDevice()
    server = create_server(device, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, config = api(base + "/api/config")
        assert status == 200 and config["habits"] == HABITS and config["port"] == "/dev/fake"
        try:
            api(base + "/api/config", "PUT", {"habits": HABITS})
            raise AssertionError("write without token accepted")
        except urllib.error.HTTPError as error:
            assert error.code == 403
        changed = [dict(HABITS[0], name="RORELSE")]
        status, saved = api(base + "/api/config", "PUT", {"habits": changed}, config["token"])
        assert status == 200 and saved["habits"] == changed and device.habits == changed
        status, _ = api(base + "/api/sync", "POST", token=config["token"])
        assert status == 200 and device.synced
        with urllib.request.urlopen(base + "/") as response:
            assert b"TickStone" in response.read()
            assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print("tickstone_settings_test: OK")


if __name__ == "__main__":
    main()
