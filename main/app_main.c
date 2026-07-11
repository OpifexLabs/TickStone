#include <stddef.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "sdkconfig.h"

#include "esp_check.h"
#include "esp_log.h"
#include "esp_pm.h"
#include "esp_timer.h"

#include "app_config.h"
#include "buttons.h"
#include "clock_service.h"
#include "display_idle.h"
#include "finish_alert.h"
#include "habit_app.h"
#include "habit_storage.h"
#include "ssd1306_oled.h"
#include "tickstone_network.h"
#include "sync_policy.h"

static const char *TAG = APP_NAME;

static habit_app_t s_app;
static sync_policy_t s_sync_policy;

static void apply_web_configuration(void)
{
    if (s_app.session_active) return;
    habit_config_t habits[HABIT_APP_MAX_HABITS];
    size_t count = 0;
    if (tickstone_network_take_habits(habits, &count) && habit_app_set_habits(&s_app, habits, count)) {
        ESP_LOGI(TAG, "Applied %u habits from web UI", (unsigned)count);
    }
}

static esp_err_t sync_one_pending_log(int64_t now_ms)
{
    if (!sync_policy_due(&s_sync_policy, now_ms)) return ESP_OK;
    for (size_t i = 0; i < s_app.log_count; ++i) {
        habit_log_t log;
        if (!habit_app_get_log(&s_app, i, &log) || log.synced) continue;
        if (tickstone_network_sync_log(&log)) {
            habit_app_mark_log_synced(&s_app, log.id);
            bool more_pending = false;
            for (size_t j = i + 1; j < s_app.log_count; ++j) {
                if (!s_app.logs[j].synced) { more_pending = true; break; }
            }
            sync_policy_succeeded(&s_sync_policy, now_ms, more_pending);
            esp_err_t err = habit_storage_save_logs(&s_app);
            if (err == ESP_OK) s_app.logs_dirty = false;
            return err;
        }
        sync_policy_failed(&s_sync_policy, now_ms);
        return ESP_OK;
    }
    sync_policy_succeeded(&s_sync_policy, now_ms, false);
    return ESP_OK;
}

static const uint8_t s_ui_icons[HABIT_UI_ICON_BACK + 1][8] = {
    [HABIT_UI_ICON_ACTION] = {0x10, 0x18, 0x1c, 0x1e, 0x1c, 0x18, 0x10, 0x00},
    [HABIT_UI_ICON_HABITS] = {0x18, 0x5a, 0x3c, 0xe7, 0xe7, 0x3c, 0x5a, 0x18},
    [HABIT_UI_ICON_LOGS] = {0x3c, 0x42, 0x91, 0xa1, 0x89, 0x42, 0x3c, 0x00},
    [HABIT_UI_ICON_COUNT] = {0x3c, 0x42, 0x5a, 0x7e, 0x7e, 0x5a, 0x42, 0x3c},
    [HABIT_UI_ICON_TIMER] = {0x7e, 0x42, 0x24, 0x18, 0x18, 0x24, 0x42, 0x7e},
    [HABIT_UI_ICON_STOPWATCH] = {0x18, 0x7e, 0x42, 0x4a, 0x4e, 0x42, 0x7e, 0x00},
    [HABIT_UI_ICON_CHECK] = {0x00, 0x01, 0x03, 0x46, 0x6c, 0x38, 0x10, 0x00},
    [HABIT_UI_ICON_EMPTY] = {0x00, 0x7e, 0x42, 0x42, 0x5a, 0x42, 0x7e, 0x00},
    [HABIT_UI_ICON_PLAY] = {0x10, 0x18, 0x1c, 0x1e, 0x1c, 0x18, 0x10, 0x00},
    [HABIT_UI_ICON_PAUSE] = {0x00, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x00},
    [HABIT_UI_ICON_CLOSE] = {0x81, 0x42, 0x24, 0x18, 0x18, 0x24, 0x42, 0x81},
    [HABIT_UI_ICON_CHART] = {0x00, 0x02, 0x22, 0x2a, 0x6a, 0x6e, 0xee, 0xfe},
    [HABIT_UI_ICON_HOME] = {0x18, 0x3c, 0x7e, 0xdb, 0x99, 0x99, 0xff, 0x00},
    [HABIT_UI_ICON_PLUS] = {0x00, 0x18, 0x18, 0x7e, 0x7e, 0x18, 0x18, 0x00},
    [HABIT_UI_ICON_MINUS] = {0x00, 0x00, 0x00, 0x7e, 0x7e, 0x00, 0x00, 0x00},
    [HABIT_UI_ICON_LEFT] = {0x08, 0x10, 0x20, 0x40, 0x40, 0x20, 0x10, 0x08},
    [HABIT_UI_ICON_RIGHT] = {0x10, 0x08, 0x04, 0x02, 0x02, 0x04, 0x08, 0x10},
    [HABIT_UI_ICON_EDIT] = {0x03, 0x07, 0x0e, 0x1c, 0x38, 0x70, 0xe0, 0xc0},
    [HABIT_UI_ICON_UNDO] = {0x10, 0x30, 0x7e, 0xff, 0x18, 0x0c, 0x7c, 0x38},
    [HABIT_UI_ICON_BACK] = {0x10, 0x30, 0x7f, 0xff, 0x30, 0x10, 0x00, 0x00},
};

