#pragma once

#include <stdbool.h>
#include <stddef.h>
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
esp_err_t ssd1306_oled_set_contrast(uint8_t contrast);
esp_err_t ssd1306_oled_set_enabled(bool enabled);
esp_err_t ssd1306_oled_clear(void);
esp_err_t ssd1306_oled_present(void);
esp_err_t ssd1306_oled_draw_text(uint8_t x, uint8_t page, const char *text);
esp_err_t ssd1306_oled_draw_text_2x(uint8_t x, uint8_t page, const char *text);
esp_err_t ssd1306_oled_draw_bitmap_8x8(uint8_t x, uint8_t page, const uint8_t rows[8]);
esp_err_t ssd1306_oled_draw_bitmap_8x8_2x(uint8_t x, uint8_t page, const uint8_t rows[8]);

#ifdef __cplusplus
}
#endif
