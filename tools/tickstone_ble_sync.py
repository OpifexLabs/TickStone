#!/usr/bin/env python3
import argparse
import asyncio
import struct
import time
import zlib
from pathlib import Path

from tickstone_store import IngestResult, append_raw_once, ingest_event, record_habits

try:
    from bleak import BleakClient, BleakScanner
    from bleak.exc import BleakError
except ImportError as error:
    raise SystemExit("Installera BLE-stod: python3 -m pip install bleak") from error

SERVICE_UUID = "7e570000-7a1b-4c2d-9e10-000000000001"
DATA_UUID = "7e570000-7a1b-4c2d-9e10-000000000002"
CONTROL_UUID = "7e570000-7a1b-4c2d-9e10-000000000003"
CONFIG_UUID = "7e570000-7a1b-4c2d-9e10-000000000004"
CONFIG_PACKET_SIZE = 28
CONFIG_VERSION = 1


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


def persist_event(path, log, database=None, snapshot_id=None):
    if database is not None:
        return ingest_event(path, database, log, snapshot_id=snapshot_id)
    return IngestResult(append_raw_once(path, log), False)


def decode_config_header(packet):
    if len(packet) != CONFIG_PACKET_SIZE or packet[0] != CONFIG_VERSION or packet[1] != 0:
        raise ValueError("unsupported TickStone config header")
    record_count, active_count, content_hash = packet[2], packet[3], struct.unpack_from("<I", packet, 4)[0]
    if record_count != 10 or active_count > record_count or any(packet[8:]):
        raise ValueError("invalid TickStone config header")
    return {"version": packet[0], "record_count": record_count,
            "active_count": active_count, "hash": content_hash}


def decode_config_record(packet, expected_slot):
    if len(packet) != CONFIG_PACKET_SIZE or packet[0] != CONFIG_VERSION or packet[1] != 1:
        raise ValueError("unsupported TickStone config record")
    slot, active, mode, code_length, name_length = packet[2:7]
    minutes = struct.unpack_from("<H", packet, 8)[0]
    if slot != expected_slot or active not in (0, 1) or mode not in (0, 1) or code_length > 3 or name_length > 15:
        raise ValueError("invalid TickStone config record")
    if packet[7] != 0 or not 1 <= minutes <= 99:
        raise ValueError("invalid TickStone config values")
    if any(packet[10 + code_length:13]) or any(packet[13 + name_length:28]):
        raise ValueError("non-canonical TickStone config padding")
    try:
        code = packet[10:10 + code_length].decode("ascii")
        name = packet[13:13 + name_length].decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError("invalid TickStone config text") from error
    if active and (not code or not name):
        raise ValueError("active TickStone habit has no identity")
    if any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" for character in code):
        raise ValueError("invalid TickStone habit code")
    if any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 " for character in name):
        raise ValueError("invalid TickStone habit name")
    return {"id": slot, "code": code, "name": name,
            "mode": "count" if mode == 0 else "time", "minutes": minutes,
            "active": bool(active), "_hash_bytes": packet[2:]}


def decode_config_snapshot(header_packet, record_packets):
    header = decode_config_header(header_packet)
    if len(record_packets) != header["record_count"]:
        raise ValueError("incomplete TickStone config snapshot")
    records = [decode_config_record(packet, slot) for slot, packet in enumerate(record_packets)]
    if sum(record["active"] for record in records) != header["active_count"]:
        raise ValueError("TickStone config active count mismatch")
    content = b"".join(record.pop("_hash_bytes") for record in records)
    if zlib.crc32(content) & 0xFFFFFFFF != header["hash"]:
        raise ValueError("TickStone config hash mismatch")
    header["habits"] = records
    return header


async def read_config(client):
    await client.write_gatt_char(CONTROL_UUID, b"\x03\x00", response=True)
    header = bytes(await client.read_gatt_char(CONFIG_UUID))
    parsed = decode_config_header(header)
    records = []
    for page in range(1, parsed["record_count"] + 1):
        await client.write_gatt_char(CONTROL_UUID, bytes((3, page)), response=True)
        records.append(bytes(await client.read_gatt_char(CONFIG_UUID)))
    return decode_config_snapshot(header, records)


async def sync_client(client, output, database=None, synced_at=None, persist=persist_event):
    synced_at = int(time.time()) if synced_at is None else int(synced_at)
    await client.write_gatt_char(CONTROL_UUID, b"\x01" + struct.pack("<Q", synced_at), response=True)
    snapshot_id = None
    try:
        config = await read_config(client)
        if database is not None:
            snapshot_id = record_habits(
                database, config["habits"], valid_from=synced_at,
                device_hash=f'{config["hash"]:08x}', protocol_version=config["version"])
    except (BleakError, ValueError) as error:
        print(f"Config ej tillganglig, loggsynk fortsatter: {error}")
    synced = 0
    while True:
        log = decode(bytes(await client.read_gatt_char(DATA_UUID)))
        if log is None:
            break
        persist(output, log, database, snapshot_id=snapshot_id)
        await client.write_gatt_char(CONTROL_UUID, b"\x02" + struct.pack("<Q", log["id"]), response=True)
        synced += 1
        await asyncio.sleep(0.35)
    return synced


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
        synced = await sync_client(client, output, database)
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
