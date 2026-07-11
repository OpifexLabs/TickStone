#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "habit_app.h"

#ifdef __cplusplus
extern "C" {
#endif

#define HABIT_CODEC_HABITS_MAX_SIZE 112
#define HABIT_CODEC_LOG_SIZE 42
#define HABIT_CODEC_SESSION_SIZE 48
#define HABIT_CODEC_DAILY_SIZE 36

bool habit_codec_encode_habits(const habit_config_t *habits,
                               size_t count,
                               uint8_t *out,
                               size_t out_size,
                               size_t *written);
bool habit_codec_decode_habits(const uint8_t *data,
                               size_t data_size,
                               habit_config_t *habits,
                               size_t max_count,
                               size_t *count);
bool habit_codec_encode_log(const habit_log_t *log, uint8_t *out, size_t out_size);
bool habit_codec_decode_log(const uint8_t *data, size_t data_size, habit_log_t *log);
bool habit_codec_encode_session(const habit_session_snapshot_t *session,
                                uint8_t *out,
                                size_t out_size);
bool habit_codec_decode_session(const uint8_t *data,
                                size_t data_size,
                                habit_session_snapshot_t *session);
bool habit_codec_encode_daily(const habit_daily_summary_t *summary, uint8_t *out, size_t out_size);
bool habit_codec_decode_daily(const uint8_t *data, size_t data_size, habit_daily_summary_t *summary);

#ifdef __cplusplus
}
#endif
