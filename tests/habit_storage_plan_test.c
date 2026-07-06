#include "habit_storage_plan.h"

#include <assert.h>
#include <stdio.h>

static void test_append_one_new_log(void)
{
    habit_storage_log_plan_t plan = habit_storage_plan_logs(2, 3, 128, 2);
    assert(plan.mode == HABIT_STORAGE_LOG_WRITE_APPEND);
    assert(plan.append_index == 2);
    assert(!plan.rewrite_latest);
    assert(plan.write_meta);
}

static void test_undo_rewrites_latest_without_full_rewrite(void)
{
    habit_storage_log_plan_t plan = habit_storage_plan_logs(3, 3, 128, 2);
    assert(plan.mode == HABIT_STORAGE_LOG_WRITE_NONE);
    assert(plan.rewrite_latest);
    assert(plan.latest_index == 2);
    assert(plan.write_meta);
}

static void test_log_rollover_or_migration_uses_full_rewrite(void)
{
    habit_storage_log_plan_t plan = habit_storage_plan_logs(128, 128, 128, 127);
    assert(plan.mode == HABIT_STORAGE_LOG_WRITE_FULL);
    assert(plan.full_count == 128);
    assert(!plan.rewrite_latest);
    assert(plan.write_meta);

    plan = habit_storage_plan_logs(128, 127, 128, 126);
    assert(plan.mode == HABIT_STORAGE_LOG_WRITE_FULL);
    assert(plan.full_count == 127);
    assert(!plan.rewrite_latest);
    assert(plan.write_meta);
}

static void test_no_write_when_clean_and_no_latest_change(void)
{
    habit_storage_log_plan_t plan = habit_storage_plan_logs(3, 3, 128, -1);
    assert(plan.mode == HABIT_STORAGE_LOG_WRITE_NONE);
    assert(!plan.rewrite_latest);
    assert(!plan.write_meta);
}

int main(void)
{
    test_append_one_new_log();
    test_undo_rewrites_latest_without_full_rewrite();
    test_log_rollover_or_migration_uses_full_rewrite();
    test_no_write_when_clean_and_no_latest_change();
    puts("habit_storage_plan_test: OK");
    return 0;
}
