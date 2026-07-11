#include "habit_app.h"
#include "clock_service.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static void press(habit_app_t *app, habit_button_t button, int64_t now)
{
    habit_app_handle_button(app, button, HABIT_PRESS_SHORT, now);
}

static void long_press(habit_app_t *app, habit_button_t button, int64_t now)
{
    habit_app_handle_button(app, button, HABIT_PRESS_LONG, now);
}

static void test_day_boundary(void)
{
    assert(habit_app_period_day(1711854000) == habit_app_period_day(1711853940) + 1);
}

static void test_count_and_undo(void)
{
    habit_app_t app;
    habit_app_init(&app);

    press(&app, HABIT_BUTTON_OK, 100);
    assert(app.log_count == 1);
    assert(app.logs[0].type == HABIT_TYPE_COUNT);
    assert(app.logs[0].count_value == 1);
    assert(!app.logs[0].synced);

    app.logs[0].synced = true;
    long_press(&app, HABIT_BUTTON_OK, 101);
    assert(app.logs[0].deleted);
    assert(!app.logs[0].synced);
}

static void test_navigation_wraps_between_habits(void)
{
    habit_app_t app;
    habit_app_init(&app);

    const habit_screen_t *screen = habit_app_screen(&app, 99);
    assert(strcmp(screen->header, "ACTION") == 0);
    assert(strcmp(screen->primary, "STR") == 0);
    assert(strcmp(screen->secondary, "COUNT") == 0);
    assert(screen->icon == HABIT_UI_ICON_COUNT);
    assert(screen->ok_action == HABIT_UI_ICON_PLUS);
    assert(screen->show_home_nav);

    press(&app, HABIT_BUTTON_LEFT, 100);
    assert(strcmp(app.habits[app.selected].label, "STA") == 0);
    press(&app, HABIT_BUTTON_RIGHT, 101);
    assert(strcmp(app.habits[app.selected].label, "STR") == 0);
}

static void test_home_modes_habits_and_logs(void)
{
    habit_app_t app;
    habit_app_init(&app);

    long_press(&app, HABIT_BUTTON_LEFT, 100);
    assert(app.home_mode == HABIT_HOME_HABITS);
    const habit_screen_t *screen = habit_app_screen(&app, 100);
    assert(strcmp(screen->header, "HABITS") == 0);
    assert(strcmp(screen->primary, "STR") == 0);
    assert(strcmp(screen->secondary, "COUNT") == 0);
    assert(screen->icon == HABIT_UI_ICON_HABITS);
    assert(screen->ok_action == HABIT_UI_ICON_NONE);
    habit_config_t unchanged = app.habits[app.selected];
    press(&app, HABIT_BUTTON_OK, 101);
    long_press(&app, HABIT_BUTTON_OK, 102);
    assert(memcmp(&unchanged, &app.habits[app.selected], sizeof(unchanged)) == 0);

    long_press(&app, HABIT_BUTTON_RIGHT, 103);
    assert(app.home_mode == HABIT_HOME_ACTION);

    long_press(&app, HABIT_BUTTON_RIGHT, 104);
    assert(app.home_mode == HABIT_HOME_LOGS);
    screen = habit_app_screen(&app, 104);
    assert(strcmp(screen->header, "LOGS") == 0);
    assert(strcmp(screen->primary, "NO LOGS") == 0);
    assert(strcmp(screen->secondary, "") == 0);
    assert(screen->icon == HABIT_UI_ICON_EMPTY);
    assert(screen->ok_action == HABIT_UI_ICON_HOME);

    press(&app, HABIT_BUTTON_LEFT, 105);
    assert(app.home_mode == HABIT_HOME_ACTION);

    long_press(&app, HABIT_BUTTON_RIGHT, 106);
    assert(app.home_mode == HABIT_HOME_LOGS);
    press(&app, HABIT_BUTTON_RIGHT, 107);
    assert(app.home_mode == HABIT_HOME_ACTION);
}

