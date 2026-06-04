#pragma once

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
} max7219_matrix_config_t;

esp_err_t max7219_matrix_init(const max7219_matrix_config_t *config);
esp_err_t max7219_matrix_clear(void);
esp_err_t max7219_matrix_set_intensity(uint8_t intensity);
esp_err_t max7219_matrix_draw_time_mm_ss(uint8_t minutes, uint8_t seconds);

#ifdef __cplusplus
}
#endif
