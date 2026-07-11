#include "sync_policy.h"
#include <assert.h>
#include <stdio.h>

int main(void)
{
    sync_policy_t policy;
    sync_policy_init(&policy);
    assert(sync_policy_due(&policy, 0));
    sync_policy_failed(&policy, 100);
    assert(!sync_policy_due(&policy, 5099));
    assert(sync_policy_due(&policy, 5100));
    assert(policy.backoff_ms == 10000);
    for (int i = 0; i < 20; ++i) sync_policy_failed(&policy, policy.next_attempt_ms);
    assert(policy.backoff_ms == 15u * 60u * 1000u);
    sync_policy_succeeded(&policy, 1000, true);
    assert(policy.backoff_ms == 5000);
    assert(policy.next_attempt_ms == 1250);
    sync_policy_succeeded(&policy, 2000, false);
    assert(policy.next_attempt_ms == 32000);
    sync_policy_request_now(&policy, 2100); assert(sync_policy_due(&policy, 2100));
    puts("sync_policy_test: OK");
    return 0;
}