static void test_log_home_shows_time_logs(void)
{
    habit_app_t app;
    habit_app_init(&app);

    press(&app, HABIT_BUTTON_RIGHT, 100);
    press(&app, HABIT_BUTTON_OK, 101);
    press(&app, HABIT_BUTTON_OK, 102);
    long_press(&app, HABIT_BUTTON_OK, 162);
    habit_app_tick(&app, 166);
    press(&app, HABIT_BUTTON_RIGHT, 167);
    press(&app, HABIT_BUTTON_OK, 168);
    long_press(&app, HABIT_BUTTON_OK, 198);
    habit_app_tick(&app, 202);

    long_press(&app, HABIT_BUTTON_RIGHT, 203);
    assert(app.home_mode == HABIT_HOME_LOGS);
    const habit_screen_t *screen = habit_app_screen(&app, 203);
    assert(strcmp(screen->primary, "30S") == 0);
    assert(strcmp(screen->secondary, "STA TIME") == 0);
    assert(screen->ok_action == HABIT_UI_ICON_CHART);

    press(&app, HABIT_BUTTON_RIGHT, 204);
    screen = habit_app_screen(&app, 204);
    assert(strcmp(screen->primary, "1M") == 0);
    assert(strcmp(screen->secondary, "MED TIME") == 0);

    press(&app, HABIT_BUTTON_OK, 205);
    assert(app.screen == HABIT_SCREEN_STATS);
    assert(strcmp(app.habits[app.selected].label, "MED") == 0);
}

static void test_set_ten_habits_and_validate_labels(void)
{
    habit_app_t app;
    habit_app_init(&app);

    habit_config_t habits[HABIT_APP_MAX_HABITS] = {
        {.id = 0, .label = "A0", .type = HABIT_TYPE_COUNT, .time_mode = HABIT_TIME_STOPWATCH, .default_minutes = 1},
        {.id = 1, .label = "B1", .type = HABIT_TYPE_TIME, .time_mode = HABIT_TIME_TIMER, .default_minutes = 5},
        {.id = 2, .label = "C2", .type = HABIT_TYPE_TIME, .time_mode = HABIT_TIME_STOPWATCH, .default_minutes = 1},
        {.id = 3, .label = "D3", .type = HABIT_TYPE_COUNT, .time_mode = HABIT_TIME_STOPWATCH, .default_minutes = 1},
        {.id = 4, .label = "E4", .type = HABIT_TYPE_COUNT, .time_mode = HABIT_TIME_STOPWATCH, .default_minutes = 1},
        {.id = 5, .label = "F5", .type = HABIT_TYPE_COUNT, .time_mode = HABIT_TIME_STOPWATCH, .default_minutes = 1},
        {.id = 6, .label = "G6", .type = HABIT_TYPE_COUNT, .time_mode = HABIT_TIME_STOPWATCH, .default_minutes = 1},
        {.id = 7, .label = "H7", .type = HABIT_TYPE_COUNT, .time_mode = HABIT_TIME_STOPWATCH, .default_minutes = 1},
        {.id = 8, .label = "I8", .type = HABIT_TYPE_COUNT, .time_mode = HABIT_TIME_STOPWATCH, .default_minutes = 1},
        {.id = 9, .label = "J9", .type = HABIT_TYPE_COUNT, .time_mode = HABIT_TIME_STOPWATCH, .default_minutes = 1},
    };

    assert(habit_app_set_habits(&app, habits, HABIT_APP_MAX_HABITS));
    assert(habit_app_take_habits_dirty(&app));
    assert(app.habit_count == HABIT_APP_MAX_HABITS);
    press(&app, HABIT_BUTTON_LEFT, 100);
    assert(strcmp(app.habits[app.selected].label, "J9") == 0);

    habit_config_t invalid = {.id = 10, .label = "bad", .type = HABIT_TYPE_COUNT};
    assert(!habit_app_set_habits(&app, &invalid, 1));

    habit_config_t duplicate[] = {
        {.id = 1, .label = "A", .type = HABIT_TYPE_COUNT},
        {.id = 1, .label = "B", .type = HABIT_TYPE_COUNT},
    };
    assert(!habit_app_set_habits(&app, duplicate, 2));

    assert(habit_app_load_habits(&app, habits, 3));
    assert(!habit_app_take_habits_dirty(&app));
}

static void test_timer_flow(void)
{
    habit_app_t app;
    habit_app_init(&app);

    press(&app, HABIT_BUTTON_RIGHT, 100);
    assert(strcmp(app.habits[app.selected].label, "MED") == 0);
    press(&app, HABIT_BUTTON_OK, 101);
    assert(app.screen == HABIT_SCREEN_TIMER_SETUP);
    assert(app.setup_minutes == 10);
    press(&app, HABIT_BUTTON_RIGHT, 102);
    assert(app.setup_minutes == 11);
    press(&app, HABIT_BUTTON_LEFT, 103);
    assert(app.setup_minutes == 10);
    press(&app, HABIT_BUTTON_OK, 104);
    assert(app.screen == HABIT_SCREEN_SESSION);
    press(&app, HABIT_BUTTON_OK, 110);
    assert(app.session_paused);
    press(&app, HABIT_BUTTON_OK, 115);
    assert(!app.session_paused);
    long_press(&app, HABIT_BUTTON_OK, 125);
    assert(app.log_count == 1);
    assert(app.logs[0].duration_seconds == 16);
}

