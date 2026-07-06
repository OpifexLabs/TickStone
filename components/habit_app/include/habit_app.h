#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define HABIT_APP_MAX_HABITS 10
#define HABIT_APP_LABEL_LEN 3
#define HABIT_APP_MAX_LOGS 128
#define HABIT_APP_DAY_START_HOUR 5

typedef enum {
    HABIT_TYPE_COUNT = 0,
    HABIT_TYPE_TIME,
} habit_type_t;

typedef enum {
    HABIT_TIME_TIMER = 0,
    HABIT_TIME_STOPWATCH,
} habit_time_mode_t;

typedef enum {
    HABIT_BUTTON_LEFT = 0,
    HABIT_BUTTON_OK,
    HABIT_BUTTON_RIGHT,
} habit_button_t;

typedef enum {
    HABIT_PRESS_SHORT = 0,
    HABIT_PRESS_LONG,
} habit_press_t;

typedef enum {
    HABIT_SCREEN_SELECT = 0,
    HABIT_SCREEN_CONFIRM,
    HABIT_SCREEN_TIMER_SETUP,
    HABIT_SCREEN_SESSION,
    HABIT_SCREEN_STATS,
} habit_screen_id_t;

typedef enum {
    HABIT_STAT_WEEK_TOTAL = 0,
    HABIT_STAT_WEEK_DELTA,
    HABIT_STAT_MONTH_TOTAL,
    HABIT_STAT_WEEK_AVG,
    HABIT_STAT_COUNT,
} habit_stat_view_t;

typedef enum {
    HABIT_HOME_ACTION = 0,
    HABIT_HOME_HABITS,
    HABIT_HOME_LOGS,
} habit_home_mode_t;

typedef struct {
    uint8_t id;
    char label[HABIT_APP_LABEL_LEN + 1];
    habit_type_t type;
    habit_time_mode_t time_mode;
    uint16_t default_minutes;
} habit_config_t;

typedef struct {
    uint8_t habit_id;
    habit_type_t type;
    int64_t timestamp_start;
    int64_t timestamp_end;
    uint32_t duration_seconds;
    uint16_t count_value;
    bool synced;
    bool deleted;
} habit_log_t;

typedef struct {
    habit_screen_id_t id;
    char primary[8];
    char secondary[8];
    char tertiary[8];
    bool dirty;
} habit_screen_t;

typedef struct {
    bool session_active;
    bool session_paused;
    uint8_t selected_habit_id;
    habit_time_mode_t time_mode;
    int64_t session_start;
    int64_t session_paused_at;
    uint32_t session_paused_total;
    uint32_t timer_seconds;
    uint32_t setup_minutes;
} habit_session_snapshot_t;

typedef struct {
    habit_config_t habits[HABIT_APP_MAX_HABITS];
    size_t habit_count;
    habit_log_t logs[HABIT_APP_MAX_LOGS];
    size_t log_count;
    int last_log_index;

    size_t selected;
    habit_home_mode_t home_mode;
    size_t log_view_index;
    habit_screen_id_t screen;
    habit_stat_view_t stat_view;
    int64_t confirm_until;

    bool session_active;
    bool session_paused;
    int64_t session_start;
    int64_t session_paused_at;
    uint32_t session_paused_total;
    uint32_t timer_seconds;
    uint32_t setup_minutes;

    bool logs_dirty;
    bool session_dirty;
    bool habits_dirty;
    int64_t last_session_tick_second;

    habit_screen_t cached_screen;
} habit_app_t;

void habit_app_init(habit_app_t *app);
bool habit_app_set_habits(habit_app_t *app, const habit_config_t *habits, size_t habit_count);
bool habit_app_load_habits(habit_app_t *app, const habit_config_t *habits, size_t habit_count);
void habit_app_tick(habit_app_t *app, int64_t now_seconds);
void habit_app_handle_button(habit_app_t *app,
                             habit_button_t button,
                             habit_press_t press,
                             int64_t now_seconds);
const habit_screen_t *habit_app_screen(habit_app_t *app, int64_t now_seconds);
bool habit_app_take_logs_dirty(habit_app_t *app);
bool habit_app_take_session_dirty(habit_app_t *app);
bool habit_app_take_habits_dirty(habit_app_t *app);
size_t habit_app_copy_habits(const habit_app_t *app, habit_config_t *out, size_t max_habits);
void habit_app_load_logs(habit_app_t *app, const habit_log_t *logs, size_t log_count);
size_t habit_app_copy_logs(const habit_app_t *app, habit_log_t *out, size_t max_logs);
bool habit_app_get_log(const habit_app_t *app, size_t index, habit_log_t *out);
int habit_app_last_log_index(const habit_app_t *app);
bool habit_app_export_session(const habit_app_t *app, habit_session_snapshot_t *out);
void habit_app_restore_session(habit_app_t *app,
                               const habit_session_snapshot_t *session,
                               int64_t now_seconds);

int64_t habit_app_period_day(int64_t timestamp_seconds);
int64_t habit_app_period_week(int64_t timestamp_seconds);
int64_t habit_app_period_month(int64_t timestamp_seconds);
uint32_t habit_app_stat_total(const habit_app_t *app,
                              uint8_t habit_id,
                              habit_stat_view_t stat_view,
                              int64_t now_seconds);
int32_t habit_app_stat_week_delta(const habit_app_t *app,
                                  uint8_t habit_id,
                                  int64_t now_seconds);

#ifdef __cplusplus
}
#endif
