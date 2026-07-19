#pragma once

#include <stdbool.h>
#include <stdint.h>

#define CLOCK_SYNC_RETRY_MS  (60LL * 60LL * 1000LL)
#define CLOCK_SYNC_PERIOD_MS (60LL * 60LL * 1000LL)

typedef struct {
    int64_t next_request_ms;
} clock_sync_policy_t;

void clock_sync_policy_init(clock_sync_policy_t *policy, int64_t now_ms);
bool clock_sync_policy_take_request(clock_sync_policy_t *policy, int64_t now_ms);
void clock_sync_policy_synchronized(clock_sync_policy_t *policy, int64_t now_ms);
