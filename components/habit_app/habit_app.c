#include "habit_app.h"

#include <stdio.h>
#include <string.h>

#include "clock_service.h"

#define COUNT_CONFIRM_SECONDS 2
#define TIME_CONFIRM_SECONDS 4
#define MIN_TIMER_MINUTES 1
#define MAX_TIMER_MINUTES 99

static const habit_config_t s_default_habits[] = {
    {.id = 0, .label = "STR", .type = HABIT_TYPE_COUNT, .time_mode = HABIT_TIME_STOPWATCH, .default_minutes = 1},
    {.id = 1, .label = "MED", .type = HABIT_TYPE_TIME, .time_mode = HABIT_TIME_TIMER, .default_minutes = 10},
    {.id = 2, .label = "STA", .type = HABIT_TYPE_TIME, .time_mode = HABIT_TIME_STOPWATCH, .default_minutes = 1},
};

static habit_config_t *selected_habit(habit_app_t *app)
{
    return &app->habits[app->selected];
}

static const habit_config_t *selected_habit_const(const habit_app_t *app)
{
    return &app->habits[app->selected];
}

static const char *habit_mode_name(const habit_config_t *habit)
{
    if (habit->type == HABIT_TYPE_COUNT) {
        return "COUNT";
    }
    return habit->time_mode == HABIT_TIME_TIMER ? "TIMER" : "STOPWATCH";
}

static habit_ui_icon_t habit_mode_icon(const habit_config_t *habit)
{
    if (habit->type == HABIT_TYPE_COUNT) {
        return HABIT_UI_ICON_COUNT;
    }
    return habit->time_mode == HABIT_TIME_TIMER ? HABIT_UI_ICON_TIMER : HABIT_UI_ICON_STOPWATCH;
}

static void mark_dirty(habit_app_t *app)
{
    app->cached_screen.dirty = true;
}

