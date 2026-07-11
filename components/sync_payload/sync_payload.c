#include "sync_payload.h"
#include <stdio.h>

bool sync_payload_build(const habit_log_t *log, char *json, size_t json_size, char *key, size_t key_size)
{
    if (!log || !log->id || !json || !json_size || !key || !key_size) return false;
    int key_len = snprintf(key, key_size, "%llu%s", (unsigned long long)log->id,
                           log->deleted ? ":deleted" : "");
    int json_len = snprintf(json, json_size,
        "{\"id\":%llu,\"habit_id\":%u,\"type\":%d,\"started_at\":%lld,\"ended_at\":%lld,\"duration_seconds\":%u,\"count\":%u,\"deleted\":%s}",
        (unsigned long long)log->id, log->habit_id, (int)log->type,
        (long long)log->timestamp_start, (long long)log->timestamp_end,
        (unsigned)log->duration_seconds, (unsigned)log->count_value, log->deleted ? "true" : "false");
    return key_len > 0 && (size_t)key_len < key_size && json_len > 0 && (size_t)json_len < json_size;
}
