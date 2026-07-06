#include <stddef.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "sdkconfig.h"

#include "esp_check.h"
#include "esp_log.h"
#include "esp_timer.h"

#include "app_config.h"
#include "buttons.h"
#include "habit_app.h"
#include "habit_storage.h"
#include "ssd1306_oled.h"

static const char *TAG = APP_NAME;

static habit_app_t s_app;

static int64_t now_seconds(void)
{
    return esp_timer_get_time() / 1000000;
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

static esp_err_t render_screen(const habit_screen_t *screen)
{
    ESP_RETURN_ON_ERROR(ssd1306_oled_clear(), TAG, "clear failed");
    ESP_RETURN_ON_ERROR(ssd1306_oled_draw_text_2x(center_x_2x(screen->primary), 6, screen->primary),
                        TAG,
                        "primary draw failed");

    if (screen->secondary[0] != '\0') {
        ESP_RETURN_ON_ERROR(ssd1306_oled_draw_text(center_x_1x(screen->secondary), 11, screen->secondary),
                            TAG,
                            "secondary draw failed");
    }

    return ESP_OK;
}

#if CONFIG_TICKSTONE_STORAGE_SELF_TEST
static void storage_self_test_press(habit_app_t *app,
                                    habit_button_t button,
                                    habit_press_t press,
                                    int64_t now_seconds)
{
    habit_app_handle_button(app, button, press, now_seconds);
}

static esp_err_t run_storage_self_test(void)
{
    static habit_app_t app;
    static habit_app_t loaded;
    static habit_app_t reloaded;

    ESP_LOGW(TAG, "TickStone storage self-test is enabled; erasing TickStone NVS namespace");
    ESP_RETURN_ON_ERROR(habit_storage_erase_all(), TAG, "erase self-test namespace failed");

    habit_app_init(&app);
    storage_self_test_press(&app, HABIT_BUTTON_LEFT, HABIT_PRESS_LONG, 5 * 3600 - 10);
    storage_self_test_press(&app, HABIT_BUTTON_OK, HABIT_PRESS_LONG, 5 * 3600 - 9);
    ESP_RETURN_ON_FALSE(habit_app_take_habits_dirty(&app), ESP_FAIL, TAG, "add habit did not mark habits dirty");
    ESP_RETURN_ON_ERROR(habit_storage_save_habits(&app), TAG, "save habits failed");

    habit_app_init(&loaded);
    ESP_RETURN_ON_ERROR(habit_storage_load(&loaded, 5 * 3600 - 8), TAG, "load habits roundtrip failed");
    ESP_RETURN_ON_FALSE(loaded.habit_count == 4, ESP_FAIL, TAG, "loaded habit count mismatch");
    ESP_RETURN_ON_FALSE(strcmp(loaded.habits[3].label, "H3") == 0, ESP_FAIL, TAG, "loaded added habit mismatch");
    ESP_RETURN_ON_ERROR(habit_storage_erase_all(), TAG, "erase after habits self-test failed");

    habit_app_init(&app);
    storage_self_test_press(&app, HABIT_BUTTON_OK, HABIT_PRESS_SHORT, 5 * 3600);
    ESP_RETURN_ON_FALSE(habit_app_take_logs_dirty(&app), ESP_FAIL, TAG, "count log did not mark logs dirty");
    ESP_RETURN_ON_ERROR(habit_storage_save_logs(&app), TAG, "save count log failed");

    habit_app_tick(&app, 5 * 3600 + 3);
    storage_self_test_press(&app, HABIT_BUTTON_RIGHT, HABIT_PRESS_SHORT, 5 * 3600 + 4);
    storage_self_test_press(&app, HABIT_BUTTON_OK, HABIT_PRESS_SHORT, 5 * 3600 + 5);
    storage_self_test_press(&app, HABIT_BUTTON_OK, HABIT_PRESS_SHORT, 5 * 3600 + 6);
    ESP_RETURN_ON_FALSE(habit_app_take_session_dirty(&app), ESP_FAIL, TAG, "start session did not mark session dirty");
    ESP_RETURN_ON_ERROR(habit_storage_save_session(&app), TAG, "save active session failed");

    habit_app_init(&loaded);
    ESP_RETURN_ON_ERROR(habit_storage_load(&loaded, 5 * 3600 + 9), TAG, "load roundtrip failed");
    ESP_RETURN_ON_FALSE(loaded.log_count == 1, ESP_FAIL, TAG, "loaded log count mismatch");
    ESP_RETURN_ON_FALSE(!loaded.logs[0].synced, ESP_FAIL, TAG, "loaded log synced flag mismatch");
    ESP_RETURN_ON_FALSE(loaded.logs[0].count_value == 1, ESP_FAIL, TAG, "loaded count value mismatch");
    ESP_RETURN_ON_FALSE(loaded.session_active, ESP_FAIL, TAG, "loaded session is not active");
    ESP_RETURN_ON_FALSE(loaded.screen == HABIT_SCREEN_SESSION, ESP_FAIL, TAG, "loaded screen is not session");
    ESP_RETURN_ON_FALSE(strcmp(loaded.habits[loaded.selected].label, "MED") == 0,
                        ESP_FAIL,
                        TAG,
                        "loaded selected habit mismatch");

    storage_self_test_press(&loaded, HABIT_BUTTON_OK, HABIT_PRESS_LONG, 5 * 3600 + 15);
    ESP_RETURN_ON_FALSE(habit_app_take_logs_dirty(&loaded), ESP_FAIL, TAG, "saved session did not dirty logs");
    ESP_RETURN_ON_FALSE(habit_app_take_session_dirty(&loaded), ESP_FAIL, TAG, "saved session did not dirty session");
    ESP_RETURN_ON_ERROR(habit_storage_save_logs(&loaded), TAG, "save session log failed");
    ESP_RETURN_ON_ERROR(habit_storage_save_session(&loaded), TAG, "clear saved session failed");

    habit_app_init(&reloaded);
    ESP_RETURN_ON_ERROR(habit_storage_load(&reloaded, 5 * 3600 + 20), TAG, "reload after save failed");
    ESP_RETURN_ON_FALSE(reloaded.log_count == 2, ESP_FAIL, TAG, "reloaded log count mismatch");
    ESP_RETURN_ON_FALSE(!reloaded.session_active, ESP_FAIL, TAG, "session key was not cleared");
    ESP_RETURN_ON_FALSE(reloaded.logs[1].type == HABIT_TYPE_TIME, ESP_FAIL, TAG, "time log type mismatch");
    ESP_RETURN_ON_FALSE(!reloaded.logs[1].synced, ESP_FAIL, TAG, "time log synced flag mismatch");
    ESP_RETURN_ON_ERROR(habit_storage_erase_all(), TAG, "final self-test cleanup failed");

    ESP_LOGI(TAG, "TickStone storage self-test PASS");
    return ESP_OK;
}
#endif

void app_main(void)
{
    ESP_LOGI(TAG, "Habit tracker starting");
    vTaskDelay(pdMS_TO_TICKS(200));

    ssd1306_oled_config_t oled_config = {0};
    ESP_ERROR_CHECK(habit_storage_init());
#if CONFIG_TICKSTONE_STORAGE_SELF_TEST
    ESP_ERROR_CHECK(run_storage_self_test());
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
#endif
    ESP_ERROR_CHECK(init_oled(&oled_config));
    ESP_ERROR_CHECK(init_buttons());

    habit_app_init(&s_app);
    ESP_ERROR_CHECK(habit_storage_load(&s_app, now_seconds()));

    habit_screen_id_t last_screen_id = HABIT_SCREEN_SELECT;
    char last_primary[sizeof(s_app.cached_screen.primary)] = {0};
    char last_secondary[sizeof(s_app.cached_screen.secondary)] = {0};

    while (true) {
        const int64_t seconds = now_seconds();
        habit_app_tick(&s_app, seconds);

        button_event_t event = {0};
        if (buttons_poll(&event)) {
            habit_button_t button = map_button(event.button);
            habit_press_t press = event.type == BUTTON_EVENT_LONG_PRESS ?
                                  HABIT_PRESS_LONG : HABIT_PRESS_SHORT;
            ESP_LOGI(TAG, "Button event button=%d press=%d", (int)button, (int)press);
            habit_app_handle_button(&s_app, button, press, seconds);
            if (habit_app_take_habits_dirty(&s_app)) {
                ESP_ERROR_CHECK(habit_storage_save_habits(&s_app));
            }
            if (habit_app_take_logs_dirty(&s_app)) {
                ESP_ERROR_CHECK(habit_storage_save_logs(&s_app));
            }
            if (habit_app_take_session_dirty(&s_app)) {
                ESP_ERROR_CHECK(habit_storage_save_session(&s_app));
            }
        }

        const habit_screen_t *screen = habit_app_screen(&s_app, seconds);
        if (screen->id != last_screen_id ||
            strcmp(screen->primary, last_primary) != 0 ||
            strcmp(screen->secondary, last_secondary) != 0) {
            ESP_ERROR_CHECK(render_screen(screen));
            last_screen_id = screen->id;
            strlcpy(last_primary, screen->primary, sizeof(last_primary));
            strlcpy(last_secondary, screen->secondary, sizeof(last_secondary));
        }

        vTaskDelay(next_loop_delay(&s_app));
    }
}
