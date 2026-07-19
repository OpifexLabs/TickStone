#include "clock_sync_policy.h"

#include <assert.h>
#include <stdio.h>

static void test_boot_requests_time_immediately_and_retries_hourly(void)
{
    clock_sync_policy_t policy;
    clock_sync_policy_init(&policy, 1000);

    assert(clock_sync_policy_take_request(&policy, 1000));
    assert(!clock_sync_policy_take_request(&policy, 1001));
    assert(!clock_sync_policy_take_request(&policy, 1000 + CLOCK_SYNC_RETRY_MS - 1));
    assert(clock_sync_policy_take_request(&policy, 1000 + CLOCK_SYNC_RETRY_MS));
}

static void test_success_schedules_hourly_drift_correction(void)
{
    assert(CLOCK_SYNC_PERIOD_MS == 60LL * 60LL * 1000LL);
    clock_sync_policy_t policy;
    clock_sync_policy_init(&policy, 0);
    assert(clock_sync_policy_take_request(&policy, 0));

    clock_sync_policy_synchronized(&policy, 5000);
    assert(!clock_sync_policy_take_request(&policy, 5000 + CLOCK_SYNC_PERIOD_MS - 1));
    assert(clock_sync_policy_take_request(&policy, 5000 + CLOCK_SYNC_PERIOD_MS));
    assert(!clock_sync_policy_take_request(&policy, 5000 + CLOCK_SYNC_PERIOD_MS + 1));
}

static void test_late_host_time_replaces_retry_deadline(void)
{
    clock_sync_policy_t policy;
    clock_sync_policy_init(&policy, 0);
    assert(clock_sync_policy_take_request(&policy, 0));

    const int64_t late_sync = CLOCK_SYNC_RETRY_MS - 1000;
    clock_sync_policy_synchronized(&policy, late_sync);
    assert(!clock_sync_policy_take_request(&policy, CLOCK_SYNC_RETRY_MS));
    assert(clock_sync_policy_take_request(&policy, late_sync + CLOCK_SYNC_PERIOD_MS));
}

int main(void)
{
    test_boot_requests_time_immediately_and_retries_hourly();
    test_success_schedules_hourly_drift_correction();
    test_late_host_time_replaces_retry_deadline();
    puts("clock_sync_policy_test: OK");
    return 0;
}
