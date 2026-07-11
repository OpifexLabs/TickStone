#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "habit_app.h"

typedef struct { uint32_t version; uint32_t count; } habit_legacy_meta_t;
typedef struct {
    uint8_t id; char label[4]; uint8_t pad[3]; int32_t type; int32_t time_mode;
    uint16_t default_minutes; uint8_t tail_pad[2];
} habit_legacy_config_item_t;
typedef struct {
    uint8_t habit_id; uint8_t pad[3]; int32_t type; int64_t start; int64_t end;
    uint32_t duration; uint16_t count; uint8_t synced; uint8_t deleted;
} habit_legacy_log_t;
typedef struct {
    uint32_t version; uint32_t count; habit_legacy_config_item_t habits[HABIT_APP_MAX_HABITS];
} habit_legacy_config_t;
typedef struct {
    uint8_t active, paused, habit_id, pad; int32_t mode; int64_t start, paused_at;
    uint32_t paused_total, timer_seconds, setup_minutes, tail_pad;
} habit_legacy_session_t;
typedef struct { uint32_t version, pad; habit_legacy_session_t session; } habit_legacy_session_blob_t;

bool habit_legacy_convert_log(const habit_legacy_log_t *old, uint64_t id, habit_log_t *out);
bool habit_legacy_convert_config(const habit_legacy_config_t *old,
                                 habit_config_t *out,
                                 size_t max_count,
                                 size_t *count);
bool habit_legacy_convert_session(const habit_legacy_session_blob_t *old, habit_session_snapshot_t *out);
