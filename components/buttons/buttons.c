#include "buttons.h"

#include <string.h>

#include "esp_timer.h"

#define BUTTONS_MAX_COUNT 8

typedef struct {
    gpio_num_t pin;
    bool stable_pressed;
    bool last_raw_pressed;
    bool long_reported;
    int64_t last_raw_change_ms;
    int64_t pressed_since_ms;
} button_state_t;

static button_state_t s_buttons[BUTTONS_MAX_COUNT];
static size_t s_button_count;
static uint32_t s_debounce_ms;
static uint32_t s_long_press_ms;

static int64_t now_ms(void)
{
    return esp_timer_get_time() / 1000;
}

esp_err_t buttons_init(const gpio_num_t *pins,
                       size_t button_count,
                       uint32_t debounce_ms,
                       uint32_t long_press_ms)
{
    if (pins == NULL || button_count == 0 || button_count > BUTTONS_MAX_COUNT) {
        return ESP_ERR_INVALID_ARG;
    }

    memset(s_buttons, 0, sizeof(s_buttons));
    s_button_count = button_count;
    s_debounce_ms = debounce_ms;
    s_long_press_ms = long_press_ms;

    gpio_config_t io_conf = {
        .pin_bit_mask = 0,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };

    for (size_t i = 0; i < button_count; ++i) {
        io_conf.pin_bit_mask |= (1ULL << pins[i]);
        s_buttons[i].pin = pins[i];
        s_buttons[i].stable_pressed = false;
        s_buttons[i].last_raw_pressed = false;
        s_buttons[i].last_raw_change_ms = now_ms();
    }

    return gpio_config(&io_conf);
}

bool buttons_poll(button_event_t *event)
{
    if (event == NULL) {
        return false;
    }

    event->type = BUTTON_EVENT_NONE;
    const int64_t current_ms = now_ms();

    for (size_t i = 0; i < s_button_count; ++i) {
        button_state_t *button = &s_buttons[i];
        const bool raw_pressed = gpio_get_level(button->pin) == 0;

        if (raw_pressed != button->last_raw_pressed) {
            button->last_raw_pressed = raw_pressed;
            button->last_raw_change_ms = current_ms;
        }

        if ((current_ms - button->last_raw_change_ms) >= s_debounce_ms &&
            raw_pressed != button->stable_pressed) {
            button->stable_pressed = raw_pressed;

            if (button->stable_pressed) {
                button->pressed_since_ms = current_ms;
                button->long_reported = false;
            } else if (!button->long_reported) {
                event->button = (button_id_t)i;
                event->type = BUTTON_EVENT_SHORT_PRESS;
                return true;
            }
        }

        if (button->stable_pressed &&
            !button->long_reported &&
            (current_ms - button->pressed_since_ms) >= s_long_press_ms) {
            button->long_reported = true;
            event->button = (button_id_t)i;
            event->type = BUTTON_EVENT_LONG_PRESS;
            return true;
        }
    }

    return false;
}
