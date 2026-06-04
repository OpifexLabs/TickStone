#include "habit_leds.h"

#include <stdbool.h>
#include <string.h>

#define HABIT_LEDS_MAX_COUNT 10

static gpio_num_t s_led_pins[HABIT_LEDS_MAX_COUNT];
static size_t s_led_count;

esp_err_t habit_leds_init(const gpio_num_t *pins, size_t led_count)
{
    if (pins == NULL || led_count == 0 || led_count > HABIT_LEDS_MAX_COUNT) {
        return ESP_ERR_INVALID_ARG;
    }

    memset(s_led_pins, 0, sizeof(s_led_pins));
    s_led_count = led_count;

    gpio_config_t io_conf = {
        .pin_bit_mask = 0,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };

    for (size_t i = 0; i < led_count; ++i) {
        s_led_pins[i] = pins[i];
        io_conf.pin_bit_mask |= (1ULL << pins[i]);
    }

    esp_err_t err = gpio_config(&io_conf);
    if (err != ESP_OK) {
        return err;
    }

    return habit_leds_all_off();
}

esp_err_t habit_leds_all_off(void)
{
    for (size_t i = 0; i < s_led_count; ++i) {
        esp_err_t err = gpio_set_level(s_led_pins[i], 0);
        if (err != ESP_OK) {
            return err;
        }
    }

    return ESP_OK;
}

esp_err_t habit_leds_set(uint8_t habit_index, bool on)
{
    if (habit_index >= s_led_count) {
        return ESP_ERR_INVALID_ARG;
    }

    return gpio_set_level(s_led_pins[habit_index], on ? 1 : 0);
}

esp_err_t habit_leds_show_selected(uint8_t habit_index)
{
    if (habit_index >= s_led_count) {
        return ESP_ERR_INVALID_ARG;
    }

    for (size_t i = 0; i < s_led_count; ++i) {
        esp_err_t err = gpio_set_level(s_led_pins[i], i == habit_index ? 1 : 0);
        if (err != ESP_OK) {
            return err;
        }
    }

    return ESP_OK;
}
