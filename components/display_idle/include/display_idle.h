#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    DISPLAY_IDLE_AWAKE = 0,
    DISPLAY_IDLE_DIMMED,
    DISPLAY_IDLE_OFF,
} display_idle_state_t;

typedef struct {
    display_idle_state_t state;
    int64_t last_activity_ms;
    uint32_t dim_after_ms;
    uint32_t off_after_ms;
    bool consume_until_release;
} display_idle_t;

typedef struct {
    display_idle_state_t state;
    bool state_changed;
    bool consume_button_event;
} display_idle_result_t;

void display_idle_init(display_idle_t *idle,
                       int64_t now_ms,
                       uint32_t dim_after_ms,
                       uint32_t off_after_ms);

void display_idle_set_timeouts(display_idle_t *idle,
                               uint32_t dim_after_ms,
                               uint32_t off_after_ms);

display_idle_result_t display_idle_update(display_idle_t *idle,
                                          int64_t now_ms,
                                          bool button_active,
                                          bool button_event);

#ifdef __cplusplus
}
#endif
