#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    spi_host_device_t host;
    gpio_num_t mosi_pin;
    gpio_num_t clk_pin;
    gpio_num_t cs_pin;
    uint8_t device_count;
    uint8_t intensity;
    enum {
        MAX7219_MATRIX_ROTATION_0 = 0,
        MAX7219_MATRIX_ROTATION_RIGHT_90,
        MAX7219_MATRIX_ROTATION_180,
        MAX7219_MATRIX_ROTATION_LEFT_90,
    } rotation;
} max7219_matrix_config_t;

esp_err_t max7219_matrix_init(const max7219_matrix_config_t *config);
esp_err_t max7219_matrix_clear(void);
esp_err_t max7219_matrix_set_intensity(uint8_t intensity);
esp_err_t max7219_matrix_set_display_test(bool enabled);
esp_err_t max7219_matrix_fill(bool on);
esp_err_t max7219_matrix_draw_time_mm_ss(uint8_t minutes, uint8_t seconds);
esp_err_t max7219_matrix_draw_7seg_2_digit(uint8_t value, bool leading_zero);
esp_err_t max7219_matrix_draw_7seg_2_digit_clock(uint8_t value, bool leading_zero, bool dots_on);

#ifdef __cplusplus
}
#endif
