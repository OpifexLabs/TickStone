#!/usr/bin/env python3
"""Configure Linux's initial BLE connection supervision timeout."""

import time
from pathlib import Path

BLUETOOTH_DEBUGFS = Path("/sys/kernel/debug/bluetooth")
SUPERVISION_TIMEOUT_UNITS = 600
CONTROL_WAIT_SECONDS = 15


def controls(root=BLUETOOTH_DEBUGFS):
    return sorted(root.glob("hci*/supervision_timeout"))


def configure(root=BLUETOOTH_DEBUGFS):
    timeout_controls = controls(root)
    if not timeout_controls:
        raise RuntimeError(f"no Bluetooth supervision_timeout controls found under {root}")

    expected = f"{SUPERVISION_TIMEOUT_UNITS}\n"
    for control in timeout_controls:
        control.write_text(expected, encoding="ascii")
        actual = control.read_text(encoding="ascii").strip()
        if actual != str(SUPERVISION_TIMEOUT_UNITS):
            raise RuntimeError(f"{control} read back {actual}, expected {SUPERVISION_TIMEOUT_UNITS}")
    return timeout_controls


def wait_and_configure(root=BLUETOOTH_DEBUGFS):
    deadline = time.monotonic() + CONTROL_WAIT_SECONDS
    while not controls(root):
        if time.monotonic() >= deadline:
            raise RuntimeError(f"no Bluetooth supervision_timeout controls found under {root}")
        time.sleep(0.25)
    return configure(root)


def main():
    configured = wait_and_configure()
    milliseconds = SUPERVISION_TIMEOUT_UNITS * 10
    print(f"Configured initial BLE supervision timeout to {milliseconds} ms: " + ", ".join(map(str, configured)))


if __name__ == "__main__":
    main()
