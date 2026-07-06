#include "habit_app.h"

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
    assert(habit_app_period_day(4 * 3600 + 59 * 60) == -1);
    assert(habit_app_period_day(5 * 3600) == 0);
    assert(habit_app_period_day(29 * 3600) == 1);
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

    long_press(&app, HABIT_BUTTON_OK, 101);
    assert(app.logs[0].deleted);
}

static void test_navigation_wraps_between_habits(void)
{
    habit_app_t app;
    habit_app_init(&app);

    const habit_screen_t *screen = habit_app_screen(&app, 99);
    assert(strcmp(screen->primary, "<STR>") == 0);
    assert(strcmp(screen->secondary, "+CNT") == 0);

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
    assert(strcmp(screen->primary, "HAB") == 0);
    assert(strcmp(screen->secondary, "STR+CNT") == 0);

    press(&app, HABIT_BUTTON_OK, 101);
    assert(app.habits[app.selected].type == HABIT_TYPE_TIME);
    assert(app.habits[app.selected].time_mode == HABIT_TIME_TIMER);
    screen = habit_app_screen(&app, 101);
    assert(strcmp(screen->secondary, "STR@TMR") == 0);

    size_t before_add = app.habit_count;
    long_press(&app, HABIT_BUTTON_OK, 102);
    assert(app.habit_count == before_add + 1);
    assert(strcmp(app.habits[app.selected].label, "H3") == 0);

    long_press(&app, HABIT_BUTTON_RIGHT, 103);
    assert(app.home_mode == HABIT_HOME_ACTION);

    long_press(&app, HABIT_BUTTON_RIGHT, 104);
    assert(app.home_mode == HABIT_HOME_LOGS);
    screen = habit_app_screen(&app, 104);
    assert(strcmp(screen->primary, "LOG") == 0);
    assert(strcmp(screen->secondary, "EMPTY") == 0);

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
    habit_app_tick(&app, 165);
    press(&app, HABIT_BUTTON_RIGHT, 166);
    press(&app, HABIT_BUTTON_OK, 167);
    long_press(&app, HABIT_BUTTON_OK, 197);
    habit_app_tick(&app, 200);

    long_press(&app, HABIT_BUTTON_RIGHT, 201);
    assert(app.home_mode == HABIT_HOME_LOGS);
    const habit_screen_t *screen = habit_app_screen(&app, 201);
    assert(strcmp(screen->primary, "30S") == 0);
    assert(strcmp(screen->secondary, "<STA>") == 0);

    press(&app, HABIT_BUTTON_RIGHT, 202);
    screen = habit_app_screen(&app, 202);
    assert(strcmp(screen->primary, "1M") == 0);
    assert(strcmp(screen->secondary, "<MED>") == 0);
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

static void test_stats(void)
{
    habit_app_t app;
    habit_app_init(&app);

    press(&app, HABIT_BUTTON_OK, 5 * 3600);
    press(&app, HABIT_BUTTON_OK, 6 * 3600);
    assert(habit_app_stat_total(&app, 0, HABIT_STAT_WEEK_TOTAL, 7 * 3600) == 2);
    assert(habit_app_stat_total(&app, 0, HABIT_STAT_WEEK_AVG, 7 * 3600) == 2);
    assert(habit_app_stat_week_delta(&app, 0, 7 * 3600) == 2);
}

static void test_stats_navigation_and_signed_delta_screen(void)
{
    habit_app_t app;
    habit_app_init(&app);

    press(&app, HABIT_BUTTON_OK, -7 * 24 * 3600 + 5 * 3600);
    habit_app_tick(&app, -7 * 24 * 3600 + 5 * 3600 + 3);
    press(&app, HABIT_BUTTON_OK, 5 * 3600);
    press(&app, HABIT_BUTTON_OK, 6 * 3600);
    habit_app_tick(&app, 7 * 3600);
    long_press(&app, HABIT_BUTTON_OK, 7 * 3600);
    assert(app.screen == HABIT_SCREEN_STATS);
    press(&app, HABIT_BUTTON_RIGHT, 7 * 3600 + 1);
    assert(app.stat_view == HABIT_STAT_WEEK_DELTA);

    const habit_screen_t *screen = habit_app_screen(&app, 7 * 3600 + 1);
    assert(strcmp(screen->secondary, "DIF") == 0);
    assert(strcmp(screen->primary, "+1") == 0);

    press(&app, HABIT_BUTTON_LEFT, 7 * 3600 + 2);
    assert(app.stat_view == HABIT_STAT_WEEK_TOTAL);
    press(&app, HABIT_BUTTON_OK, 7 * 3600 + 3);
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

int main(void)
{
    test_day_boundary();
    test_count_and_undo();
    test_navigation_wraps_between_habits();
    test_home_modes_habits_and_logs();
    test_log_home_shows_time_logs();
    test_set_ten_habits_and_validate_labels();
    test_timer_flow();
    test_timer_cancel();
    test_stopwatch_cancel_and_save();
    test_session_screen_shows_seconds();
    test_timer_screen_shows_countdown_seconds();
    test_stats();
    test_stats_navigation_and_signed_delta_screen();
    test_session_restore();
    puts("habit_app_test: OK");
    return 0;
}
