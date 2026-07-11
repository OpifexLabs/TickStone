# BLE configuration sync and historical dashboard

Status: implementation complete; deployment verification in progress

## Invariants

- Existing BLE service, log data packet, time command and ACK command remain byte-compatible.
- WiFi remains disabled and BLE remains event-driven.
- `logs.jsonl` is append-only and is never rebuilt or truncated.
- SQLite migrations are forward-only; unknown newer schemas are rejected.
- Dashboard requests use read-only SQLite connections and never infer metadata that is not known.

## Protocol

- Add read-only characteristic `7e570000-7a1b-4c2d-9e10-000000000004`.
- Control command `3,index` selects a fixed config page.
- Page 0 is a versioned header with record count, active count and deterministic CRC32.
- Pages 1-10 are fixed-size slot records with slot, active, type, minutes, code and name.
- Hash input is the ten canonical record payloads in slot order. No dynamic allocation.

## Storage

- Migrate schema v1 to v2 with protocol/hash metadata, active snapshot entries and validity intervals.
- Close the previous snapshot when a changed snapshot arrives.
- Resolve event metadata against the snapshot valid at `started_at`.
- Events before the first known snapshot use current metadata only as an explicitly uncertain fallback.

## Delivery slices

1. RED/GREEN: C config packet/hash/index protocol and unchanged legacy log packet.
2. RED/GREEN: Python config decoding, validation, legacy fallback and safe sync ordering.
3. RED/GREEN: schema migration, snapshots, slot reuse and historical lookup.
4. RED/GREEN: overview metadata and week/month/year habit details.
5. HTTP/security/accessibility/systemd verification.
6. ESP-IDF build, hardware flash, real config/log sync and browser QA.

## Verification record

- Host/C tests: protocol, legacy fallback, ACK ordering, schema migration and dashboard periods pass.
- ESP-IDF 5.5.3 build: pass for ESP32-C3.
- Hardware flash: pass on `/dev/cu.usbmodem21201`.
- Real BLE config read: protocol 1, hash `261ff10d`, 3 active and 7 inactive slots.
- Pi deployment, service hardening and browser QA: pending final branch deployment.