static void test_timer_setup_has_back_path(void)
{
    habit_app_t app; habit_app_init(&app);
    press(&app, HABIT_BUTTON_RIGHT, 10);
    press(&app, HABIT_BUTTON_OK, 11);
    assert(app.screen == HABIT_SCREEN_TIMER_SETUP);
    long_press(&app, HABIT_BUTTON_LEFT, 12);
    assert(app.screen == HABIT_SCREEN_SELECT && !app.session_active);
}

static void test_active_session_rejects_configuration_change(void)
{
    habit_app_t app; habit_app_init(&app);
    press(&app, HABIT_BUTTON_RIGHT, 10); press(&app, HABIT_BUTTON_OK, 11); press(&app, HABIT_BUTTON_OK, 12);
    assert(app.session_active);
    habit_config_t replacement = {.id=0, .label="NEW", .type=HABIT_TYPE_COUNT, .default_minutes=1};
    assert(!habit_app_set_habits(&app, &replacement, 1));
    assert(app.session_active && strcmp(app.habits[app.selected].label, "MED") == 0);
}

static void test_timer_cancel(void)
{
    habit_app_t app;
    habit_app_init(&app);

    press(&app, HABIT_BUTTON_RIGHT, 100);
    press(&app, HABIT_BUTTON_OK, 101);
    press(&app, HABIT_BUTTON_OK, 102);
    assert(app.screen == HABIT_SCREEN_SESSION);
    long_press(&app, HABIT_BUTTON_LEFT, 110);
    assert(!app.session_active);
    assert(app.log_count == 0);
    assert(app.screen == HABIT_SCREEN_SELECT);
}

static void test_session_cancel_confirmation_and_visible_save(void)
{
    habit_app_t app;
    habit_app_init(&app);

    press(&app, HABIT_BUTTON_RIGHT, 100);
    press(&app, HABIT_BUTTON_RIGHT, 101);
    press(&app, HABIT_BUTTON_OK, 102);
    press(&app, HABIT_BUTTON_LEFT, 110);
    assert(app.screen == HABIT_SCREEN_CANCEL_CONFIRM);

    const habit_screen_t *screen = habit_app_screen(&app, 110);
    assert(strcmp(screen->header, "CANCEL STA?") == 0);
    assert(strcmp(screen->primary, "NO SAVE") == 0);
    assert(screen->left_action == HABIT_UI_ICON_BACK);
    assert(screen->right_action == HABIT_UI_ICON_CLOSE);

    press(&app, HABIT_BUTTON_OK, 111);
    assert(app.screen == HABIT_SCREEN_SESSION);
    press(&app, HABIT_BUTTON_RIGHT, 120);
    assert(app.screen == HABIT_SCREEN_CONFIRM);
    assert(app.log_count == 1);
    assert(app.logs[0].duration_seconds == 18);
}

static void test_stopwatch_cancel_and_save(void)
{
    habit_app_t app;
    habit_app_init(&app);

    press(&app, HABIT_BUTTON_RIGHT, 100);
    press(&app, HABIT_BUTTON_RIGHT, 101);
    assert(strcmp(app.habits[app.selected].label, "STA") == 0);
    press(&app, HABIT_BUTTON_OK, 102);
    assert(app.screen == HABIT_SCREEN_SESSION);
    long_press(&app, HABIT_BUTTON_LEFT, 110);
    assert(!app.session_active);
    assert(app.log_count == 0);

    press(&app, HABIT_BUTTON_OK, 120);
    long_press(&app, HABIT_BUTTON_OK, 180);
    assert(app.log_count == 1);
    assert(app.logs[0].duration_seconds == 60);
}

static void test_session_screen_shows_seconds(void)
{
    habit_app_t app;
    habit_app_init(&app);

    press(&app, HABIT_BUTTON_RIGHT, 100);
    press(&app, HABIT_BUTTON_RIGHT, 101);
    press(&app, HABIT_BUTTON_OK, 102);

    const habit_screen_t *screen = habit_app_screen(&app, 102);
    assert(strcmp(screen->primary, "0:00") == 0);
    habit_app_tick(&app, 107);
    screen = habit_app_screen(&app, 107);
    assert(strcmp(screen->primary, "0:05") == 0);
}

