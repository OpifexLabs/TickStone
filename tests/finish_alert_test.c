#include "finish_alert.h"
#include <assert.h>
#include <stdio.h>

int main(void)
{
    finish_alert_t alert; finish_alert_begin(&alert, 100, 3000, 300);
    assert(alert.active && alert.visible);
    finish_alert_result_t r = finish_alert_step(&alert, 399, false, false); assert(!r.visibility_changed);
    r = finish_alert_step(&alert, 400, false, false); assert(r.visibility_changed && !r.visible);
    r = finish_alert_step(&alert, 1000, false, false); assert(!r.visibility_changed && !r.visible);
    r = finish_alert_step(&alert, 1001, true, true); assert(r.stopped && r.visible && r.consume_button_event);
    r = finish_alert_step(&alert, 1010, true, true); assert(r.consume_button_event);
    r = finish_alert_step(&alert, 1020, false, true); assert(r.consume_button_event);
    r = finish_alert_step(&alert, 1030, false, true); assert(!r.consume_button_event);
    finish_alert_begin(&alert, 0, 3000, 300);
    r = finish_alert_step(&alert, 3000, false, false); assert(r.stopped && !alert.active && r.visible);
    puts("finish_alert_test: OK");
    return 0;
}
