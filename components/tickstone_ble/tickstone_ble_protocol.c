#include "tickstone_ble_protocol.h"

#include <string.h>

static void put_u16(uint8_t *out, uint16_t value)
{
    out[0] = (uint8_t)value; out[1] = (uint8_t)(value >> 8);
}

static void put_u32(uint8_t *out, uint32_t value)
{
    for (unsigned i = 0; i < 4; ++i) out[i] = (uint8_t)(value >> (i * 8));
}

static void put_u64(uint8_t *out, uint64_t value)
{
    for (unsigned i = 0; i < 8; ++i) out[i] = (uint8_t)(value >> (i * 8));
}

bool tickstone_ble_encode_log(const habit_log_t *log,
                              uint8_t out[TICKSTONE_BLE_PACKET_SIZE])
{
    if (!out) return false;
    memset(out, 0, TICKSTONE_BLE_PACKET_SIZE);
    out[0] = TICKSTONE_BLE_PACKET_VERSION;
    if (!log) return true;
    if (!log->id) return false;
    out[1] = 1u | (log->deleted ? 2u : 0u);
    out[2] = (uint8_t)log->type;
    out[3] = log->habit_id;
    put_u64(&out[4], log->id);
    put_u64(&out[12], (uint64_t)log->timestamp_start);
    put_u64(&out[20], (uint64_t)log->timestamp_end);
    put_u32(&out[28], log->duration_seconds);
    put_u16(&out[32], log->count_value);
    return true;
}
