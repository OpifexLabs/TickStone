#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define HABIT_APP_MAX_HABITS 10
#define HABIT_APP_LABEL_LEN 3
#define HABIT_APP_NAME_LEN 15
#define HABIT_APP_MAX_LOGS 512
#define HABIT_APP_MAX_DAILY_SUMMARIES 700

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
    HABIT_SCREEN_TIME_MODE,
    HABIT_SCREEN_TIMER_SETUP,
    HABIT_SCREEN_SESSION,
    HABIT_SCREEN_CANCEL_CONFIRM,
    HABIT_SCREEN_STATS,
    HABIT_SCREEN_ERROR,
} habit_screen_id_t;

typedef enum {
    HABIT_STAT_LATEST_LOG = 0,
    HABIT_STAT_WEEK_TOTAL,
    HABIT_STAT_WEEK_DELTA,
    HABIT_STAT_MONTH_TOTAL,
    HABIT_STAT_WEEK_AVG,
    HABIT_STAT_COUNT,
} habit_stat_view_t;

typedef enum {
    HABIT_HOME_ACTION = 0,
    HABIT_HOME_HABITS,
} habit_home_mode_t;

typedef enum {
    HABIT_UI_ICON_NONE = 0,
    HABIT_UI_ICON_ACTION,
    HABIT_UI_ICON_HABITS,
    HABIT_UI_ICON_LOGS,
    HABIT_UI_ICON_COUNT,
    HABIT_UI_ICON_TIMER,
    HABIT_UI_ICON_STOPWATCH,
    HABIT_UI_ICON_CHECK,
    HABIT_UI_ICON_EMPTY,
    HABIT_UI_ICON_PLAY,
    HABIT_UI_ICON_PAUSE,
    HABIT_UI_ICON_CLOSE,
    HABIT_UI_ICON_CHART,
    HABIT_UI_ICON_HOME,
    HABIT_UI_ICON_PLUS,
    HABIT_UI_ICON_MINUS,
    HABIT_UI_ICON_LEFT,
    HABIT_UI_ICON_RIGHT,
    HABIT_UI_ICON_EDIT,
    HABIT_UI_ICON_UNDO,
    HABIT_UI_ICON_BACK,
} habit_ui_icon_t;

typedef struct {
    uint8_t id;
    char label[HABIT_APP_LABEL_LEN + 1];
    char name[HABIT_APP_NAME_LEN + 1];
    habit_type_t type;
    habit_time_mode_t time_mode;
    uint16_t default_minutes;
} habit_config_t;

typedef struct {
    uint64_t id;
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
    int32_t day_id;
    int32_t week_id;
    int32_t month_id;
    uint8_t habit_id;
    habit_type_t type;
    uint32_t value;
    uint64_t through_log_id;
} habit_daily_summary_t;

typedef struct {
    habit_screen_id_t id;
    habit_home_mode_t home_mode;
    habit_ui_icon_t icon;
    habit_ui_icon_t left_action;
    habit_ui_icon_t ok_action;
    habit_ui_icon_t right_action;
    char header[16];
    char primary[12];
    char secondary[16];
    bool show_home_nav;
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
    int64_t session_start_utc;
    bool session_start_utc_valid;
} habit_session_snapshot_t;

typedef struct {
    habit_config_t habits[HABIT_APP_MAX_HABITS];
    size_t habit_count;
    habit_log_t logs[HABIT_APP_MAX_LOGS];
    size_t log_count;
    int last_log_index;
    uint64_t next_log_id;
    habit_daily_summary_t daily[HABIT_APP_MAX_DAILY_SUMMARIES];
    size_t daily_count;

    size_t selected;
    habit_home_mode_t home_mode;
    habit_screen_id_t screen;
    habit_screen_id_t error_return_screen;
    habit_stat_view_t stat_view;
    int64_t confirm_until;

    bool session_active;
    bool session_paused;
    int64_t session_start;
    int64_t session_paused_at;
    uint32_t session_paused_total;
    uint32_t timer_seconds;
    uint32_t setup_minutes;
    habit_time_mode_t session_time_mode;
    uint32_t completion_sequence;
    bool timer_completed;
    int64_t utc_now;
    int64_t session_start_utc;
    bool clock_synced;
    bool session_start_utc_valid;

    bool logs_dirty;
    bool session_dirty;
    bool habits_dirty;
    bool daily_dirty;
    int64_t last_session_tick_second;

    habit_screen_t cached_screen;
} habit_app_t;

void habit_app_init(habit_app_t *app);
void habit_app_update_clock(habit_app_t *app, int64_t utc_seconds, bool synced);
bool habit_app_clock_is_synced(const habit_app_t *app);
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
bool habit_app_take_daily_dirty(habit_app_t *app);
size_t habit_app_copy_habits(const habit_app_t *app, habit_config_t *out, size_t max_habits);
void habit_app_load_logs(habit_app_t *app, const habit_log_t *logs, size_t log_count);
size_t habit_app_copy_logs(const habit_app_t *app, habit_log_t *out, size_t max_logs);
bool habit_app_get_log(const habit_app_t *app, size_t index, habit_log_t *out);
bool habit_app_mark_log_synced(habit_app_t *app, uint64_t log_id);
void habit_app_load_daily(habit_app_t *app, const habit_daily_summary_t *daily, size_t count);
size_t habit_app_copy_daily(const habit_app_t *app, habit_daily_summary_t *out, size_t max_count);
int habit_app_last_log_index(const habit_app_t *app);
uint32_t habit_app_completion_sequence(const habit_app_t *app);
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
