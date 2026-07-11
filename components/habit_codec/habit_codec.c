#include "habit_codec.h"

#include <string.h>

#define HABITS_MAGIC 0x33424854U
#define LOG_MAGIC 0x334C4854U
#define SESSION_MAGIC 0x33534854U
#define DAILY_MAGIC 0x33444854U
#define HABITS_HEADER_SIZE 8
#define HABIT_RECORD_SIZE 10

static void put_u16(uint8_t *out, uint16_t value)
{
    out[0] = (uint8_t)value;
    out[1] = (uint8_t)(value >> 8);
}

static void put_u32(uint8_t *out, uint32_t value)
{
    for (unsigned i = 0; i < 4; ++i) {
        out[i] = (uint8_t)(value >> (i * 8));
    }
}

static void put_u64(uint8_t *out, uint64_t value)
{
    for (unsigned i = 0; i < 8; ++i) {
        out[i] = (uint8_t)(value >> (i * 8));
    }
}

static uint16_t get_u16(const uint8_t *data)
{
    return (uint16_t)data[0] | ((uint16_t)data[1] << 8);
}

static uint32_t get_u32(const uint8_t *data)
{
    uint32_t value = 0;
    for (unsigned i = 0; i < 4; ++i) {
        value |= (uint32_t)data[i] << (i * 8);
    }
    return value;
}

static uint64_t get_u64(const uint8_t *data)
{
    uint64_t value = 0;
    for (unsigned i = 0; i < 8; ++i) {
        value |= (uint64_t)data[i] << (i * 8);
    }
    return value;
}

static uint32_t crc32(const uint8_t *data, size_t size)
{
    uint32_t crc = 0xFFFFFFFFU;
    for (size_t i = 0; i < size; ++i) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8; ++bit) {
            crc = (crc >> 1) ^ (0xEDB88320U & (uint32_t)-(int32_t)(crc & 1U));
        }
    }
    return ~crc;
}

static bool valid_crc(const uint8_t *data, size_t size)
{
    return size >= 4 && get_u32(&data[size - 4]) == crc32(data, size - 4);
}

bool habit_codec_encode_habits(const habit_config_t *habits,
                               size_t count,
                               uint8_t *out,
                               size_t out_size,
                               size_t *written)
{
    const size_t size = HABITS_HEADER_SIZE + count * HABIT_RECORD_SIZE + 4;
    if (habits == NULL || out == NULL || written == NULL || count == 0 ||
        count > HABIT_APP_MAX_HABITS || out_size < size) {
        return false;
    }

    memset(out, 0, size);
    put_u32(out, HABITS_MAGIC);
    out[4] = (uint8_t)count;
    for (size_t i = 0; i < count; ++i) {
        uint8_t *record = &out[HABITS_HEADER_SIZE + i * HABIT_RECORD_SIZE];
        record[0] = habits[i].id;
        memcpy(&record[1], habits[i].label, HABIT_APP_LABEL_LEN + 1);
        record[5] = (uint8_t)habits[i].type;
        record[6] = (uint8_t)habits[i].time_mode;
        put_u16(&record[7], habits[i].default_minutes);
    }
    put_u32(&out[size - 4], crc32(out, size - 4));
    *written = size;
    return true;
}

bool habit_codec_decode_habits(const uint8_t *data,
                               size_t data_size,
                               habit_config_t *habits,
                               size_t max_count,
                               size_t *count)
{
    if (data == NULL || habits == NULL || count == NULL || data_size < HABITS_HEADER_SIZE + 4 ||
        get_u32(data) != HABITS_MAGIC || !valid_crc(data, data_size)) {
        return false;
    }
    const size_t decoded_count = data[4];
    const size_t expected = HABITS_HEADER_SIZE + decoded_count * HABIT_RECORD_SIZE + 4;
    if (decoded_count == 0 || decoded_count > max_count || data_size != expected) {
        return false;
    }

    memset(habits, 0, sizeof(*habits) * decoded_count);
    for (size_t i = 0; i < decoded_count; ++i) {
        const uint8_t *record = &data[HABITS_HEADER_SIZE + i * HABIT_RECORD_SIZE];
        habits[i].id = record[0];
        memcpy(habits[i].label, &record[1], HABIT_APP_LABEL_LEN + 1);
        habits[i].type = (habit_type_t)record[5];
        habits[i].time_mode = (habit_time_mode_t)record[6];
        habits[i].default_minutes = get_u16(&record[7]);
    }
    *count = decoded_count;
    return true;
}

bool habit_codec_encode_log(const habit_log_t *log, uint8_t *out, size_t out_size)
{
    if (log == NULL || out == NULL || out_size < HABIT_CODEC_LOG_SIZE || log->id == 0) {
        return false;
    }
    memset(out, 0, HABIT_CODEC_LOG_SIZE);
    put_u32(out, LOG_MAGIC);
    put_u64(&out[4], log->id);
    out[12] = log->habit_id;
    out[13] = (uint8_t)log->type;
    out[14] = (log->synced ? 1U : 0U) | (log->deleted ? 2U : 0U);
    put_u64(&out[16], (uint64_t)log->timestamp_start);
    put_u64(&out[24], (uint64_t)log->timestamp_end);
    put_u32(&out[32], log->duration_seconds);
    put_u16(&out[36], log->count_value);
    put_u32(&out[38], crc32(out, 38));
    return true;
}

