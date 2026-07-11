#include "finish_alert.h"

void finish_alert_begin(finish_alert_t *alert, int64_t now_ms, uint32_t duration_ms, uint32_t blink_ms)
{
    if (!alert || !blink_ms) return;
    *alert = (finish_alert_t){.active=true, .visible=true, .ends_at_ms=now_ms + duration_ms,
        .next_toggle_ms=now_ms + blink_ms, .blink_ms=blink_ms};
}

finish_alert_result_t finish_alert_step(finish_alert_t *alert, int64_t now_ms, bool button_active, bool button_event)
{
    finish_alert_result_t result = {.visible=true};
    if (!alert) return result;
    result.visible = alert->visible;
    if (alert->consume_until_release) {
        result.consume_button_event = button_event;
        if (!button_active) alert->consume_until_release = false;
        return result;
    }
    if (!alert->active) return result;
    if (button_active || button_event || now_ms >= alert->ends_at_ms) {
        result.consume_button_event = button_event;
        alert->active = false; alert->consume_until_release = button_active;
        result.stopped = true;
        if (!alert->visible) { alert->visible = true; result.visibility_changed = true; }
        result.visible = true; return result;
    }
    if (now_ms >= alert->next_toggle_ms) {
        int64_t toggles = (now_ms - alert->next_toggle_ms) / alert->blink_ms + 1;
        if (toggles & 1) { alert->visible = !alert->visible; result.visibility_changed = true; }
        alert->next_toggle_ms += toggles * alert->blink_ms;
        result.visible = alert->visible;
    }
    return result;
}