static int64_t now_seconds(void)
{
    return esp_timer_get_time() / 1000000;
}

static int64_t now_milliseconds(void)
{
    return esp_timer_get_time() / 1000;
}

static esp_err_t init_oled(ssd1306_oled_config_t *active_config)
{
    const ssd1306_oled_config_t config = {
        .sda_pin = OLED_SDA_PIN,
        .scl_pin = OLED_SCL_PIN,
        .address = OLED_I2C_ADDRESS,
    };

    ESP_LOGI(TAG, "Trying OLED on SDA GPIO%ld / SCL GPIO%ld", (long)config.sda_pin, (long)config.scl_pin);
    ESP_RETURN_ON_ERROR(ssd1306_oled_init(&config), TAG, "OLED init failed");
    *active_config = config;
    return ESP_OK;
}

static esp_err_t init_buttons(void)
{
    static const gpio_num_t pins[] = {
        BUTTON_LEFT_PIN,
        BUTTON_PLAY_PIN,
        BUTTON_RIGHT_PIN,
    };

    return buttons_init(pins,
                        sizeof(pins) / sizeof(pins[0]),
                        BUTTON_DEBOUNCE_MS,
                        BUTTON_LONG_PRESS_MS);
}

static habit_button_t map_button(button_id_t button)
{
    switch (button) {
    case BUTTON_ID_LEFT:
        return HABIT_BUTTON_LEFT;
    case BUTTON_ID_PLAY:
        return HABIT_BUTTON_OK;
    case BUTTON_ID_RIGHT:
        return HABIT_BUTTON_RIGHT;
    default:
        return HABIT_BUTTON_OK;
    }
}

static TickType_t next_loop_delay(const habit_app_t *app)
{
    if (buttons_active()) {
        return pdMS_TO_TICKS(BUTTON_ACTIVE_LOOP_DELAY_MS);
    }

    if (app->screen == HABIT_SCREEN_SESSION) {
        return pdMS_TO_TICKS(SESSION_LOOP_DELAY_MS);
    }

    return pdMS_TO_TICKS(IDLE_LOOP_DELAY_MS);
}

static uint8_t center_x_2x(const char *text)
{
    const size_t len = strlen(text);
    const size_t width = len * 12;
    return width >= 128 ? 0 : (uint8_t)((128 - width) / 2);
}