static void test_timer_screen_shows_countdown_seconds(void)
{
    habit_app_t app;
    habit_app_init(&app);

    press(&app, HABIT_BUTTON_RIGHT, 100);
    press(&app, HABIT_BUTTON_OK, 101);
    press(&app, HABIT_BUTTON_OK, 102);

    habit_app_tick(&app, 107);
    const habit_screen_t *screen = habit_app_screen(&app, 107);
    assert(strcmp(screen->primary, "9:55") == 0);
}

static void test_timer_finishes_and_logs_exact_duration(void)
{
    habit_app_t app;
    habit_app_init(&app);
    const habit_config_t habit = {
        .id = 7,
        .label = "TST",
        .type = HABIT_TYPE_TIME,
        .time_mode = HABIT_TIME_TIMER,
        .default_minutes = 1,
    };
    assert(habit_app_set_habits(&app, &habit, 1));

    press(&app, HABIT_BUTTON_OK, 100);
    press(&app, HABIT_BUTTON_OK, 101);
    assert(app.screen == HABIT_SCREEN_SESSION);

    const int64_t base_utc = 1704110400;
    habit_app_update_clock(&app, base_utc + 62, true);
    habit_app_tick(&app, 162);
    assert(!app.session_active);
    assert(app.screen == HABIT_SCREEN_CONFIRM);
    assert(app.timer_completed);
    assert(app.log_count == 1);
    assert(app.logs[0].duration_seconds == 60);
    assert(app.logs[0].timestamp_end == base_utc + 61);
    assert(habit_app_completion_sequence(&app) == 1);

    const habit_screen_t *screen = habit_app_screen(&app, 162);
    assert(strcmp(screen->header, "TIMER DONE") == 0);
    assert(strcmp(screen->primary, "1M") == 0);

    habit_app_tick(&app, 165);
    assert(app.screen == HABIT_SCREEN_CONFIRM);
    habit_app_tick(&app, 166);
    assert(app.screen == HABIT_SCREEN_SELECT);
}

static void test_stats(void)
{
    habit_app_t app;
    habit_app_init(&app);

    const int64_t current_week = 1704715200;
    habit_app_update_clock(&app, current_week, true);
    press(&app, HABIT_BUTTON_OK, 100);
    habit_app_tick(&app, 103);
    habit_app_update_clock(&app, current_week + 3600, true);
    press(&app, HABIT_BUTTON_OK, 104);
    assert(habit_app_stat_total(&app, 0, HABIT_STAT_WEEK_TOTAL, current_week + 7200) == 2);
    assert(habit_app_stat_total(&app, 0, HABIT_STAT_WEEK_AVG, current_week + 7200) == 2);
    assert(habit_app_stat_week_delta(&app, 0, current_week + 7200) == 2);
}

static void test_stats_navigation_and_signed_delta_screen(void)
{
    habit_app_t app;
    habit_app_init(&app);

    const int64_t previous_week = 1704110400;
    const int64_t current_week = 1704715200;
    habit_app_update_clock(&app, previous_week, true);
    press(&app, HABIT_BUTTON_OK, 100);
    habit_app_tick(&app, 103);
    habit_app_update_clock(&app, current_week, true);
    press(&app, HABIT_BUTTON_OK, 200);
    habit_app_tick(&app, 203);
    habit_app_update_clock(&app, current_week + 3600, true);
    press(&app, HABIT_BUTTON_OK, 204);
    habit_app_tick(&app, 207);
    long_press(&app, HABIT_BUTTON_OK, 208);
    assert(app.screen == HABIT_SCREEN_STATS);
    press(&app, HABIT_BUTTON_RIGHT, 209);
    assert(app.stat_view == HABIT_STAT_WEEK_DELTA);

    const habit_screen_t *screen = habit_app_screen(&app, 209);
    assert(strcmp(screen->header, "VS LAST WEEK") == 0);
    assert(strcmp(screen->secondary, "STR COUNT") == 0);
    assert(strcmp(screen->primary, "+1") == 0);

    press(&app, HABIT_BUTTON_LEFT, 210);
    assert(app.stat_view == HABIT_STAT_WEEK_TOTAL);
    press(&app, HABIT_BUTTON_OK, 211);
    assert(app.screen == HABIT_SCREEN_SELECT);
}

