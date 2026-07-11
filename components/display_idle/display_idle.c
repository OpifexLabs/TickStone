#include "display_idle.h"

#include <stddef.h>

void display_idle_init(display_idle_t *idle,
                       int64_t now_ms,
                       uint32_t dim_after_ms,
                       uint32_t off_after_ms)
{
    if (idle == NULL) {
        return;
    }

    *idle = (display_idle_t) {
        .state = DISPLAY_IDLE_AWAKE,
        .last_activity_ms = now_ms,
        .dim_after_ms = dim_after_ms,
        .off_after_ms = off_after_ms,
        .consume_until_release = false,
    };
}

void display_idle_set_timeouts(display_idle_t *idle,
                               uint32_t dim_after_ms,
                               uint32_t off_after_ms)
{
    if (idle == NULL) {
        return;
    }

    idle->dim_after_ms = dim_after_ms;
    idle->off_after_ms = off_after_ms < dim_after_ms ? dim_after_ms : off_after_ms;
}

display_idle_result_t display_idle_update(display_idle_t *idle,
                                          int64_t now_ms,
                                          bool button_active,
                                          bool button_event)
{
    display_idle_result_t result = {
        .state = DISPLAY_IDLE_AWAKE,
        .state_changed = false,
        .consume_button_event = false,
    };
    if (idle == NULL) {
        return result;
    }

    result.state = idle->state;

    if (idle->state != DISPLAY_IDLE_AWAKE && (button_active || button_event)) {
        idle->state = DISPLAY_IDLE_AWAKE;
        idle->last_activity_ms = now_ms;
        idle->consume_until_release = button_active;
        result.state = idle->state;
        result.state_changed = true;
        result.consume_button_event = button_event;
        return result;
    }

    if (idle->consume_until_release) {
        idle->last_activity_ms = now_ms;
        result.consume_button_event = button_event;
        if (!button_active) {
            idle->consume_until_release = false;
        }
        return result;
    }

    if (button_active || button_event) {
        idle->last_activity_ms = now_ms;
    }

    if (button_active) {
        return result;
    }

    int64_t inactive_ms = now_ms - idle->last_activity_ms;
    if (inactive_ms < 0) {
        idle->last_activity_ms = now_ms;
        return result;
    }

    display_idle_state_t next_state = idle->state;
    if ((uint64_t)inactive_ms >= idle->off_after_ms) {
        next_state = DISPLAY_IDLE_OFF;
    } else if ((uint64_t)inactive_ms >= idle->dim_after_ms) {
        next_state = DISPLAY_IDLE_DIMMED;
    } else {
        next_state = DISPLAY_IDLE_AWAKE;
    }

    if (next_state != idle->state) {
        idle->state = next_state;
        result.state = next_state;
        result.state_changed = true;
    }
    return result;
}