static uint8_t center_x_1x(const char *text)
{
    const size_t len = strlen(text);
    const size_t width = len * 6;
    return width >= 128 ? 0 : (uint8_t)((128 - width) / 2);
}

static esp_err_t draw_icon(uint8_t x, uint8_t page, habit_ui_icon_t icon)
{
    if (icon == HABIT_UI_ICON_NONE || icon > HABIT_UI_ICON_BACK) {
        return ESP_OK;
    }
    return ssd1306_oled_draw_bitmap_8x8_2x(x, page, s_ui_icons[icon]);
}

static habit_ui_icon_t header_icon(const habit_screen_t *screen)
{
    if (!screen->show_home_nav) {
        return screen->icon;
    }

    if (screen->home_mode == HABIT_HOME_HABITS) {
        return HABIT_UI_ICON_HABITS;
    }
    if (screen->home_mode == HABIT_HOME_LOGS) {
        return HABIT_UI_ICON_LOGS;
    }
    return HABIT_UI_ICON_ACTION;
}

static esp_err_t render_header(const habit_screen_t *screen)
{
    const habit_ui_icon_t icon = header_icon(screen);
    const size_t text_width = strlen(screen->header) * 6;
    const size_t icon_width = icon == HABIT_UI_ICON_NONE ? 0 : 12;
    const size_t total_width = icon_width + text_width;
    uint8_t x = total_width >= 128 ? 0 : (uint8_t)((128 - total_width) / 2);

    if (icon != HABIT_UI_ICON_NONE) {
        ESP_RETURN_ON_ERROR(ssd1306_oled_draw_bitmap_8x8(x, 1, s_ui_icons[icon]),
                            TAG,
                            "header icon failed");
        x += 12;
    }
    if (screen->header[0] != '\0') {
        ESP_RETURN_ON_ERROR(ssd1306_oled_draw_text(x, 1, screen->header),
                            TAG,
                            "header text failed");
    }
    return ESP_OK;
}

static esp_err_t render_screen(const habit_screen_t *screen)
{
    ESP_RETURN_ON_ERROR(ssd1306_oled_clear(), TAG, "clear failed");
    ESP_RETURN_ON_ERROR(render_header(screen), TAG, "header draw failed");
    ESP_RETURN_ON_ERROR(ssd1306_oled_draw_text_2x(center_x_2x(screen->primary), 5, screen->primary),
                        TAG,
                        "primary draw failed");

    if (screen->secondary[0] != '\0') {
        ESP_RETURN_ON_ERROR(ssd1306_oled_draw_text(center_x_1x(screen->secondary), 8, screen->secondary),
                            TAG,
                            "secondary draw failed");
    }

    ESP_RETURN_ON_ERROR(draw_icon(12, 12, screen->left_action), TAG, "left action failed");
    ESP_RETURN_ON_ERROR(draw_icon(56, 12, screen->ok_action), TAG, "ok action failed");
    ESP_RETURN_ON_ERROR(draw_icon(100, 12, screen->right_action), TAG, "right action failed");
    return ssd1306_oled_present();
}

static esp_err_t apply_display_idle_state(display_idle_state_t state)
{
    switch (state) {
    case DISPLAY_IDLE_AWAKE:
        ESP_RETURN_ON_ERROR(ssd1306_oled_set_contrast(OLED_FULL_CONTRAST),
                            TAG,
                            "restore OLED contrast failed");
        return ssd1306_oled_set_enabled(true);
    case DISPLAY_IDLE_DIMMED:
        return ssd1306_oled_set_contrast(OLED_DIM_CONTRAST);
    case DISPLAY_IDLE_OFF:
        return ssd1306_oled_set_enabled(false);
    default:
        return ESP_ERR_INVALID_ARG;
    }
}

