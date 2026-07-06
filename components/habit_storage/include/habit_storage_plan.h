#pragma once

#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    HABIT_STORAGE_LOG_WRITE_NONE = 0,
    HABIT_STORAGE_LOG_WRITE_APPEND,
    HABIT_STORAGE_LOG_WRITE_FULL,
} habit_storage_log_write_mode_t;

typedef struct {
    habit_storage_log_write_mode_t mode;
    size_t append_index;
    size_t full_count;
    bool rewrite_latest;
    size_t latest_index;
    bool write_meta;
} habit_storage_log_plan_t;

habit_storage_log_plan_t habit_storage_plan_logs(size_t saved_log_count,
                                                 size_t current_log_count,
                                                 size_t max_log_count,
                                                 int latest_log_index);

#ifdef __cplusplus
}
#endif
