#include "sync_payload.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
    habit_log_t log = {.id=42, .habit_id=3, .type=HABIT_TYPE_TIME, .timestamp_start=100,
        .timestamp_end=160, .duration_seconds=60, .deleted=true};
    char json[320], key[24]; assert(sync_payload_build(&log, json, sizeof(json), key, sizeof(key)));
    assert(!strcmp(key, "42:deleted"));
    assert(strstr(json, "\"id\":42") && strstr(json, "\"habit_id\":3") &&
           strstr(json, "\"duration_seconds\":60") && strstr(json, "\"deleted\":true"));
    assert(!sync_payload_build(&log, json, 8, key, sizeof(key)));
    log.deleted = false; assert(sync_payload_build(&log, json, sizeof(json), key, sizeof(key)) && !strcmp(key, "42"));
    log.id = 0; assert(!sync_payload_build(&log, json, sizeof(json), key, sizeof(key)));
    puts("sync_payload_test: OK");
    return 0;
}
