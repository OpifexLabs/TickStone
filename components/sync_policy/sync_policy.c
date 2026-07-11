#include "sync_policy.h"

#define INITIAL_BACKOFF_MS 5000u
#define MAX_BACKOFF_MS (15u * 60u * 1000u)
#define NEXT_ITEM_MS 250
#define EMPTY_SCAN_MS 30000

void sync_policy_init(sync_policy_t *policy)
{
    if (!policy) return;
    policy->next_attempt_ms = 0;
    policy->backoff_ms = INITIAL_BACKOFF_MS;
}

bool sync_policy_due(const sync_policy_t *policy, int64_t now_ms)
{
    return policy && now_ms >= policy->next_attempt_ms;
}

void sync_policy_request_now(sync_policy_t *policy, int64_t now_ms)
{
    if (policy && policy->next_attempt_ms > now_ms) policy->next_attempt_ms = now_ms;
}

void sync_policy_succeeded(sync_policy_t *policy, int64_t now_ms, bool more_pending)
{
    if (!policy) return;
    policy->backoff_ms = INITIAL_BACKOFF_MS;
    policy->next_attempt_ms = now_ms + (more_pending ? NEXT_ITEM_MS : EMPTY_SCAN_MS);
}

void sync_policy_failed(sync_policy_t *policy, int64_t now_ms)
{
    if (!policy) return;
    policy->next_attempt_ms = now_ms + policy->backoff_ms;
    if (policy->backoff_ms < MAX_BACKOFF_MS) {
        uint32_t doubled = policy->backoff_ms * 2u;
        policy->backoff_ms = doubled > MAX_BACKOFF_MS ? MAX_BACKOFF_MS : doubled;
    }
}