bool habit_codec_decode_log(const uint8_t *data, size_t data_size, habit_log_t *log)
{
    if (data == NULL || log == NULL || data_size != HABIT_CODEC_LOG_SIZE ||
        get_u32(data) != LOG_MAGIC || !valid_crc(data, data_size)) {
        return false;
    }
    memset(log, 0, sizeof(*log));
    log->id = get_u64(&data[4]);
    log->habit_id = data[12];
    log->type = (habit_type_t)data[13];
    log->synced = (data[14] & 1U) != 0;
    log->deleted = (data[14] & 2U) != 0;
    log->timestamp_start = (int64_t)get_u64(&data[16]);
    log->timestamp_end = (int64_t)get_u64(&data[24]);
    log->duration_seconds = get_u32(&data[32]);
    log->count_value = get_u16(&data[36]);
    return log->id != 0 &&
           (log->type == HABIT_TYPE_COUNT || log->type == HABIT_TYPE_TIME);
}

bool habit_codec_encode_session(const habit_session_snapshot_t *session,
                                uint8_t *out,
                                size_t out_size)
{
    if (session == NULL || out == NULL || out_size < HABIT_CODEC_SESSION_SIZE ||
        !session->session_active) {
        return false;
    }
    memset(out, 0, HABIT_CODEC_SESSION_SIZE);
    put_u32(out, SESSION_MAGIC);
    out[4] = 1U | (session->session_paused ? 2U : 0U) |
             (session->session_start_utc_valid ? 4U : 0U);
    out[5] = session->selected_habit_id;
    out[6] = (uint8_t)session->time_mode;
    put_u64(&out[8], (uint64_t)session->session_start);
    put_u64(&out[16], (uint64_t)session->session_paused_at);
    put_u32(&out[24], session->session_paused_total);
    put_u32(&out[28], session->timer_seconds);
    put_u32(&out[32], session->setup_minutes);
    put_u64(&out[36], (uint64_t)session->session_start_utc);
    put_u32(&out[44], crc32(out, 44));
    return true;
}

bool habit_codec_decode_session(const uint8_t *data,
                                size_t data_size,
                                habit_session_snapshot_t *session)
{
    if (data == NULL || session == NULL || data_size != HABIT_CODEC_SESSION_SIZE ||
        get_u32(data) != SESSION_MAGIC || !valid_crc(data, data_size)) {
        return false;
    }
    memset(session, 0, sizeof(*session));
    session->session_active = (data[4] & 1U) != 0;
    session->session_paused = (data[4] & 2U) != 0;
    session->session_start_utc_valid = (data[4] & 4U) != 0;
    session->selected_habit_id = data[5];
    session->time_mode = (habit_time_mode_t)data[6];
    session->session_start = (int64_t)get_u64(&data[8]);
    session->session_paused_at = (int64_t)get_u64(&data[16]);
    session->session_paused_total = get_u32(&data[24]);
    session->timer_seconds = get_u32(&data[28]);
    session->setup_minutes = get_u32(&data[32]);
    session->session_start_utc = (int64_t)get_u64(&data[36]);
    return session->session_active &&
           (session->time_mode == HABIT_TIME_TIMER || session->time_mode == HABIT_TIME_STOPWATCH);
}

bool habit_codec_encode_daily(const habit_daily_summary_t *summary, uint8_t *out, size_t out_size)
{
    if (!summary || !out || out_size < HABIT_CODEC_DAILY_SIZE || summary->habit_id >= HABIT_APP_MAX_HABITS ||
        (summary->type != HABIT_TYPE_COUNT && summary->type != HABIT_TYPE_TIME)) return false;
    memset(out, 0, HABIT_CODEC_DAILY_SIZE);
    put_u32(out, DAILY_MAGIC); put_u32(&out[4], (uint32_t)summary->day_id);
    put_u32(&out[8], (uint32_t)summary->week_id); put_u32(&out[12], (uint32_t)summary->month_id);
    out[16] = summary->habit_id; out[17] = (uint8_t)summary->type;
    put_u32(&out[20], summary->value); put_u64(&out[24], summary->through_log_id);
    put_u32(&out[32], crc32(out, 32)); return true;
}

bool habit_codec_decode_daily(const uint8_t *data, size_t data_size, habit_daily_summary_t *summary)
{
    if (!data || !summary || data_size != HABIT_CODEC_DAILY_SIZE || get_u32(data) != DAILY_MAGIC || !valid_crc(data, data_size)) return false;
    *summary = (habit_daily_summary_t){
        .day_id=(int32_t)get_u32(&data[4]), .week_id=(int32_t)get_u32(&data[8]),
        .month_id=(int32_t)get_u32(&data[12]), .habit_id=data[16],
        .type=(habit_type_t)data[17], .value=get_u32(&data[20]), .through_log_id=get_u64(&data[24]),
    };
    return summary->habit_id < HABIT_APP_MAX_HABITS &&
           (summary->type == HABIT_TYPE_COUNT || summary->type == HABIT_TYPE_TIME);
}