static esp_err_t persist_app_state(void)
{
    if (s_app.habits_dirty) {
        ESP_RETURN_ON_ERROR(habit_storage_save_habits(&s_app), TAG, "save habits failed");
        s_app.habits_dirty = false;
        habit_config_t habits[HABIT_APP_MAX_HABITS];
        size_t count = habit_app_copy_habits(&s_app, habits, HABIT_APP_MAX_HABITS);
        tickstone_network_update_habits(habits, count);
    }
    if (s_app.daily_dirty) {
        ESP_RETURN_ON_ERROR(habit_storage_save_daily(&s_app), TAG, "save daily summaries failed");
        s_app.daily_dirty = false;
    }
    if (s_app.logs_dirty) {
        ESP_RETURN_ON_ERROR(habit_storage_save_logs(&s_app), TAG, "save logs failed");
        s_app.logs_dirty = false;
        sync_policy_request_now(&s_sync_policy, now_milliseconds());
    }
    if (s_app.session_dirty) {
        ESP_RETURN_ON_ERROR(habit_storage_save_session(&s_app), TAG, "save session failed");
        s_app.session_dirty = false;
    }
    return ESP_OK;
}

static esp_err_t finish_alert_start(finish_alert_t *alert,
                                    display_idle_t *display_idle,
                                    int64_t now_ms)
{
    finish_alert_begin(alert, now_ms, FINISHED_ALERT_MS, FINISHED_BLINK_MS);
    display_idle_init(display_idle, now_ms, OLED_DIM_AFTER_MS, OLED_OFF_AFTER_MS);
    ESP_RETURN_ON_ERROR(ssd1306_oled_set_contrast(OLED_FULL_CONTRAST),
                        TAG,
                        "finish alert contrast failed");
    ESP_RETURN_ON_ERROR(ssd1306_oled_set_enabled(true), TAG, "finish alert wake failed");
    ESP_LOGI(TAG, "Time session finished; starting display alert");
    return ESP_OK;
}

static esp_err_t finish_alert_update(finish_alert_t *alert,
                                     display_idle_t *display_idle,
                                     int64_t now_ms,
                                     bool button_active,
                                     bool button_event,
                                     bool *consume_button_event)
{
    finish_alert_result_t result = finish_alert_step(alert, now_ms, button_active, button_event);
    *consume_button_event = result.consume_button_event;
    if (result.visibility_changed) {
        ESP_RETURN_ON_ERROR(ssd1306_oled_set_enabled(result.visible), TAG, "finish alert blink failed");
    }
    if (result.stopped) {
        display_idle_init(display_idle, now_ms, OLED_DIM_AFTER_MS, OLED_OFF_AFTER_MS);
        ESP_RETURN_ON_ERROR(ssd1306_oled_set_contrast(OLED_FULL_CONTRAST), TAG, "finish alert restore contrast failed");
        ESP_RETURN_ON_ERROR(ssd1306_oled_set_enabled(true), TAG, "finish alert restore display failed");
    }
    return ESP_OK;
}

