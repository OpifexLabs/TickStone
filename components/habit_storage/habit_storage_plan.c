#include "habit_storage_plan.h"

habit_storage_log_plan_t habit_storage_plan_logs(size_t saved_log_count,
                                                 size_t current_log_count,
                                                 size_t max_log_count,
                                                 int latest_log_index)
{
    habit_storage_log_plan_t plan = {
        .mode = HABIT_STORAGE_LOG_WRITE_NONE,
        .append_index = 0,
        .full_count = 0,
        .rewrite_latest = false,
        .latest_index = 0,
        .write_meta = false,
    };

    if (current_log_count == saved_log_count &&
        current_log_count == max_log_count &&
        latest_log_index >= 0 &&
        (size_t)latest_log_index == current_log_count - 1) {
        plan.mode = HABIT_STORAGE_LOG_WRITE_FULL;
        plan.full_count = current_log_count;
        plan.write_meta = true;
    } else if (current_log_count == saved_log_count + 1) {
        plan.mode = HABIT_STORAGE_LOG_WRITE_APPEND;
        plan.append_index = current_log_count - 1;
        plan.write_meta = true;
    } else if (current_log_count != saved_log_count) {
        plan.mode = HABIT_STORAGE_LOG_WRITE_FULL;
        plan.full_count = current_log_count;
        plan.write_meta = true;
    }

    if (latest_log_index >= 0 && (size_t)latest_log_index < current_log_count) {
        size_t latest = (size_t)latest_log_index;
        bool already_appended = plan.mode == HABIT_STORAGE_LOG_WRITE_APPEND &&
                                plan.append_index == latest;
        bool already_rewritten = plan.mode == HABIT_STORAGE_LOG_WRITE_FULL;
        if (!already_appended && !already_rewritten) {
            plan.rewrite_latest = true;
            plan.latest_index = latest;
            plan.write_meta = true;
        }
    }

    return plan;
}
