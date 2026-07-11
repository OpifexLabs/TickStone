#pragma once
#include <stdbool.h>
#include <stdint.h>

typedef struct {
    bool active;
    bool visible;
    bool consume_until_release;
    int64_t ends_at_ms;
    int64_t next_toggle_ms;
    uint32_t blink_ms;
} finish_alert_t;

typedef struct {
    bool visibility_changed;
    bool visible;
    bool stopped;
    bool consume_button_event;
} finish_alert_result_t;

void finish_alert_begin(finish_alert_t *alert, int64_t now_ms, uint32_t duration_ms, uint32_t blink_ms);
finish_alert_result_t finish_alert_step(finish_alert_t *alert, int64_t now_ms, bool button_active, bool button_event);
