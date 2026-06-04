#include <stdbool.h>
#include <stdint.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_log.h"
#include "esp_timer.h"

#include "app_config.h"
#include "buttons.h"
#include "habit_leds.h"
#include "max7219_matrix.h"

static const char *TAG = APP_NAME;

typedef struct {
    uint8_t selected_habit;
    uint32_t duration_seconds[HABIT_COUNT];
    uint32_t remaining_seconds;
    bool running;
    bool finished;
} app_state_t;

static void draw_remaining_time(uint32_t remaining_seconds)
{
    const uint8_t minutes = remaining_seconds / 60;
    const uint8_t seconds = remaining_seconds % 60;
    ESP_ERROR_CHECK(max7219_matrix_draw_time_mm_ss(minutes, seconds));
}

static void show_selected_habit(const app_state_t *state)
{
    if (!state->finished) {
        ESP_ERROR_CHECK(habit_leds_show_selected(state->selected_habit));
    }
}

static void select_habit(app_state_t *state, int direction)
{
    const int next = (int)state->selected_habit + direction + HABIT_COUNT;
    state->selected_habit = next % HABIT_COUNT;
    state->remaining_seconds = state->duration_seconds[state->selected_habit];
    state->running = false;
    state->finished = false;

    ESP_LOGI(TAG, "Selected habit %u", state->selected_habit + 1);
    show_selected_habit(state);
    draw_remaining_time(state->remaining_seconds);
}

static void adjust_selected_duration(app_state_t *state, int delta_seconds)
{
    int32_t duration = (int32_t)state->duration_seconds[state->selected_habit] + delta_seconds;

    if (duration < MIN_DURATION_SECONDS) {
        duration = MIN_DURATION_SECONDS;
    } else if (duration > MAX_DURATION_SECONDS) {
        duration = MAX_DURATION_SECONDS;
    }

    state->duration_seconds[state->selected_habit] = duration;
    state->remaining_seconds = duration;
    state->running = false;
    state->finished = false;

    ESP_LOGI(TAG,
             "Habit %u duration set to %ld:%02ld",
             state->selected_habit + 1,
             (long)(duration / 60),
             (long)(duration % 60));

    show_selected_habit(state);
    draw_remaining_time(state->remaining_seconds);
}

static void reset_selected_timer(app_state_t *state)
{
    state->remaining_seconds = state->duration_seconds[state->selected_habit];
    state->running = false;
    state->finished = false;

    ESP_LOGI(TAG, "Habit %u timer reset", state->selected_habit + 1);
    show_selected_habit(state);
    draw_remaining_time(state->remaining_seconds);
}

static void toggle_timer(app_state_t *state)
{
    if (state->finished || state->remaining_seconds == 0) {
        state->remaining_seconds = state->duration_seconds[state->selected_habit];
        state->finished = false;
        draw_remaining_time(state->remaining_seconds);
    }

    state->running = !state->running;
    ESP_LOGI(TAG, "Timer %s", state->running ? "started" : "paused");
    show_selected_habit(state);
}

static void handle_button_event(app_state_t *state, const button_event_t *event)
{
    if (event->type == BUTTON_EVENT_SHORT_PRESS) {
        switch (event->button) {
        case BUTTON_ID_LEFT:
            select_habit(state, -1);
            break;
        case BUTTON_ID_PLAY:
            toggle_timer(state);
            break;
        case BUTTON_ID_RIGHT:
            select_habit(state, 1);
            break;
        default:
            break;
        }

        return;
    }

    if (event->type == BUTTON_EVENT_LONG_PRESS) {
        switch (event->button) {
        case BUTTON_ID_LEFT:
            adjust_selected_duration(state, -60);
            break;
        case BUTTON_ID_PLAY:
            reset_selected_timer(state);
            break;
        case BUTTON_ID_RIGHT:
            adjust_selected_duration(state, 60);
            break;
        default:
            break;
        }
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "Habit tracker starting");

    const gpio_num_t led_pins[HABIT_COUNT] = {
        HABIT_LED_1_PIN,
        HABIT_LED_2_PIN,
        HABIT_LED_3_PIN,
    };

    const gpio_num_t button_pins[HABIT_COUNT] = {
        BUTTON_LEFT_PIN,
        BUTTON_PLAY_PIN,
        BUTTON_RIGHT_PIN,
    };

    const max7219_matrix_config_t matrix_config = {
        .host = SPI2_HOST,
        .mosi_pin = MAX7219_DIN_PIN,
        .clk_pin = MAX7219_CLK_PIN,
        .cs_pin = MAX7219_CS_PIN,
        .device_count = MAX7219_DEVICE_COUNT,
        .intensity = MAX7219_DEFAULT_INTENSITY,
    };

    ESP_ERROR_CHECK(max7219_matrix_init(&matrix_config));
    ESP_ERROR_CHECK(habit_leds_init(led_pins, HABIT_COUNT));
    ESP_ERROR_CHECK(buttons_init(button_pins,
                                 HABIT_COUNT,
                                 BUTTON_DEBOUNCE_MS,
                                 BUTTON_LONG_PRESS_MS));

    app_state_t state = {
        .selected_habit = 0,
        .duration_seconds = {
            DEFAULT_DURATION_SECONDS,
            DEFAULT_DURATION_SECONDS,
            DEFAULT_DURATION_SECONDS,
        },
        .remaining_seconds = DEFAULT_DURATION_SECONDS,
        .running = false,
        .finished = false,
    };

    ESP_LOGI(TAG, "Habit tracker started. Displaying 20:00");
    draw_remaining_time(state.remaining_seconds);
    show_selected_habit(&state);

    int64_t last_countdown_us = esp_timer_get_time();
    int64_t last_blink_us = esp_timer_get_time();
    bool blink_on = true;

    while (true) {
        button_event_t event = {0};
        if (buttons_poll(&event)) {
            handle_button_event(&state, &event);
            last_countdown_us = esp_timer_get_time();
        }

        const int64_t now_us = esp_timer_get_time();

        if (state.running && !state.finished) {
            while ((now_us - last_countdown_us) >= 1000000) {
                last_countdown_us += 1000000;

                if (state.remaining_seconds > 0) {
                    state.remaining_seconds--;
                    draw_remaining_time(state.remaining_seconds);
                }

                if (state.remaining_seconds == 0) {
                    state.running = false;
                    state.finished = true;
                    blink_on = true;
                    last_blink_us = now_us;
                    ESP_LOGI(TAG, "Habit %u timer finished", state.selected_habit + 1);
                    break;
                }
            }
        } else {
            last_countdown_us = now_us;
        }

        if (state.finished && (now_us - last_blink_us) >= (FINISHED_BLINK_MS * 1000)) {
            last_blink_us = now_us;
            blink_on = !blink_on;
            ESP_ERROR_CHECK(habit_leds_all_off());
            ESP_ERROR_CHECK(habit_leds_set(state.selected_habit, blink_on));
        }

        vTaskDelay(pdMS_TO_TICKS(MAIN_LOOP_DELAY_MS));
    }
}
