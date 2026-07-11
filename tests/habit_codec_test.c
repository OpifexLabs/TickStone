#include "habit_codec.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static uint32_t test_crc32(const uint8_t *data, size_t size)
{
    uint32_t crc = 0xffffffffu;
    for (size_t i = 0; i < size; ++i) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8; ++bit) {
            crc = (crc >> 1) ^ (0xedb88320u & (uint32_t)-(int32_t)(crc & 1u));
        }
    }
    return ~crc;
}

static void test_v3_habit_migration(void)
{
    uint8_t encoded[22] = {
        0x54, 0x48, 0x42, 0x33, // THB3
        1, 0, 0, 0,
        2, 'S', 'T', 'R', 0,
        HABIT_TYPE_COUNT, HABIT_TIME_STOPWATCH, 1, 0, 0,
    };
    const uint32_t crc = test_crc32(encoded, sizeof(encoded) - 4);
    encoded[18] = (uint8_t)crc;
    encoded[19] = (uint8_t)(crc >> 8);
    encoded[20] = (uint8_t)(crc >> 16);
    encoded[21] = (uint8_t)(crc >> 24);

    habit_config_t output = {0};
    size_t count = 0;
    assert(habit_codec_decode_habits(encoded, sizeof(encoded), &output, 1, &count));
    assert(count == 1 && !strcmp(output.label, "STR") && !strcmp(output.name, "STRACKA"));
}

static void test_habits_roundtrip_and_corruption(void)
{
    const habit_config_t input[] = {
        {.id = 1, .label = "MED", .name = "MEDITATION", .type = HABIT_TYPE_TIME, .time_mode = HABIT_TIME_TIMER, .default_minutes = 12},
        {.id = 2, .label = "STR", .name = "STRACKA", .type = HABIT_TYPE_COUNT, .time_mode = HABIT_TIME_STOPWATCH, .default_minutes = 1},
    };
    uint8_t encoded[HABIT_CODEC_HABITS_MAX_SIZE] = {0};
    size_t written = 0;
    assert(habit_codec_encode_habits(input, 2, encoded, sizeof(encoded), &written));

    habit_config_t output[HABIT_APP_MAX_HABITS] = {0};
    size_t count = 0;
    assert(habit_codec_decode_habits(encoded, written, output, HABIT_APP_MAX_HABITS, &count));
    assert(count == 2);
    assert(memcmp(input, output, sizeof(input)) == 0);

    encoded[9] ^= 0x40;
    assert(!habit_codec_decode_habits(encoded, written, output, HABIT_APP_MAX_HABITS, &count));
}

static void test_log_roundtrip_and_corruption(void)
{
    const habit_log_t input = {
        .id = 0x1122334455667788ULL,
        .habit_id = 4,
        .type = HABIT_TYPE_TIME,
        .timestamp_start = 1700000000,
        .timestamp_end = 1700000061,
        .duration_seconds = 60,
        .synced = false,
    };
    uint8_t encoded[HABIT_CODEC_LOG_SIZE] = {0};
    assert(habit_codec_encode_log(&input, encoded, sizeof(encoded)));
    habit_log_t output = {0};
    assert(habit_codec_decode_log(encoded, sizeof(encoded), &output));
    assert(memcmp(&input, &output, sizeof(input)) == 0);
    encoded[20] ^= 1;
    assert(!habit_codec_decode_log(encoded, sizeof(encoded), &output));
}

static void test_session_roundtrip(void)
{
    const habit_session_snapshot_t input = {
        .session_active = true,
        .session_paused = true,
        .selected_habit_id = 3,
        .time_mode = HABIT_TIME_STOPWATCH,
        .session_start = 100,
        .session_paused_at = 130,
        .session_paused_total = 4,
        .timer_seconds = 0,
        .setup_minutes = 1,
        .session_start_utc = 1700000000,
        .session_start_utc_valid = true,
    };
    uint8_t encoded[HABIT_CODEC_SESSION_SIZE] = {0};
    assert(habit_codec_encode_session(&input, encoded, sizeof(encoded)));
    habit_session_snapshot_t output = {0};
    assert(habit_codec_decode_session(encoded, sizeof(encoded), &output));
    assert(memcmp(&input, &output, sizeof(input)) == 0);
}

static void test_daily_roundtrip_and_corruption(void)
{
    habit_daily_summary_t input = {.day_id=20000, .week_id=2857, .month_id=24291,
        .habit_id=7, .type=HABIT_TYPE_TIME, .value=3600, .through_log_id=998};
    uint8_t encoded[HABIT_CODEC_DAILY_SIZE]; habit_daily_summary_t output;
    assert(habit_codec_encode_daily(&input, encoded, sizeof(encoded)));
    assert(habit_codec_decode_daily(encoded, sizeof(encoded), &output));
    assert(memcmp(&input, &output, sizeof(input)) == 0);
    encoded[8] ^= 1; assert(!habit_codec_decode_daily(encoded, sizeof(encoded), &output));
}

int main(void)
{
    test_v3_habit_migration();
    test_habits_roundtrip_and_corruption();
    test_log_roundtrip_and_corruption();
    test_session_roundtrip();
    test_daily_roundtrip_and_corruption();
    puts("habit_codec_test: OK");
    return 0;
}
