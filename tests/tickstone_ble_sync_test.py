#!/usr/bin/env python3
import asyncio
import struct
import sys
import types
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
if "bleak" not in sys.modules:
    bleak = types.ModuleType("bleak")
    bleak.BleakClient = object
    bleak.BleakScanner = object
    errors = types.ModuleType("bleak.exc")
    errors.BleakError = OSError
    sys.modules["bleak"] = bleak
    sys.modules["bleak.exc"] = errors

from tickstone_ble_sync import (  # noqa: E402
    CONFIG_UUID, CONTROL_UUID, DATA_UUID, decode_config_snapshot, read_config, sync_client,
)


def record(slot, active=False, mode=0, minutes=1, code="", name=""):
    packet = bytearray(28)
    packet[0:7] = bytes((1, 1, slot, int(active), mode, len(code), len(name)))
    struct.pack_into("<H", packet, 8, minutes)
    packet[10:10 + len(code)] = code.encode()
    packet[13:13 + len(name)] = name.encode()
    return bytes(packet)


def snapshot():
    records = [record(index) for index in range(10)]
    records[0] = record(0, True, 0, 1, "STR", "STRACKA")
    records[4] = record(4, True, 1, 10, "MED", "MEDITATION")
    header = bytearray(28)
    header[:4] = bytes((1, 0, 10, 2))
    struct.pack_into("<I", header, 4, zlib.crc32(b"".join(item[2:] for item in records)))
    return bytes(header), records


class FakeClient:
    def __init__(self, header, records):
        self.header, self.records, self.page = header, records, 0
        self.writes = []

    async def write_gatt_char(self, uuid, value, response):
        self.writes.append((uuid, value, response))
        if value[0] == 3:
            self.page = value[1]

    async def read_gatt_char(self, uuid):
        assert uuid == CONFIG_UUID
        return self.header if self.page == 0 else self.records[self.page - 1]


class LegacyClient:
    def __init__(self, packets):
        self.packets = list(packets)
        self.writes = []

    async def write_gatt_char(self, uuid, value, response):
        self.writes.append((uuid, value))

    async def read_gatt_char(self, uuid):
        if uuid == CONFIG_UUID:
            raise OSError("characteristic missing")
        assert uuid == DATA_UUID
        return self.packets.pop(0)


class ConfigProtocolTest(unittest.TestCase):
    def test_complete_snapshot_is_validated(self):
        header, records = snapshot()
        decoded = decode_config_snapshot(header, records)
        self.assertEqual(decoded["active_count"], 2)
        self.assertEqual(decoded["habits"][4]["name"], "MEDITATION")
        self.assertFalse(decoded["habits"][1]["active"])

    def test_truncation_hash_enum_ids_and_text_are_rejected(self):
        header, records = snapshot()
        cases = []
        cases.append((header, records[:-1]))
        damaged = list(records); damaged[0] = damaged[0][:-1]; cases.append((header, damaged))
        damaged = list(records); value = bytearray(damaged[0]); value[4] = 9; damaged[0] = bytes(value); cases.append((header, damaged))
        damaged = list(records); value = bytearray(damaged[0]); value[2] = 1; damaged[0] = bytes(value); cases.append((header, damaged))
        damaged = list(records); value = bytearray(damaged[0]); value[10] = ord("!"); damaged[0] = bytes(value); cases.append((header, damaged))
        for broken_header, broken_records in cases:
            with self.subTest(index=len(cases)):
                with self.assertRaises(ValueError):
                    decode_config_snapshot(broken_header, broken_records)

    def test_read_uses_bounded_index_pages(self):
        header, records = snapshot()
        client = FakeClient(header, records)
        decoded = asyncio.run(read_config(client))
        self.assertEqual(decoded["record_count"], 10)
        self.assertEqual([write[1] for write in client.writes], [bytes((3, index)) for index in range(11)])
        self.assertTrue(all(write[0] == CONTROL_UUID for write in client.writes))

    def test_legacy_config_failure_does_not_block_log_sync(self):
        log = bytearray(34); log[:4] = bytes((1, 1, 0, 0)); struct.pack_into("<QqqIH", log, 4, 42, 100, 100, 0, 1)
        empty = bytes((1,)) + bytes(33)
        client = LegacyClient((bytes(log), empty))
        saved = []
        def persist(path, event, database, snapshot_id=None):
            saved.append((event, snapshot_id))
        synced = asyncio.run(sync_client(client, Path("unused"), synced_at=2000000000, persist=persist))
        self.assertEqual(synced, 1)
        self.assertEqual((saved[0][0]["id"], saved[0][1]), (42, None))
        self.assertEqual([value[0] for _, value in client.writes], [1, 3, 2])

    def test_persistence_failure_never_acknowledges_event(self):
        log = bytearray(34); log[:4] = bytes((1, 1, 0, 0)); struct.pack_into("<QqqIH", log, 4, 43, 100, 100, 0, 1)
        client = LegacyClient((bytes(log),))
        def fail(*args, **kwargs):
            raise OSError("disk full")
        with self.assertRaises(OSError):
            asyncio.run(sync_client(client, Path("unused"), synced_at=2000000000, persist=fail))
        self.assertNotIn(2, [value[0] for _, value in client.writes])


if __name__ == "__main__":
    unittest.main()
