#pragma once
#include <stdbool.h>
#include <stdint.h>

typedef struct {
    int64_t next_attempt_ms;
    uint32_t backoff_ms;
} sync_policy_t;

void sync_policy_init(sync_policy_t *policy);
bool sync_policy_due(const sync_policy_t *policy, int64_t now_ms);
void sync_policy_request_now(sync_policy_t *policy, int64_t now_ms);
void sync_policy_succeeded(sync_policy_t *policy, int64_t now_ms, bool more_pending);
void sync_policy_failed(sync_policy_t *policy, int64_t now_ms);
