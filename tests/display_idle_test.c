#include "display_idle.h"

#include <assert.h>
#include <stdio.h>

static void test_dim_and_off_deadlines(void)
{
    display_idle_t idle;
    display_idle_init(&idle, 1000, 5000, 10000);

    assert(display_idle_update(&idle, 5999, false, false).state == DISPLAY_IDLE_AWAKE);

    display_idle_result_t result = display_idle_update(&idle, 6000, false, false);
    assert(result.state_changed);
    assert(result.state == DISPLAY_IDLE_DIMMED);

    result = display_idle_update(&idle, 10999, false, false);
    assert(!result.state_changed);
    assert(result.state == DISPLAY_IDLE_DIMMED);

    result = display_idle_update(&idle, 11000, false, false);
    assert(result.state_changed);
    assert(result.state == DISPLAY_IDLE_OFF);
}

static void test_activity_restarts_deadline(void)
{
    display_idle_t idle;
    display_idle_init(&idle, 0, 5000, 10000);

    display_idle_update(&idle, 4000, true, false);
    display_idle_update(&idle, 4010, false, true);
    assert(display_idle_update(&idle, 9009, false, false).state == DISPLAY_IDLE_AWAKE);
    assert(display_idle_update(&idle, 9010, false, false).state == DISPLAY_IDLE_DIMMED);
}

static void test_wake_press_is_consumed_until_release(void)
{
    display_idle_t idle;
    display_idle_init(&idle, 0, 5000, 10000);
    display_idle_update(&idle, 5000, false, false);

    display_idle_result_t result = display_idle_update(&idle, 5100, true, false);
    assert(result.state_changed);
    assert(result.state == DISPLAY_IDLE_AWAKE);
    assert(!result.consume_button_event);

    result = display_idle_update(&idle, 5800, true, true);
    assert(result.consume_button_event);
    result = display_idle_update(&idle, 5810, false, true);
    assert(result.consume_button_event);

    result = display_idle_update(&idle, 6000, false, true);
    assert(!result.consume_button_event);
}

static void test_release_event_can_wake_and_is_consumed(void)
{
    display_idle_t idle;
    display_idle_init(&idle, 0, 5000, 10000);
    display_idle_update(&idle, 10000, false, false);

    display_idle_result_t result = display_idle_update(&idle, 10100, false, true);
    assert(result.state_changed);
    assert(result.state == DISPLAY_IDLE_AWAKE);
    assert(result.consume_button_event);
}

static void test_running_session_can_stay_dimmed_for_one_minute(void)
{
    display_idle_t idle;
    display_idle_init(&idle, 0, 5000, 15000);
    display_idle_set_timeouts(&idle, 5000, 65000);

    assert(display_idle_update(&idle, 5000, false, false).state == DISPLAY_IDLE_DIMMED);
    assert(display_idle_update(&idle, 64999, false, false).state == DISPLAY_IDLE_DIMMED);
    assert(display_idle_update(&idle, 65000, false, false).state == DISPLAY_IDLE_OFF);
}

int main(void)
{
    test_dim_and_off_deadlines();
    test_activity_restarts_deadline();
    test_wake_press_is_consumed_until_release();
    test_release_event_can_wake_and_is_consumed();
    test_running_session_can_stay_dimmed_for_one_minute();
    puts("display_idle_test: OK");
    return 0;
}
