#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "driver/gpio.h"
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t habit_leds_init(const gpio_num_t *pins, size_t led_count);
esp_err_t habit_leds_all_off(void);
esp_err_t habit_leds_set(uint8_t habit_index, bool on);
esp_err_t habit_leds_show_selected(uint8_t habit_index);

#ifdef __cplusplus
}
#endif