static void test_session_restore(void)
{
    habit_app_t app;
    habit_app_init(&app);

    press(&app, HABIT_BUTTON_RIGHT, 100);
    press(&app, HABIT_BUTTON_OK, 101);
    press(&app, HABIT_BUTTON_OK, 102);
    assert(app.session_active);

    habit_session_snapshot_t snapshot;
    assert(habit_app_export_session(&app, &snapshot));

    habit_app_t restored;
    habit_app_init(&restored);
    habit_app_restore_session(&restored, &snapshot, 120);
    assert(restored.session_active);
    assert(restored.screen == HABIT_SCREEN_SESSION);
    assert(strcmp(restored.habits[restored.selected].label, "MED") == 0);

    long_press(&restored, HABIT_BUTTON_OK, 140);
    assert(restored.log_count == 1);
    assert(restored.logs[0].duration_seconds == 38);
}

static void test_full_log_queue_never_overwrites_unsynced_data(void)
{
    habit_log_t logs[HABIT_APP_MAX_LOGS] = {0};
    for (size_t i = 0; i < HABIT_APP_MAX_LOGS; ++i) {
        logs[i] = (habit_log_t){.id = i + 1, .habit_id = 0, .type = HABIT_TYPE_COUNT, .count_value = 1};
    }
    habit_app_t app;
    habit_app_init(&app);
    habit_app_load_logs(&app, logs, HABIT_APP_MAX_LOGS);
    press(&app, HABIT_BUTTON_OK, 100);
    assert(app.log_count == HABIT_APP_MAX_LOGS);
    assert(app.logs[0].id == 1);
    assert(app.screen == HABIT_SCREEN_ERROR);

    app.screen = HABIT_SCREEN_SELECT;
    app.logs[0].synced = true;
    press(&app, HABIT_BUTTON_OK, 101);
    assert(app.log_count == HABIT_APP_MAX_LOGS);
    assert(app.logs[0].id == 2);
    assert(app.logs[HABIT_APP_MAX_LOGS - 1].id == HABIT_APP_MAX_LOGS + 1);
}

static void test_synced_rollover_preserves_calendar_history(void)
{
    const int64_t now = 1711965600;
    habit_log_t logs[HABIT_APP_MAX_LOGS] = {0};
    for (size_t i = 0; i < HABIT_APP_MAX_LOGS; ++i) {
        logs[i] = (habit_log_t){.id=i + 1, .habit_id=0, .type=HABIT_TYPE_COUNT,
            .timestamp_start=now, .timestamp_end=now, .count_value=1, .synced=true};
    }
    habit_app_t app; habit_app_init(&app); habit_app_load_logs(&app, logs, HABIT_APP_MAX_LOGS);
    habit_app_update_clock(&app, now, true); press(&app, HABIT_BUTTON_OK, 100);
    assert(app.daily_count == 1 && app.daily[0].value == 1 && habit_app_take_daily_dirty(&app));
    assert(habit_app_stat_total(&app, 0, HABIT_STAT_WEEK_TOTAL, now) == HABIT_APP_MAX_LOGS + 1);
    habit_daily_summary_t saved[HABIT_APP_MAX_DAILY_SUMMARIES];
    size_t count = habit_app_copy_daily(&app, saved, HABIT_APP_MAX_DAILY_SUMMARIES);
    habit_app_t restored; habit_app_init(&restored); habit_app_load_daily(&restored, saved, count);
    assert(restored.daily_count == 1 && restored.daily[0].value == 1 && !habit_app_take_daily_dirty(&restored));
}

int main(void)
{
    clock_service_init();
    test_day_boundary();
    test_count_and_undo();
    test_navigation_wraps_between_habits();
    test_home_modes_habits_and_logs();
    test_log_home_shows_time_logs();
    test_set_ten_habits_and_validate_labels();
    test_timer_flow();
    test_timer_setup_has_back_path();
    test_active_session_rejects_configuration_change();
    test_timer_cancel();
    test_session_cancel_confirmation_and_visible_save();
    test_stopwatch_cancel_and_save();
    test_session_screen_shows_seconds();
    test_timer_screen_shows_countdown_seconds();
    test_timer_finishes_and_logs_exact_duration();
    test_stats();
    test_stats_navigation_and_signed_delta_screen();
    test_session_restore();
    test_full_log_queue_never_overwrites_unsynced_data();
    test_synced_rollover_preserves_calendar_history();
    puts("habit_app_test: OK");
    return 0;
}
