
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
    printf("%s|%d|%d|%d|%d|%d|%d|%d|%s|%s|%s|%s\n",
           title,
           (int)screen->id,
           (int)screen->home_mode,
           (int)screen->icon,
           (int)screen->left_action,
           (int)screen->ok_action,
           (int)screen->right_action,
           screen->show_home_nav ? 1 : 0,
           screen->header,
           screen->primary,
           screen->secondary,
           screen->meta);
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
    show(&app, "04_back_action", 103);
    long_press(&app, HABIT_BUTTON_RIGHT, 104);
    show(&app, "05_home_logs_empty", 104);
    press(&app, HABIT_BUTTON_OK, 105);
    show(&app, "06_empty_logs_exit", 105);

    habit_app_init(&app);
    press(&app, HABIT_BUTTON_OK, 101);
    show(&app, "07_count_logged", 101);
    long_press(&app, HABIT_BUTTON_OK, 102);
    show(&app, "08_count_undo", 102);

    press(&app, HABIT_BUTTON_RIGHT, 110);
    show(&app, "09_action_timer", 110);
    press(&app, HABIT_BUTTON_OK, 111);
    show(&app, "10_timer_setup", 111);
    press(&app, HABIT_BUTTON_RIGHT, 112);
    show(&app, "11_timer_plus_minute", 112);
    press(&app, HABIT_BUTTON_OK, 113);
    show(&app, "12_timer_running_start", 113);
    show(&app, "13_timer_running_seconds", 118);
    press(&app, HABIT_BUTTON_OK, 119);
    show(&app, "14_timer_paused", 119);
    press(&app, HABIT_BUTTON_OK, 124);
    show(&app, "15_timer_resumed", 124);
    press(&app, HABIT_BUTTON_LEFT, 125);
    show(&app, "16_cancel_confirmation", 125);
    press(&app, HABIT_BUTTON_OK, 126);
    show(&app, "17_cancel_back", 126);
    press(&app, HABIT_BUTTON_RIGHT, 130);
    show(&app, "18_timer_saved", 130);
    show(&app, "19_back_to_action", 135);

    press(&app, HABIT_BUTTON_RIGHT, 140);
    show(&app, "20_action_stopwatch", 140);
    press(&app, HABIT_BUTTON_OK, 141);
    show(&app, "21_stopwatch_start", 141);
    show(&app, "22_stopwatch_seconds", 146);
    press(&app, HABIT_BUTTON_OK, 147);
    show(&app, "23_stopwatch_paused", 147);
    press(&app, HABIT_BUTTON_RIGHT, 150);
    show(&app, "24_stopwatch_saved", 150);
    show(&app, "25_select_after_save", 155);

    long_press(&app, HABIT_BUTTON_RIGHT, 154);
    show(&app, "26_logs_latest", 154);
    press(&app, HABIT_BUTTON_RIGHT, 155);
    show(&app, "27_logs_previous", 155);
    press(&app, HABIT_BUTTON_OK, 156);
    show(&app, "28_log_stats", 156);
    press(&app, HABIT_BUTTON_OK, 157);
    show(&app, "29_stats_exit", 157);

    long_press(&app, HABIT_BUTTON_OK, 160);
    show(&app, "30_stats_week", 160);
    press(&app, HABIT_BUTTON_RIGHT, 161);
    show(&app, "31_stats_delta", 161);
    press(&app, HABIT_BUTTON_RIGHT, 162);
    show(&app, "32_stats_month", 162);
    press(&app, HABIT_BUTTON_RIGHT, 163);
    show(&app, "33_stats_average", 163);
    press(&app, HABIT_BUTTON_OK, 164);
    show(&app, "34_stats_exit", 164);

    habit_app_init(&app);
    press(&app, HABIT_BUTTON_RIGHT, 170);
    press(&app, HABIT_BUTTON_OK, 171);
    press(&app, HABIT_BUTTON_OK, 172);
    show(&app, "35_timer_cancel_running", 176);
    press(&app, HABIT_BUTTON_LEFT, 177);
    show(&app, "36_timer_cancel_prompt", 177);
    press(&app, HABIT_BUTTON_RIGHT, 178);
    show(&app, "37_timer_cancelled", 178);

    return 0;
}
