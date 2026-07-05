#pragma once

#include <stdint.h>

#include "driver/gpio.h"
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    gpio_num_t sda_pin;
    gpio_num_t scl_pin;
    uint8_t address;
} ssd1306_oled_config_t;

esp_err_t ssd1306_oled_init(const ssd1306_oled_config_t *config);
esp_err_t ssd1306_oled_clear(void);
esp_err_t ssd1306_oled_draw_text(uint8_t x, uint8_t page, const char *text);
esp_err_t ssd1306_oled_draw_text_2x(uint8_t x, uint8_t page, const char *text);

#ifdef __cplusplus
}
#endif
