#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "driver/gpio.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    BUTTON_ID_LEFT = 0,
    BUTTON_ID_PLAY,
    BUTTON_ID_RIGHT,
} button_id_t;

typedef enum {
    BUTTON_EVENT_NONE = 0,
    BUTTON_EVENT_SHORT_PRESS,
    BUTTON_EVENT_LONG_PRESS,
} button_event_type_t;

typedef struct {
    button_id_t button;
    button_event_type_t type;
} button_event_t;

esp_err_t buttons_init(const gpio_num_t *pins,
                       size_t button_count,
                       uint32_t debounce_ms,
                       uint32_t long_press_ms);

bool buttons_poll(button_event_t *event);
bool buttons_active(void);
void buttons_wait(TickType_t timeout);

#ifdef __cplusplus
}
#endif
