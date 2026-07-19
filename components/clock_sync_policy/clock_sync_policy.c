#include "clock_sync_policy.h"

void clock_sync_policy_init(clock_sync_policy_t *policy, int64_t now_ms)
{
    if (!policy) return;
    policy->next_request_ms = now_ms;
    policy->synchronized = false;
}

bool clock_sync_policy_take_request(clock_sync_policy_t *policy, int64_t now_ms)
{
    if (!policy || now_ms < policy->next_request_ms) return false;
    policy->next_request_ms = now_ms + CLOCK_SYNC_RETRY_MS;
    return true;
}

void clock_sync_policy_synchronized(clock_sync_policy_t *policy, int64_t now_ms)
{
    if (!policy) return;
    policy->next_request_ms = now_ms + CLOCK_SYNC_PERIOD_MS;
    policy->synchronized = true;
}

bool clock_sync_policy_is_synchronized(const clock_sync_policy_t *policy)
{
    return policy && policy->synchronized;
}
