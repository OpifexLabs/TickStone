#!/usr/bin/env python3
import argparse
import glob
import os
import select
import termios
import time
import urllib.parse


def find_port(explicit):
    if explicit:
        return explicit
    ports = sorted(glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/ttyACM*"))
    if len(ports) != 1:
        raise SystemExit("Ange --port; hittade: " + ", ".join(ports))
    return ports[0]


class SerialLine:
    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attrs = termios.tcgetattr(self.fd)
        attrs[0] = attrs[0] & ~(termios.IXON | termios.IXOFF | termios.ICRNL)
        attrs[1] = attrs[1] & ~termios.OPOST
        attrs[2] = attrs[2] | termios.CLOCAL | termios.CREAD
        attrs[3] = 0
        attrs[4] = termios.B115200
        attrs[5] = termios.B115200
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        self.buffer = b""

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def write(self, text):
        os.write(self.fd, (text + "\n").encode())

    def response(self, timeout=5):
        deadline = time.monotonic() + timeout
        lines = []
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self.fd], [], [], 0.2)
            if not ready:
                continue
            self.buffer += os.read(self.fd, 4096)
            while b"\n" in self.buffer:
                raw, self.buffer = self.buffer.split(b"\n", 1)
                line = raw.decode(errors="replace").strip()
                if line.startswith("@TS1 "):
                    lines.append(line)
                    if line in ("@TS1 END", "@TS1 OK CONFIG", "@TS1 OK TIME", "@TS1 OK SYNC") or line.startswith("@TS1 ERROR"):
                        return lines
        raise RuntimeError("TickStone svarade inte via USB")


def get_config(serial):
    lines = None
    for _ in range(3):
        serial.write("TS1 GET")
        try:
            lines = serial.response(timeout=3)
            break
        except RuntimeError:
            time.sleep(0.5)
    if lines is None:
        raise RuntimeError("TickStone svarade inte via USB")
    habits = []
    for line in lines:
        if line.startswith("@TS1 HABIT "):
            _, _, ident, code, mode, minutes, name = line.split(" ", 6)
            habits.append({"id": int(ident), "code": code, "mode": int(mode), "minutes": int(minutes), "name": name})
    return habits


def configure(serial):
    current = {habit["id"]: habit for habit in get_config(serial)}
    print("Skriv - som kod for att ta bort platsen. Tryck Enter for att behalla nuvarande varde.")
    values = []
    for ident in range(10):
        old = current.get(ident, {"code": "", "name": "", "mode": 0, "minutes": 5})
        code = input(f"Habit {ident + 1} kod [{old['code']}]: ").strip().upper()
        if code == "-":
            continue
        if code == "" and old["code"]:
            code = old["code"]
        if not code:
            continue
        name = input(f"  Namn [{old['name']}]: ").strip().upper() or old["name"] or code
        current_mode = 0 if old["mode"] == 0 else 1
        mode_text = input(f"  Typ 0=tillfalle, 1=tid [{current_mode}]: ").strip()
        mode = int(mode_text) if mode_text else current_mode
        if mode not in (0, 1):
            raise SystemExit("Typ maste vara 0 eller 1")
        minute_text = input(f"  Standardminuter [{old['minutes']}]: ").strip()
        minutes = int(minute_text) if minute_text else old["minutes"]
        values.extend([(f"n{ident}", code), (f"f{ident}", name), (f"t{ident}", "c" if mode == 0 else "t"), (f"d{ident}", str(minutes))])
    serial.write("TS1 SET " + urllib.parse.urlencode(values))
    print("\n".join(serial.response()))


def main():
    parser = argparse.ArgumentParser(description="Konfigurera TickStone via USB")
    parser.add_argument("command", choices=("show", "configure", "sync"))
    parser.add_argument("--port")
    args = parser.parse_args()
    serial = SerialLine(find_port(args.port))
    time.sleep(2.0)
    for _ in range(3):
        serial.write(f"TS1 TIME {int(time.time())}")
        try:
            serial.response(timeout=3)
            break
        except RuntimeError:
            time.sleep(0.5)
    else:
        raise SystemExit("TickStone svarade inte via USB")
    if args.command == "show":
        for habit in get_config(serial):
            print(f"{habit['id'] + 1}: {habit['code']}  {habit['name']}  type={habit['mode']}  min={habit['minutes']}")
    elif args.command == "configure":
        configure(serial)
    else:
        serial.write("TS1 SYNC")
        print("\n".join(serial.response()))


if __name__ == "__main__":
    main()