static bool valid_label_char(char c)
{
    return (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9');
}

static bool valid_habit_label(const char *label)
{
    if (label == NULL || label[0] == '\0') {
        return false;
    }

    for (size_t i = 0; i < HABIT_APP_LABEL_LEN; ++i) {
        if (label[i] == '\0') {
            return true;
        }
        if (!valid_label_char(label[i])) {
            return false;
        }
    }

    return label[HABIT_APP_LABEL_LEN] == '\0';
}

static bool valid_habit_config(const habit_config_t *habit)
{
    if (habit->type != HABIT_TYPE_COUNT && habit->type != HABIT_TYPE_TIME) {
        return false;
    }
    if (habit->time_mode != HABIT_TIME_TIMER && habit->time_mode != HABIT_TIME_STOPWATCH) {
        return false;
    }
    if (!valid_habit_label(habit->label)) {
        return false;
    }
    if (habit->type == HABIT_TYPE_TIME &&
        (habit->default_minutes < MIN_TIMER_MINUTES || habit->default_minutes > MAX_TIMER_MINUTES)) {
        return false;
    }
    return true;
}

int64_t habit_app_period_day(int64_t timestamp_seconds)
{
    clock_calendar_periods_t periods = {0};
    return clock_service_calendar_periods(timestamp_seconds, &periods) ? periods.day_id : INT64_MIN;
}

int64_t habit_app_period_week(int64_t timestamp_seconds)
{
    clock_calendar_periods_t periods = {0};
    return clock_service_calendar_periods(timestamp_seconds, &periods) ? periods.week_id : INT64_MIN;
}

int64_t habit_app_period_month(int64_t timestamp_seconds)
{
    clock_calendar_periods_t periods = {0};
    return clock_service_calendar_periods(timestamp_seconds, &periods) ? periods.month_id : INT64_MIN;
}

static bool append_log(habit_app_t *app, habit_log_t log)
{
    if (app->log_count == HABIT_APP_MAX_LOGS &&
        !app->logs[0].synced && !app->logs[0].deleted) return false;
    if (log.id == 0) log.id = app->next_log_id++;
    if (app->log_count < HABIT_APP_MAX_LOGS) {
        app->logs[app->log_count] = log;
        app->last_log_index = (int)app->log_count;
        app->log_count++;
        app->logs_dirty = true;
        return true;
    }

    const habit_log_t *evicted = &app->logs[0];
    if (!evicted->deleted && clock_service_utc_is_valid(evicted->timestamp_start)) {
        clock_calendar_periods_t periods;
        clock_service_calendar_periods(evicted->timestamp_start, &periods);
        int64_t day = periods.day_id;
        uint32_t value = evicted->type == HABIT_TYPE_COUNT ? evicted->count_value : evicted->duration_seconds;
        size_t index = app->daily_count;
        for (size_t i = 0; i < app->daily_count; ++i) {
            if (app->daily[i].day_id == day && app->daily[i].habit_id == evicted->habit_id &&
                app->daily[i].type == evicted->type) { index = i; break; }
        }
        if (index == app->daily_count && app->daily_count == HABIT_APP_MAX_DAILY_SUMMARIES) {
            int32_t oldest = app->daily[0].day_id;
            for (size_t i = 1; i < app->daily_count; ++i) if (app->daily[i].day_id < oldest) oldest = app->daily[i].day_id;
            size_t write = 0;
            for (size_t i = 0; i < app->daily_count; ++i) if (app->daily[i].day_id != oldest) app->daily[write++] = app->daily[i];
            app->daily_count = write; index = write;
        }
        if (index == app->daily_count) {
            app->daily[index] = (habit_daily_summary_t){
                .day_id=(int32_t)day, .week_id=(int32_t)periods.week_id,
                .month_id=(int32_t)periods.month_id, .habit_id=evicted->habit_id, .type=evicted->type};
            app->daily_count++;
        }
        app->daily[index].value += value;
        if (evicted->id > app->daily[index].through_log_id) app->daily[index].through_log_id = evicted->id;
        app->daily_dirty = true;
    }

    memmove(&app->logs[0],
            &app->logs[1],
            sizeof(app->logs[0]) * (HABIT_APP_MAX_LOGS - 1));
    app->logs[HABIT_APP_MAX_LOGS - 1] = log;
    app->last_log_index = HABIT_APP_MAX_LOGS - 1;
    app->logs_dirty = true;
    return true;
}

static void show_log_full_error(habit_app_t *app, habit_screen_id_t return_screen)
{
    app->screen = HABIT_SCREEN_ERROR;
    app->error_return_screen = return_screen;
    mark_dirty(app);
}

static bool log_matches_time_view(const habit_log_t *log)
{
    return !log->deleted && log->type == HABIT_TYPE_TIME;
}

static size_t time_log_count(const habit_app_t *app)
{
    size_t count = 0;
    for (size_t i = 0; i < app->log_count; ++i) {
        if (log_matches_time_view(&app->logs[i])) {
            count++;
        }
    }
    return count;
}

static const habit_config_t *habit_by_id(const habit_app_t *app, uint8_t habit_id)
{
    for (size_t i = 0; i < app->habit_count; ++i) {
        if (app->habits[i].id == habit_id) {
            return &app->habits[i];
        }
    }
    return NULL;
}

static bool select_habit_by_id(habit_app_t *app, uint8_t habit_id)
{
    for (size_t i = 0; i < app->habit_count; ++i) {
        if (app->habits[i].id == habit_id) {
            app->selected = i;
            return true;
        }
    }
    return false;
}

static const habit_log_t *time_log_at_view_index(const habit_app_t *app, size_t view_index)
{
    size_t seen = 0;
    for (size_t i = app->log_count; i > 0; --i) {
        const habit_log_t *log = &app->logs[i - 1];
        if (!log_matches_time_view(log)) {
            continue;
        }
        if (seen == view_index) {
            return log;
        }
        seen++;
    }
    return NULL;
}

static void log_count_event(habit_app_t *app, int64_t now_seconds)
{
    const habit_config_t *habit = selected_habit_const(app);
    if (!append_log(app, (habit_log_t) {
        .habit_id = habit->id,
        .type = HABIT_TYPE_COUNT,
        .timestamp_start = app->clock_synced ? app->utc_now : 0,
        .timestamp_end = app->clock_synced ? app->utc_now : 0,
        .duration_seconds = 0,
        .count_value = 1,
        .synced = false,
        .deleted = false,
    })) {
        show_log_full_error(app, HABIT_SCREEN_SELECT);
        return;
    }

    app->screen = HABIT_SCREEN_CONFIRM;
    app->confirm_until = now_seconds + COUNT_CONFIRM_SECONDS;
    app->timer_completed = false;
    mark_dirty(app);
}

static uint32_t elapsed_session_seconds(const habit_app_t *app, int64_t now_seconds)
{
    if (!app->session_active) {
        return 0;
    }

    int64_t end = app->session_paused ? app->session_paused_at : now_seconds;
    int64_t elapsed = end - app->session_start - app->session_paused_total;
    return elapsed > 0 ? (uint32_t)elapsed : 0;
}

static void start_time_session(habit_app_t *app, int64_t now_seconds)
{
    const habit_config_t *habit = selected_habit_const(app);
    app->session_active = true;
    app->session_paused = false;
    app->session_start = now_seconds;
    app->session_paused_at = 0;
    app->session_paused_total = 0;
    app->timer_seconds = habit->time_mode == HABIT_TIME_TIMER ? app->setup_minutes * 60 : 0;
    app->session_start_utc = app->clock_synced ? app->utc_now : 0;
    app->session_start_utc_valid = app->clock_synced;
    app->timer_completed = false;
    app->screen = HABIT_SCREEN_SESSION;
    app->session_dirty = true;
    app->last_session_tick_second = now_seconds;
    mark_dirty(app);
}

static void save_time_session(habit_app_t *app, int64_t now_seconds, bool completed_automatically)
{
    if (!app->session_active) {
        return;
    }

    const habit_config_t *habit = selected_habit_const(app);
    uint32_t duration = elapsed_session_seconds(app, now_seconds);
    int64_t timestamp_end = app->clock_synced ? app->utc_now : 0;
    if (habit->time_mode == HABIT_TIME_TIMER && duration >= app->timer_seconds) {
        duration = app->timer_seconds;
        if (app->clock_synced) {
            timestamp_end = app->utc_now - (elapsed_session_seconds(app, now_seconds) - duration);
        }
    }
    if (!append_log(app, (habit_log_t) {
        .habit_id = habit->id,
        .type = HABIT_TYPE_TIME,
        .timestamp_start = app->session_start_utc_valid ? app->session_start_utc :
                           app->clock_synced ? timestamp_end - duration : 0,
        .timestamp_end = timestamp_end,
        .duration_seconds = duration,
        .count_value = 0,
        .synced = false,
        .deleted = false,
    })) {
        app->session_paused = true;
        app->session_paused_at = now_seconds;
        app->session_dirty = true;
        show_log_full_error(app, HABIT_SCREEN_SESSION);
        return;
    }

    app->session_active = false;
    app->session_paused = false;
    app->timer_completed = completed_automatically;
    app->completion_sequence++;
    app->screen = HABIT_SCREEN_CONFIRM;
    app->confirm_until = now_seconds + TIME_CONFIRM_SECONDS;
    app->session_dirty = true;
    app->last_session_tick_second = -1;
    mark_dirty(app);
}

static void cancel_session(habit_app_t *app)
{
    app->session_active = false;
    app->session_paused = false;
    app->timer_completed = false;
    app->screen = HABIT_SCREEN_SELECT;
    app->session_dirty = true;
    app->last_session_tick_second = -1;
    mark_dirty(app);
}

static void undo_last_log(habit_app_t *app)
{
    if (app->last_log_index >= 0 && (size_t)app->last_log_index < app->log_count) {
        app->logs[app->last_log_index].deleted = true;
        app->logs[app->last_log_index].synced = false;
        app->logs_dirty = true;
    }
    app->screen = HABIT_SCREEN_SELECT;
    mark_dirty(app);
}

static void next_habit(habit_app_t *app, int direction)
{
    if (app->habit_count == 0) {
        return;
    }

    int next = (int)app->selected + direction;
    if (next < 0) {
        next = (int)app->habit_count - 1;
    } else if ((size_t)next >= app->habit_count) {
        next = 0;
    }
    app->selected = (size_t)next;
    app->screen = HABIT_SCREEN_SELECT;
    mark_dirty(app);
}

static void next_time_log(habit_app_t *app, int direction)
{
    size_t count = time_log_count(app);
    if (count == 0) {
        app->log_view_index = 0;
        mark_dirty(app);
        return;
    }

    int next = (int)app->log_view_index + direction;
    if (next < 0) {
        next = (int)count - 1;
    } else if ((size_t)next >= count) {
        next = 0;
    }
    app->log_view_index = (size_t)next;
    mark_dirty(app);
}

static void move_home_mode(habit_app_t *app, int direction)
{
    if (direction < 0) {
        if (app->home_mode == HABIT_HOME_LOGS) {
            app->home_mode = HABIT_HOME_ACTION;
        } else if (app->home_mode == HABIT_HOME_ACTION) {
            app->home_mode = HABIT_HOME_HABITS;
        }
    } else if (direction > 0) {
        if (app->home_mode == HABIT_HOME_HABITS) {
            app->home_mode = HABIT_HOME_ACTION;
        } else if (app->home_mode == HABIT_HOME_ACTION) {
            app->home_mode = HABIT_HOME_LOGS;
            app->log_view_index = 0;
        }
    }
    app->screen = HABIT_SCREEN_SELECT;
    mark_dirty(app);
}

void habit_app_init(habit_app_t *app)
{
    memset(app, 0, sizeof(*app));
    memcpy(app->habits, s_default_habits, sizeof(s_default_habits));
    app->habit_count = sizeof(s_default_habits) / sizeof(s_default_habits[0]);
    app->selected = 0;
    app->home_mode = HABIT_HOME_ACTION;
    app->log_view_index = 0;
    app->screen = HABIT_SCREEN_SELECT;
    app->stat_view = HABIT_STAT_WEEK_TOTAL;
    app->last_log_index = -1;
    app->next_log_id = 1;
    app->last_session_tick_second = -1;
    app->cached_screen.dirty = true;
}

void habit_app_update_clock(habit_app_t *app, int64_t utc_seconds, bool synced)
{
    if (app == NULL) {
        return;
    }
    app->clock_synced = synced && clock_service_utc_is_valid(utc_seconds);
    app->utc_now = app->clock_synced ? utc_seconds : 0;
}

bool habit_app_clock_is_synced(const habit_app_t *app)
{
    return app != NULL && app->clock_synced;
}

static bool apply_habits(habit_app_t *app, const habit_config_t *habits, size_t habit_count, bool mark_config_dirty)
{
    if (app == NULL || habits == NULL || habit_count == 0 || habit_count > HABIT_APP_MAX_HABITS) {
        return false;
    }
    if (app->session_active) {
        return false;
    }

    for (size_t i = 0; i < habit_count; ++i) {
        if (!valid_habit_config(&habits[i])) {
            return false;
        }
        for (size_t j = i + 1; j < habit_count; ++j) {
            if (habits[i].id == habits[j].id) {
                return false;
            }
        }
    }

    memset(app->habits, 0, sizeof(app->habits));
    memcpy(app->habits, habits, sizeof(app->habits[0]) * habit_count);
    app->habit_count = habit_count;
    if (app->selected >= app->habit_count) {
        app->selected = 0;
    }
    app->screen = HABIT_SCREEN_SELECT;
    app->home_mode = HABIT_HOME_ACTION;
    app->stat_view = HABIT_STAT_WEEK_TOTAL;
    app->habits_dirty = mark_config_dirty;
    mark_dirty(app);
    return true;
}

bool habit_app_set_habits(habit_app_t *app, const habit_config_t *habits, size_t habit_count)
{
    if (app && app->session_active) return false;
    return apply_habits(app, habits, habit_count, true);
}

bool habit_app_load_habits(habit_app_t *app, const habit_config_t *habits, size_t habit_count)
{
    return apply_habits(app, habits, habit_count, false);
}

void habit_app_tick(habit_app_t *app, int64_t now_seconds)
{
    if (app->screen == HABIT_SCREEN_CONFIRM && now_seconds >= app->confirm_until) {
        app->screen = HABIT_SCREEN_SELECT;
        mark_dirty(app);
    }

    if (app->screen == HABIT_SCREEN_SESSION && app->session_active) {
        const habit_config_t *habit = selected_habit_const(app);
        if (habit->type == HABIT_TYPE_TIME &&
            habit->time_mode == HABIT_TIME_TIMER &&
            !app->session_paused &&
            elapsed_session_seconds(app, now_seconds) >= app->timer_seconds) {
            save_time_session(app, now_seconds, true);
            return;
        }
    }

    if (app->screen == HABIT_SCREEN_SESSION && now_seconds != app->last_session_tick_second) {
        app->last_session_tick_second = now_seconds;
        mark_dirty(app);
    }
}

void habit_app_handle_button(habit_app_t *app,
                             habit_button_t button,
                             habit_press_t press,
                             int64_t now_seconds)
{
    habit_config_t *habit = selected_habit(app);

    if (app->screen == HABIT_SCREEN_CONFIRM && button == HABIT_BUTTON_OK && press == HABIT_PRESS_LONG) {
        undo_last_log(app);
        return;
    }
    if (app->screen == HABIT_SCREEN_CONFIRM && button == HABIT_BUTTON_LEFT && press == HABIT_PRESS_SHORT) {
        undo_last_log(app);
        return;
    }
    if (app->screen == HABIT_SCREEN_CONFIRM &&
        button == HABIT_BUTTON_OK &&
        press == HABIT_PRESS_SHORT &&
        selected_habit_const(app)->type == HABIT_TYPE_COUNT) {
        log_count_event(app, now_seconds);
        return;
    }

    switch (app->screen) {
    case HABIT_SCREEN_SELECT:
        if (press == HABIT_PRESS_LONG && button == HABIT_BUTTON_LEFT) {
            move_home_mode(app, -1);
        } else if (press == HABIT_PRESS_LONG && button == HABIT_BUTTON_RIGHT) {
            move_home_mode(app, 1);
        } else if (app->home_mode == HABIT_HOME_HABITS) {
            if (button == HABIT_BUTTON_LEFT) {
                next_habit(app, -1);
            } else if (button == HABIT_BUTTON_RIGHT) {
                next_habit(app, 1);
            }
        } else if (app->home_mode == HABIT_HOME_LOGS) {
            size_t logs = time_log_count(app);
            if (logs == 0 && (button == HABIT_BUTTON_LEFT || button == HABIT_BUTTON_RIGHT)) {
                move_home_mode(app, -1);
            } else if (button == HABIT_BUTTON_LEFT) {
                next_time_log(app, -1);
            } else if (button == HABIT_BUTTON_RIGHT) {
                next_time_log(app, 1);
            } else if (button == HABIT_BUTTON_OK) {
                const habit_log_t *log = time_log_at_view_index(app, app->log_view_index);
                if (log != NULL && select_habit_by_id(app, log->habit_id)) {
                    app->screen = HABIT_SCREEN_STATS;
                    app->stat_view = HABIT_STAT_WEEK_TOTAL;
                } else {
                    app->home_mode = HABIT_HOME_ACTION;
                }
                mark_dirty(app);
            }
        } else if (press == HABIT_PRESS_LONG && button == HABIT_BUTTON_OK) {
            app->screen = HABIT_SCREEN_STATS;
            app->stat_view = HABIT_STAT_WEEK_TOTAL;
            mark_dirty(app);
        } else if (button == HABIT_BUTTON_LEFT) {
            next_habit(app, -1);
        } else if (button == HABIT_BUTTON_RIGHT) {
            next_habit(app, 1);
        } else if (button == HABIT_BUTTON_OK && habit->type == HABIT_TYPE_COUNT) {
            log_count_event(app, now_seconds);
        } else if (button == HABIT_BUTTON_OK && habit->type == HABIT_TYPE_TIME) {
            app->setup_minutes = habit->default_minutes;
            if (habit->time_mode == HABIT_TIME_TIMER) {
                app->screen = HABIT_SCREEN_TIMER_SETUP;
                mark_dirty(app);
            } else {
                start_time_session(app, now_seconds);
            }
        }
        break;

    case HABIT_SCREEN_TIMER_SETUP:
        if (button == HABIT_BUTTON_LEFT && press == HABIT_PRESS_LONG) {
            app->screen = HABIT_SCREEN_SELECT;
            mark_dirty(app);
        } else if (button == HABIT_BUTTON_LEFT && app->setup_minutes > MIN_TIMER_MINUTES) {
            app->setup_minutes--;
            mark_dirty(app);
        } else if (button == HABIT_BUTTON_RIGHT && app->setup_minutes < MAX_TIMER_MINUTES) {
            app->setup_minutes++;
            mark_dirty(app);
        } else if (button == HABIT_BUTTON_OK) {
            start_time_session(app, now_seconds);
        }
        break;

    case HABIT_SCREEN_SESSION:
        if (button == HABIT_BUTTON_LEFT && press == HABIT_PRESS_LONG) {
            cancel_session(app);
        } else if (button == HABIT_BUTTON_LEFT && press == HABIT_PRESS_SHORT) {
            app->screen = HABIT_SCREEN_CANCEL_CONFIRM;
            mark_dirty(app);
        } else if (button == HABIT_BUTTON_RIGHT) {
            save_time_session(app, now_seconds, false);
        } else if (button == HABIT_BUTTON_OK && press == HABIT_PRESS_LONG) {
            save_time_session(app, now_seconds, false);
        } else if (button == HABIT_BUTTON_OK && press == HABIT_PRESS_SHORT) {
            if (app->session_paused) {
                app->session_paused_total += (uint32_t)(now_seconds - app->session_paused_at);
                app->session_paused = false;
            } else {
                app->session_paused = true;
                app->session_paused_at = now_seconds;
            }
            app->session_dirty = true;
            mark_dirty(app);
        }
        break;

    case HABIT_SCREEN_CANCEL_CONFIRM:
        if (button == HABIT_BUTTON_RIGHT) {
            cancel_session(app);
        } else if (button == HABIT_BUTTON_LEFT || button == HABIT_BUTTON_OK) {
            app->screen = HABIT_SCREEN_SESSION;
            mark_dirty(app);
        }
        break;

    case HABIT_SCREEN_STATS:
        if (button == HABIT_BUTTON_OK) {
            app->screen = HABIT_SCREEN_SELECT;
            mark_dirty(app);
        } else if (button == HABIT_BUTTON_LEFT) {
            app->stat_view = app->stat_view == 0 ? HABIT_STAT_COUNT - 1 : app->stat_view - 1;
            mark_dirty(app);
        } else if (button == HABIT_BUTTON_RIGHT) {
            app->stat_view = (app->stat_view + 1) % HABIT_STAT_COUNT;
            mark_dirty(app);
        }
        break;

    case HABIT_SCREEN_ERROR:
        if (button == HABIT_BUTTON_OK || button == HABIT_BUTTON_LEFT) {
            app->screen = app->error_return_screen;
            mark_dirty(app);
        }
        break;

    case HABIT_SCREEN_CONFIRM:
        break;
    }
}

bool habit_app_take_logs_dirty(habit_app_t *app)
{
    bool dirty = app->logs_dirty;
    app->logs_dirty = false;
    return dirty;
}

bool habit_app_take_session_dirty(habit_app_t *app)
{
    bool dirty = app->session_dirty;
    app->session_dirty = false;
    return dirty;
}

bool habit_app_take_habits_dirty(habit_app_t *app)
{
    bool dirty = app->habits_dirty;
    app->habits_dirty = false;
    return dirty;
}

bool habit_app_take_daily_dirty(habit_app_t *app)
{
    bool dirty = app->daily_dirty; app->daily_dirty = false; return dirty;
}

void habit_app_load_daily(habit_app_t *app, const habit_daily_summary_t *daily, size_t count)
{
    if (!app || (!daily && count)) return;
    if (count > HABIT_APP_MAX_DAILY_SUMMARIES) count = HABIT_APP_MAX_DAILY_SUMMARIES;
    if (count) memcpy(app->daily, daily, count * sizeof(*daily));
    app->daily_count = count; app->daily_dirty = false;
}

size_t habit_app_copy_daily(const habit_app_t *app, habit_daily_summary_t *out, size_t max_count)
{
    if (!app) return 0;
    if (!out || max_count == 0) return app->daily_count;
    size_t count = app->daily_count < max_count ? app->daily_count : max_count;
    memcpy(out, app->daily, count * sizeof(*out)); return count;
}

size_t habit_app_copy_habits(const habit_app_t *app, habit_config_t *out, size_t max_habits)
{
    if (out == NULL || max_habits == 0) {
        return app->habit_count;
    }

    size_t count = app->habit_count < max_habits ? app->habit_count : max_habits;
    memcpy(out, app->habits, sizeof(app->habits[0]) * count);
    return count;
}

void habit_app_load_logs(habit_app_t *app, const habit_log_t *logs, size_t log_count)
{
    if (logs == NULL || log_count == 0) {
        app->log_count = 0;
        app->last_log_index = -1;
        return;
    }

    if (log_count > HABIT_APP_MAX_LOGS) {
        log_count = HABIT_APP_MAX_LOGS;
    }

    memcpy(app->logs, logs, sizeof(app->logs[0]) * log_count);
    app->log_count = log_count;
    app->next_log_id = 1;
    for (size_t i = 0; i < app->log_count; ++i) {
        if (app->logs[i].id == 0) {
            app->logs[i].id = app->next_log_id;
        }
        if (app->logs[i].id >= app->next_log_id) {
            app->next_log_id = app->logs[i].id + 1;
        }
    }
    app->last_log_index = -1;
    for (size_t i = app->log_count; i > 0; --i) {
        if (!app->logs[i - 1].deleted) {
            app->last_log_index = (int)(i - 1);
            break;
        }
    }
    app->logs_dirty = false;
}

size_t habit_app_copy_logs(const habit_app_t *app, habit_log_t *out, size_t max_logs)
{
    if (out == NULL || max_logs == 0) {
        return app->log_count;
    }

    size_t count = app->log_count < max_logs ? app->log_count : max_logs;
    memcpy(out, app->logs, sizeof(app->logs[0]) * count);
    return count;
}

bool habit_app_get_log(const habit_app_t *app, size_t index, habit_log_t *out)
{
    if (out == NULL || index >= app->log_count) {
        return false;
    }

    *out = app->logs[index];
    return true;
}

bool habit_app_mark_log_synced(habit_app_t *app, uint64_t log_id)
{
    if (app == NULL || log_id == 0) {
        return false;
    }
    for (size_t i = 0; i < app->log_count; ++i) {
        if (app->logs[i].id == log_id && !app->logs[i].deleted) {
            if (!app->logs[i].synced) {
                app->logs[i].synced = true;
                app->logs_dirty = true;
            }
            return true;
        }
    }
    return false;
}

int habit_app_last_log_index(const habit_app_t *app)
{
    return app->last_log_index;
}

uint32_t habit_app_completion_sequence(const habit_app_t *app)
{
    return app == NULL ? 0 : app->completion_sequence;
}

bool habit_app_export_session(const habit_app_t *app, habit_session_snapshot_t *out)
{
    if (out == NULL || !app->session_active) {
        return false;
    }

    const habit_config_t *habit = selected_habit_const(app);
    *out = (habit_session_snapshot_t) {
        .session_active = app->session_active,
        .session_paused = app->session_paused,
        .selected_habit_id = habit->id,
        .time_mode = habit->time_mode,
        .session_start = app->session_start,
        .session_paused_at = app->session_paused_at,
        .session_paused_total = app->session_paused_total,
        .timer_seconds = app->timer_seconds,
        .setup_minutes = app->setup_minutes,
        .session_start_utc = app->session_start_utc,
        .session_start_utc_valid = app->session_start_utc_valid,
    };
    return true;
}

void habit_app_restore_session(habit_app_t *app,
                               const habit_session_snapshot_t *session,
                               int64_t now_seconds)
{
    if (session == NULL || !session->session_active) {
        return;
    }

    for (size_t i = 0; i < app->habit_count; ++i) {
        if (app->habits[i].id == session->selected_habit_id) {
            app->selected = i;
            break;
        }
    }

    app->session_active = true;
    app->session_paused = session->session_paused;
    app->session_start = session->session_start;
    app->session_paused_at = session->session_paused ? session->session_paused_at : 0;
    app->session_paused_total = session->session_paused_total;
    app->timer_seconds = session->timer_seconds;
    app->setup_minutes = session->setup_minutes;
    app->session_start_utc = session->session_start_utc;
    app->session_start_utc_valid = session->session_start_utc_valid;
    app->screen = HABIT_SCREEN_SESSION;
    app->last_session_tick_second = now_seconds;
    if (!app->session_paused && app->session_start > now_seconds) {
        app->session_start = now_seconds;
    }
    mark_dirty(app);
}

uint32_t habit_app_stat_total(const habit_app_t *app,
                              uint8_t habit_id,
                              habit_stat_view_t stat_view,
                              int64_t now_seconds)
{
    if (!clock_service_utc_is_valid(now_seconds)) {
        return 0;
    }
    int64_t current;
    int64_t previous;
    bool use_month = false;

    if (stat_view == HABIT_STAT_MONTH_TOTAL) {
        current = habit_app_period_month(now_seconds);
        previous = current - 1;
        use_month = true;
    } else {
        current = habit_app_period_week(now_seconds);
        previous = current - 1;
    }

    uint32_t total = 0;
    uint32_t prev_total = 0;
    uint32_t active_days = 0;
    int64_t seen_days[7] = {0};
    const habit_config_t *configured = habit_by_id(app, habit_id);
    if (!configured) return 0;

    for (size_t i = 0; i < app->daily_count; ++i) {
        const habit_daily_summary_t *summary = &app->daily[i];
        if (summary->habit_id != habit_id || summary->type != configured->type) continue;
        int64_t period = use_month ? summary->month_id : summary->week_id;
        if (period == current) {
            total += summary->value;
            if (stat_view == HABIT_STAT_WEEK_AVG) {
                bool seen = false;
                for (uint32_t d = 0; d < active_days; ++d) seen = seen || seen_days[d] == summary->day_id;
                if (!seen && active_days < 7) seen_days[active_days++] = summary->day_id;
            }
        } else if (period == previous) prev_total += summary->value;
    }

    for (size_t i = 0; i < app->log_count; ++i) {
        const habit_log_t *log = &app->logs[i];
        if (log->deleted || log->habit_id != habit_id || log->type != configured->type) {
            continue;
        }
        if (!clock_service_utc_is_valid(log->timestamp_start)) continue;

        bool summarized = false;
        int64_t log_day = habit_app_period_day(log->timestamp_start);
        for (size_t d = 0; d < app->daily_count; ++d) {
            const habit_daily_summary_t *summary = &app->daily[d];
            if (summary->habit_id == log->habit_id && summary->type == log->type &&
                summary->day_id == log_day && log->id <= summary->through_log_id) { summarized = true; break; }
        }
        if (summarized) continue;

        int64_t period = use_month ? habit_app_period_month(log->timestamp_start) :
                         habit_app_period_week(log->timestamp_start);
        uint32_t value = log->type == HABIT_TYPE_COUNT ? log->count_value : log->duration_seconds;

        if (period == current) {
            total += value;
            if (stat_view == HABIT_STAT_WEEK_AVG) {
                int64_t day = habit_app_period_day(log->timestamp_start);
                bool seen = false;
                for (uint32_t d = 0; d < active_days; ++d) {
                    seen = seen || seen_days[d] == day;
                }
                if (!seen && active_days < 7) {
                    seen_days[active_days++] = day;
                }
            }
        } else if (period == previous) {
            prev_total += value;
        }
    }

    if (stat_view == HABIT_STAT_WEEK_DELTA) {
        return total >= prev_total ? total - prev_total : prev_total - total;
    }
    if (stat_view == HABIT_STAT_WEEK_AVG) {
        return active_days > 0 ? total / active_days : 0;
    }
    return total;
}

static void format_duration(uint32_t seconds, char *out, size_t out_size)
{
    if (seconds < 60) {
        snprintf(out, out_size, "%luS", (unsigned long)seconds);
        return;
    }

    uint32_t minutes = seconds / 60;
    if (minutes >= 60) {
        snprintf(out, out_size, "%luH%02lu", (unsigned long)(minutes / 60), (unsigned long)(minutes % 60));
    } else if (seconds % 60 != 0 && minutes < 10) {
        snprintf(out, out_size, "%luM%02lu", (unsigned long)minutes, (unsigned long)(seconds % 60));
    } else {
        snprintf(out, out_size, "%luM", (unsigned long)minutes);
    }
}

static void format_live_duration(uint32_t seconds, char *out, size_t out_size)
{
    uint32_t minutes = seconds / 60;
    uint32_t remaining_seconds = seconds % 60;
    if (minutes < 100) {
        snprintf(out, out_size, "%lu:%02lu",
                 (unsigned long)minutes,
                 (unsigned long)remaining_seconds);
        return;
    }

    uint32_t hours = minutes / 60;
    uint32_t remaining_minutes = minutes % 60;
    if (hours > 99) {
        hours = 99;
        remaining_minutes = 59;
    }
    snprintf(out, out_size, "%luH%02lu",
             (unsigned long)hours,
             (unsigned long)remaining_minutes);
}

static uint32_t log_value(const habit_log_t *log)
{
    return log->type == HABIT_TYPE_COUNT ? log->count_value : log->duration_seconds;
}

static uint32_t total_for_period(const habit_app_t *app,
                                 uint8_t habit_id,
                                 int64_t period,
                                 bool use_month)
{
    uint32_t total = 0;
    const habit_config_t *configured = habit_by_id(app, habit_id);
    if (!configured) return 0;
    for (size_t i = 0; i < app->daily_count; ++i) {
        const habit_daily_summary_t *summary = &app->daily[i];
        if (summary->habit_id != habit_id || summary->type != configured->type) continue;
        int64_t summary_period = use_month ? summary->month_id : summary->week_id;
        if (summary_period == period) total += summary->value;
    }
    for (size_t i = 0; i < app->log_count; ++i) {
        const habit_log_t *log = &app->logs[i];
        if (log->deleted || log->habit_id != habit_id || log->type != configured->type) {
            continue;
        }
        if (!clock_service_utc_is_valid(log->timestamp_start)) continue;

        bool summarized = false;
        int64_t log_day = habit_app_period_day(log->timestamp_start);
        for (size_t d = 0; d < app->daily_count; ++d) {
            const habit_daily_summary_t *summary = &app->daily[d];
            if (summary->habit_id == log->habit_id && summary->type == log->type &&
                summary->day_id == log_day && log->id <= summary->through_log_id) { summarized = true; break; }
        }
        if (summarized) continue;

        int64_t log_period = use_month ? habit_app_period_month(log->timestamp_start) :
                             habit_app_period_week(log->timestamp_start);
        if (log_period == period) {
            total += log_value(log);
        }
    }
    return total;
}

int32_t habit_app_stat_week_delta(const habit_app_t *app,
                                  uint8_t habit_id,
                                  int64_t now_seconds)
{
    if (!clock_service_utc_is_valid(now_seconds)) {
        return 0;
    }
    int64_t current = habit_app_period_week(now_seconds);
    uint32_t total = total_for_period(app, habit_id, current, false);
    uint32_t previous = total_for_period(app, habit_id, current - 1, false);
    return (int32_t)total - (int32_t)previous;
}

const habit_screen_t *habit_app_screen(habit_app_t *app, int64_t now_seconds)
{
    habit_screen_t *screen = &app->cached_screen;
    if (!screen->dirty) {
        return screen;
    }

    memset(screen, 0, sizeof(*screen));
    screen->id = app->screen;
    screen->home_mode = app->home_mode;
    const habit_config_t *habit = selected_habit_const(app);

    switch (app->screen) {
    case HABIT_SCREEN_SELECT:
        screen->show_home_nav = true;
        screen->left_action = HABIT_UI_ICON_LEFT;
        screen->right_action = HABIT_UI_ICON_RIGHT;
        if (app->home_mode == HABIT_HOME_HABITS) {
            screen->icon = HABIT_UI_ICON_HABITS;
            screen->ok_action = HABIT_UI_ICON_NONE;
            snprintf(screen->header, sizeof(screen->header), "HABITS");
            snprintf(screen->primary, sizeof(screen->primary), "%s", habit->label);
            if (habit->type == HABIT_TYPE_TIME && habit->time_mode == HABIT_TIME_TIMER) {
                snprintf(screen->secondary, sizeof(screen->secondary), "TIMER %u MIN", habit->default_minutes);
            } else {
                snprintf(screen->secondary, sizeof(screen->secondary), "%s", habit_mode_name(habit));
            }
        } else if (app->home_mode == HABIT_HOME_LOGS) {
            const habit_log_t *log = time_log_at_view_index(app, app->log_view_index);
            screen->icon = log == NULL ? HABIT_UI_ICON_EMPTY : HABIT_UI_ICON_LOGS;
            screen->ok_action = log == NULL ? HABIT_UI_ICON_HOME : HABIT_UI_ICON_CHART;
            snprintf(screen->header, sizeof(screen->header), "LOGS");
            if (log == NULL) {
                snprintf(screen->primary, sizeof(screen->primary), "NO LOGS");
            } else {
                const habit_config_t *log_habit = habit_by_id(app, log->habit_id);
                const char *label = log_habit == NULL ? "???" : log_habit->label;
                format_duration(log->duration_seconds, screen->primary, sizeof(screen->primary));
                snprintf(screen->secondary, sizeof(screen->secondary), "%s TIME", label);
            }
        } else {
            screen->icon = habit_mode_icon(habit);
            screen->ok_action = habit->type == HABIT_TYPE_COUNT ? HABIT_UI_ICON_PLUS : HABIT_UI_ICON_PLAY;
            snprintf(screen->header, sizeof(screen->header), "ACTION");
            snprintf(screen->primary, sizeof(screen->primary), "%s", habit->label);
            if (habit->type == HABIT_TYPE_TIME && habit->time_mode == HABIT_TIME_TIMER) {
                snprintf(screen->secondary, sizeof(screen->secondary), "%u MIN TIMER", habit->default_minutes);
            } else {
                snprintf(screen->secondary, sizeof(screen->secondary), "%s", habit_mode_name(habit));
            }
        }
        break;

    case HABIT_SCREEN_CONFIRM: {
        const habit_log_t *log = app->last_log_index >= 0 ? &app->logs[app->last_log_index] : NULL;
        bool count_log = log != NULL && log->type == HABIT_TYPE_COUNT;
        const habit_config_t *log_habit = log == NULL ? habit : habit_by_id(app, log->habit_id);
        screen->icon = HABIT_UI_ICON_CHECK;
        screen->left_action = HABIT_UI_ICON_UNDO;
        screen->ok_action = count_log ? HABIT_UI_ICON_PLUS : HABIT_UI_ICON_HOME;
        snprintf(screen->header,
                 sizeof(screen->header),
                 "%s",
                 count_log ? "LOGGED" : app->timer_completed ? "TIMER DONE" : "SAVED");
        if (count_log) {
            snprintf(screen->primary, sizeof(screen->primary), "+1");
        } else if (log != NULL) {
            format_duration(log->duration_seconds, screen->primary, sizeof(screen->primary));
        } else {
            snprintf(screen->primary, sizeof(screen->primary), "DONE");
        }
        snprintf(screen->secondary, sizeof(screen->secondary), "%s %s",
                 log_habit == NULL ? "???" : log_habit->label,
                 count_log ? "COUNT" : "TIME");
        break;
    }

    case HABIT_SCREEN_TIMER_SETUP:
        screen->icon = HABIT_UI_ICON_TIMER;
        screen->left_action = HABIT_UI_ICON_MINUS;
        screen->ok_action = HABIT_UI_ICON_PLAY;
        screen->right_action = HABIT_UI_ICON_PLUS;
        snprintf(screen->header, sizeof(screen->header), "%s TIMER", habit->label);
        snprintf(screen->primary, sizeof(screen->primary), "%lu", (unsigned long)app->setup_minutes);
        snprintf(screen->secondary, sizeof(screen->secondary), "MINUTES");
        break;

    case HABIT_SCREEN_SESSION: {
        uint32_t elapsed = elapsed_session_seconds(app, now_seconds);
        uint32_t shown = elapsed;
        if (habit->time_mode == HABIT_TIME_TIMER) {
            shown = elapsed >= app->timer_seconds ? 0 : app->timer_seconds - elapsed;
        }
        screen->icon = habit_mode_icon(habit);
        screen->left_action = HABIT_UI_ICON_CLOSE;
        screen->ok_action = app->session_paused ? HABIT_UI_ICON_PLAY : HABIT_UI_ICON_PAUSE;
        screen->right_action = HABIT_UI_ICON_CHECK;
        snprintf(screen->header, sizeof(screen->header), "%s %s", habit->label, habit_mode_name(habit));
        format_live_duration(shown, screen->primary, sizeof(screen->primary));
        snprintf(screen->secondary, sizeof(screen->secondary), "%s", app->session_paused ? "PAUSED" : "RUNNING");
        break;
    }

    case HABIT_SCREEN_CANCEL_CONFIRM:
        screen->icon = HABIT_UI_ICON_CLOSE;
        screen->left_action = HABIT_UI_ICON_BACK;
        screen->right_action = HABIT_UI_ICON_CLOSE;
        snprintf(screen->header, sizeof(screen->header), "CANCEL %s?", habit->label);
        snprintf(screen->primary, sizeof(screen->primary), "NO SAVE");
        break;

    case HABIT_SCREEN_STATS: {
        uint32_t total = habit_app_stat_total(app, habit->id, app->stat_view, app->utc_now);
        const char *heading = "THIS WEEK";
        if (app->stat_view == HABIT_STAT_WEEK_DELTA) {
            heading = "VS LAST WEEK";
        } else if (app->stat_view == HABIT_STAT_MONTH_TOTAL) {
            heading = "THIS MONTH";
        } else if (app->stat_view == HABIT_STAT_WEEK_AVG) {
            heading = "DAILY AVERAGE";
        }
        screen->icon = HABIT_UI_ICON_CHART;
        screen->left_action = HABIT_UI_ICON_LEFT;
        screen->ok_action = HABIT_UI_ICON_HOME;
        screen->right_action = HABIT_UI_ICON_RIGHT;
        snprintf(screen->header, sizeof(screen->header), "%s", heading);
        snprintf(screen->secondary, sizeof(screen->secondary), "%s %s",
                 habit->label,
                 habit->type == HABIT_TYPE_COUNT ? "COUNT" : "TIME");
        if (!app->clock_synced) {
            snprintf(screen->primary, sizeof(screen->primary), "--");
            snprintf(screen->secondary, sizeof(screen->secondary), "NO CLOCK");
            break;
        }
        if (app->stat_view == HABIT_STAT_WEEK_DELTA) {
            int32_t delta = habit_app_stat_week_delta(app, habit->id, app->utc_now);
            char sign = delta >= 0 ? '+' : '-';
            uint32_t absolute = delta >= 0 ? (uint32_t)delta : (uint32_t)-delta;
            if (habit->type == HABIT_TYPE_TIME) {
                screen->primary[0] = sign;
                format_duration(absolute, &screen->primary[1], sizeof(screen->primary) - 1);
            } else {
                if (absolute > 999999) {
                    absolute = 999999;
                }
                snprintf(screen->primary, sizeof(screen->primary), "%c%lu", sign, (unsigned long)absolute);
            }
        } else if (habit->type == HABIT_TYPE_TIME) {
            format_duration(total, screen->primary, sizeof(screen->primary));
        } else {
            snprintf(screen->primary, sizeof(screen->primary), "%lu", (unsigned long)total);
        }
        break;
    }

    case HABIT_SCREEN_ERROR:
        screen->icon = HABIT_UI_ICON_CLOSE;
        screen->ok_action = HABIT_UI_ICON_BACK;
        snprintf(screen->header, sizeof(screen->header), "STORAGE");
        snprintf(screen->primary, sizeof(screen->primary), "LOG FULL");
        snprintf(screen->secondary, sizeof(screen->secondary), "SYNC NEEDED");
        break;
    }

    screen->dirty = false;
    return screen;
}