void app_main(void)
{
    ESP_LOGI(TAG, "Habit tracker starting");
    sync_policy_init(&s_sync_policy);
    const esp_pm_config_t power = {
        .max_freq_mhz = 160,
        .min_freq_mhz = 40,
        .light_sleep_enable = false,
    };
    ESP_ERROR_CHECK(esp_pm_configure(&power));
    vTaskDelay(pdMS_TO_TICKS(200));

    ssd1306_oled_config_t oled_config = {0};
    ESP_ERROR_CHECK(habit_storage_init());
    ESP_ERROR_CHECK(init_oled(&oled_config));
    ESP_ERROR_CHECK(init_buttons());

    clock_service_init();
    habit_app_init(&s_app);
    int64_t initial_utc = 0;
    bool initial_clock_synced = clock_service_now_utc(&initial_utc);
    habit_app_update_clock(&s_app, initial_utc, initial_clock_synced);
    ESP_ERROR_CHECK(habit_storage_load(&s_app, now_seconds()));
    habit_config_t network_habits[HABIT_APP_MAX_HABITS];
    size_t network_habit_count = habit_app_copy_habits(&s_app, network_habits, HABIT_APP_MAX_HABITS);
    ESP_ERROR_CHECK(tickstone_network_start(network_habits, network_habit_count));

    habit_screen_t last_screen = {0};
    bool has_last_screen = false;
    display_idle_t display_idle;
    display_idle_init(&display_idle,
                      now_milliseconds(),
                      OLED_DIM_AFTER_MS,
                      OLED_OFF_AFTER_MS);
    finish_alert_t finish_alert = {0};
    uint32_t seen_completion_sequence = habit_app_completion_sequence(&s_app);

    while (true) {
        apply_web_configuration();
        const int64_t seconds = now_seconds();
        const int64_t milliseconds = now_milliseconds();
        int64_t utc_seconds = 0;
        bool clock_synced = clock_service_now_utc(&utc_seconds);
        habit_app_update_clock(&s_app, utc_seconds, clock_synced);
        habit_app_tick(&s_app, seconds);

        uint32_t completion_sequence = habit_app_completion_sequence(&s_app);
        if (completion_sequence != seen_completion_sequence) {
            ESP_ERROR_CHECK(finish_alert_start(&finish_alert, &display_idle, milliseconds));
            seen_completion_sequence = completion_sequence;
        }

        button_event_t event = {0};
        const bool has_button_event = buttons_poll(&event);
        const bool button_active = buttons_active();
        bool consume_button_event = false;

        if (finish_alert.active || finish_alert.consume_until_release) {
            ESP_ERROR_CHECK(finish_alert_update(&finish_alert,
                                                &display_idle,
                                                milliseconds,
                                                button_active,
                                                has_button_event,
                                                &consume_button_event));
        } else {
            const bool session_running = s_app.screen == HABIT_SCREEN_SESSION &&
                                         s_app.session_active &&
                                         !s_app.session_paused;
            display_idle_set_timeouts(&display_idle,
                                      OLED_DIM_AFTER_MS,
                                      session_running ? OLED_RUNNING_OFF_AFTER_MS : OLED_OFF_AFTER_MS);
            const display_idle_result_t idle_result = display_idle_update(&display_idle,
                                                                          milliseconds,
                                                                          button_active,
                                                                          has_button_event);
            consume_button_event = idle_result.consume_button_event;
            if (idle_result.state_changed) {
                ESP_LOGI(TAG, "Display idle state=%d", (int)idle_result.state);
                ESP_ERROR_CHECK(apply_display_idle_state(idle_result.state));
            }
        }

        if (has_button_event && !consume_button_event) {
            habit_button_t button = map_button(event.button);
            habit_press_t press = event.type == BUTTON_EVENT_LONG_PRESS ?
                                  HABIT_PRESS_LONG : HABIT_PRESS_SHORT;
            ESP_LOGI(TAG, "Button event button=%d press=%d", (int)button, (int)press);
            habit_app_handle_button(&s_app, button, press, seconds);
        }

        completion_sequence = habit_app_completion_sequence(&s_app);
        if (completion_sequence != seen_completion_sequence) {
            ESP_ERROR_CHECK(finish_alert_start(&finish_alert, &display_idle, milliseconds));
            seen_completion_sequence = completion_sequence;
        }
        ESP_ERROR_CHECK(persist_app_state());
        ESP_ERROR_CHECK(sync_one_pending_log(milliseconds));

        const habit_screen_t *screen = habit_app_screen(&s_app, seconds);
        if (display_idle.state != DISPLAY_IDLE_OFF &&
            (!has_last_screen || memcmp(screen, &last_screen, sizeof(*screen)) != 0)) {
            ESP_ERROR_CHECK(render_screen(screen));
            last_screen = *screen;
            has_last_screen = true;
        }

        buttons_wait(finish_alert.active ? pdMS_TO_TICKS(50) : next_loop_delay(&s_app));
    }
}
