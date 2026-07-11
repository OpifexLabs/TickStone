#!/usr/bin/env python3
import argparse
import asyncio
import struct
import time
from pathlib import Path

from tickstone_store import IngestResult, append_raw_once, ingest_event

try:
    from bleak import BleakClient, BleakScanner
    from bleak.exc import BleakError
except ImportError as error:
    raise SystemExit("Installera BLE-stod: python3 -m pip install bleak") from error

SERVICE_UUID = "7e570000-7a1b-4c2d-9e10-000000000001"
DATA_UUID = "7e570000-7a1b-4c2d-9e10-000000000002"
CONTROL_UUID = "7e570000-7a1b-4c2d-9e10-000000000003"


def decode(packet):
    if len(packet) != 34 or packet[0] != 1:
        raise ValueError("Okant TickStone-paket")
    if not packet[1] & 1:
        return None
    ident, started, ended, duration, count = struct.unpack_from("<QqqIH", packet, 4)
    return {
        "id": ident,
        "habit_id": packet[3],
        "type": "count" if packet[2] == 0 else "time",
        "started_at": started,
        "ended_at": ended,
        "duration_seconds": duration,
        "count": count,
        "deleted": bool(packet[1] & 2),
    }


def persist_event(path, log, database=None):
    if database is not None:
        return ingest_event(path, database, log)
    return IngestResult(append_raw_once(path, log), False)


async def sync(output, database=None, attempts=3):
    device = None
    for attempt in range(attempts):
        device = await BleakScanner.find_device_by_filter(
            lambda candidate, advertisement: (
                candidate.name == "TickStone"
                or advertisement.local_name == "TickStone"
                or SERVICE_UUID in advertisement.service_uuids
            ),
            timeout=10,
        )
        if device:
            break
        if attempt + 1 < attempts:
            await asyncio.sleep(2)
    if not device:
        return False
    async with BleakClient(device) as client:
        await client.write_gatt_char(CONTROL_UUID, b"\x01" + struct.pack("<Q", int(time.time())), response=True)
        synced = 0
        while True:
            log = decode(bytes(await client.read_gatt_char(DATA_UUID)))
            if log is None:
                break
            persist_event(output, log, database)
            await client.write_gatt_char(CONTROL_UUID, b"\x02" + struct.pack("<Q", log["id"]), response=True)
            synced += 1
            await asyncio.sleep(0.35)
        print(f"Synk klar: {synced} loggar, fil: {output}")
    return True


async def watch(output, database=None):
    print("Vantar pa TickStone. Avsluta med Ctrl+C.")
    while True:
        try:
            if await sync(output, database, attempts=1):
                await asyncio.sleep(5)
        except (BleakError, TimeoutError, OSError, ValueError) as error:
            print(f"Synk misslyckades, forsoker igen: {error}")
        await asyncio.sleep(2)


def main():
    parser = argparse.ArgumentParser(description="Synka TickStone-loggar via Bluetooth LE")
    parser.add_argument("--output", type=Path, default=Path.home() / "tickstone-logs.jsonl")
    parser.add_argument("--database", type=Path, help="SQLite-databas for strukturerad historik")
    parser.add_argument("--watch", action="store_true", help="vanta kontinuerligt pa nya loggar")
    args = parser.parse_args()
    output = args.output.expanduser()
    database = args.database.expanduser() if args.database else None
    if args.watch:
        try:
            asyncio.run(watch(output, database))
        except KeyboardInterrupt:
            pass
    elif not asyncio.run(sync(output, database)):
        raise SystemExit("Hittade ingen TickStone via Bluetooth")


if __name__ == "__main__":
    main()
