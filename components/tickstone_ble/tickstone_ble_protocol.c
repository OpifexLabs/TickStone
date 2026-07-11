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

static size_t bounded_length(const char *text, size_t maximum)
{
    size_t length = 0;
    while (length <= maximum && text[length]) ++length;
    return length;
}

static bool valid_config(const habit_config_t *habits, size_t count)
{
    if ((!habits && count) || count > HABIT_APP_MAX_HABITS) return false;
    uint16_t used = 0;
    for (size_t i = 0; i < count; ++i) {
        const habit_config_t *habit = &habits[i];
        if (habit->id >= HABIT_APP_MAX_HABITS || (used & (1u << habit->id)) ||
            (habit->type != HABIT_TYPE_COUNT && habit->type != HABIT_TYPE_TIME) ||
            bounded_length(habit->label, HABIT_APP_LABEL_LEN) > HABIT_APP_LABEL_LEN ||
            bounded_length(habit->name, HABIT_APP_NAME_LEN) > HABIT_APP_NAME_LEN ||
            !habit->label[0] || !habit->name[0] || habit->default_minutes < 1 ||
            habit->default_minutes > 99) return false;
        used |= (uint16_t)(1u << habit->id);
    }
    return true;
}

static const habit_config_t *config_for_slot(const habit_config_t *habits,
                                             size_t count,
                                             uint8_t slot)
{
    for (size_t i = 0; i < count; ++i) if (habits[i].id == slot) return &habits[i];
    return NULL;
}

static void encode_record(const habit_config_t *habits,
                          size_t count,
                          uint8_t slot,
                          uint8_t out[TICKSTONE_BLE_CONFIG_PACKET_SIZE])
{
    memset(out, 0, TICKSTONE_BLE_CONFIG_PACKET_SIZE);
    out[0] = TICKSTONE_BLE_CONFIG_VERSION;
    out[1] = 1;
    out[2] = slot;
    const habit_config_t *habit = config_for_slot(habits, count, slot);
    if (!habit) {
        put_u16(&out[8], 1);
        return;
    }
    const size_t code_length = bounded_length(habit->label, HABIT_APP_LABEL_LEN);
    const size_t name_length = bounded_length(habit->name, HABIT_APP_NAME_LEN);
    out[3] = 1;
    out[4] = (uint8_t)habit->type;
    out[5] = (uint8_t)code_length;
    out[6] = (uint8_t)name_length;
    put_u16(&out[8], habit->default_minutes);
    memcpy(&out[10], habit->label, code_length);
    memcpy(&out[13], habit->name, name_length);
}

static uint32_t crc32_update(uint32_t crc, const uint8_t *data, size_t size)
{
    for (size_t i = 0; i < size; ++i) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8; ++bit) {
            crc = (crc >> 1) ^ (0xEDB88320u & (uint32_t)-(int32_t)(crc & 1u));
        }
    }
    return crc;
}

uint32_t tickstone_ble_config_hash(const habit_config_t *habits, size_t count)
{
    if (!valid_config(habits, count)) return 0;
    uint32_t crc = 0xFFFFFFFFu;
    uint8_t record[TICKSTONE_BLE_CONFIG_PACKET_SIZE];
    for (uint8_t slot = 0; slot < HABIT_APP_MAX_HABITS; ++slot) {
        encode_record(habits, count, slot, record);
        crc = crc32_update(crc, &record[2], TICKSTONE_BLE_CONFIG_PACKET_SIZE - 2);
    }
    return ~crc;
}

bool tickstone_ble_encode_config_page(const habit_config_t *habits,
                                      size_t count,
                                      uint8_t page,
                                      uint8_t out[TICKSTONE_BLE_CONFIG_PACKET_SIZE])
{
    if (!out || page >= TICKSTONE_BLE_CONFIG_PAGE_COUNT || !valid_config(habits, count)) return false;
    if (page > 0) {
        encode_record(habits, count, (uint8_t)(page - 1), out);
        return true;
    }
    memset(out, 0, TICKSTONE_BLE_CONFIG_PACKET_SIZE);
    out[0] = TICKSTONE_BLE_CONFIG_VERSION;
    out[1] = 0;
    out[2] = HABIT_APP_MAX_HABITS;
    out[3] = (uint8_t)count;
    put_u32(&out[4], tickstone_ble_config_hash(habits, count));
    return true;
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
