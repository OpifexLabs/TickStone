
#include "habit_app.h"

#include <stdio.h>

static void press(habit_app_t *app, habit_button_t button, int64_t now)
{
    habit_app_handle_button(app, button, HABIT_PRESS_SHORT, now);
}

static void long_press(habit_app_t *app, habit_button_t button, int64_t now)
{
    habit_app_handle_button(app, button, HABIT_PRESS_LONG, now);
}

static void show(habit_app_t *app, const char *title, int64_t now)
{
    habit_app_tick(app, now);
    const habit_screen_t *screen = habit_app_screen(app, now);
    printf("%s|%s|%s\n", title, screen->primary, screen->secondary);
}

int main(void)
{
    habit_app_t app;
    habit_app_init(&app);

    show(&app, "01_action_count", 100);
    long_press(&app, HABIT_BUTTON_LEFT, 101);
    show(&app, "02_home_habits", 101);
    press(&app, HABIT_BUTTON_OK, 102);
    show(&app, "03_habits_cycle_type", 102);
    long_press(&app, HABIT_BUTTON_RIGHT, 103);
    show(&app, "04_home_logs_empty", 103);
    press(&app, HABIT_BUTTON_OK, 104);
    show(&app, "05_back_action", 104);

    habit_app_init(&app);
    press(&app, HABIT_BUTTON_OK, 101);
    show(&app, "06_count_logged", 101);
    long_press(&app, HABIT_BUTTON_OK, 102);
    show(&app, "07_count_undo", 102);

    press(&app, HABIT_BUTTON_RIGHT, 110);
    show(&app, "08_action_timer", 110);
    press(&app, HABIT_BUTTON_OK, 111);
    show(&app, "09_timer_setup", 111);
    press(&app, HABIT_BUTTON_RIGHT, 112);
    show(&app, "10_timer_plus_minute", 112);
    press(&app, HABIT_BUTTON_OK, 113);
    show(&app, "11_timer_running_start", 113);
    show(&app, "12_timer_running_seconds", 118);
    press(&app, HABIT_BUTTON_OK, 119);
    show(&app, "13_timer_paused", 119);
    press(&app, HABIT_BUTTON_OK, 124);
    show(&app, "14_timer_resumed", 124);
    long_press(&app, HABIT_BUTTON_OK, 130);
    show(&app, "15_timer_saved", 130);
    show(&app, "16_back_to_action", 133);

    press(&app, HABIT_BUTTON_RIGHT, 140);
    show(&app, "17_action_stopwatch", 140);
    press(&app, HABIT_BUTTON_OK, 141);
    show(&app, "18_stopwatch_start", 141);
    show(&app, "19_stopwatch_seconds", 146);
    press(&app, HABIT_BUTTON_OK, 147);
    show(&app, "20_stopwatch_paused", 147);
    long_press(&app, HABIT_BUTTON_OK, 150);
    show(&app, "21_stopwatch_saved", 150);
    show(&app, "22_select_after_save", 153);

    long_press(&app, HABIT_BUTTON_RIGHT, 154);
    show(&app, "23_logs_latest", 154);
    press(&app, HABIT_BUTTON_RIGHT, 155);
    show(&app, "24_logs_previous", 155);
    press(&app, HABIT_BUTTON_OK, 156);
    show(&app, "25_logs_exit", 156);

    long_press(&app, HABIT_BUTTON_OK, 160);
    show(&app, "26_stats_week", 160);
    press(&app, HABIT_BUTTON_RIGHT, 161);
    show(&app, "27_stats_delta", 161);
    press(&app, HABIT_BUTTON_RIGHT, 162);
    show(&app, "28_stats_month", 162);
    press(&app, HABIT_BUTTON_RIGHT, 163);
    show(&app, "29_stats_average", 163);
    press(&app, HABIT_BUTTON_OK, 164);
    show(&app, "30_stats_exit", 164);

    press(&app, HABIT_BUTTON_LEFT, 170);
    press(&app, HABIT_BUTTON_OK, 171);
    press(&app, HABIT_BUTTON_OK, 172);
    show(&app, "31_timer_cancel_running", 176);
    long_press(&app, HABIT_BUTTON_LEFT, 177);
    show(&app, "32_timer_cancelled", 177);

    return 0;
}
