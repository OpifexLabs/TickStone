#include "clock_service.h"

#include <assert.h>
#include <stdio.h>

static clock_calendar_periods_t periods(int64_t utc)
{
    clock_calendar_periods_t value = {0};
    assert(clock_service_calendar_periods(utc, &value));
    return value;
}

static void test_clock_validity(void)
{
    assert(!clock_service_utc_is_valid(0));
    assert(!clock_service_utc_is_valid(1704067199));
    assert(clock_service_utc_is_valid(1704067200));
    assert(clock_service_utc_is_valid(4102444799));
    assert(!clock_service_utc_is_valid(4102444800));
    assert(!clock_service_utc_is_valid(INT64_MAX));
}

static void test_clock_text_parsing_rejects_overflow_and_bad_ranges(void)
{
    int64_t value = 0;
    assert(clock_service_parse_utc("1704067200", &value));
    assert(value == 1704067200);
    assert(!clock_service_parse_utc("1704067200junk", &value));
    assert(!clock_service_parse_utc("4102444800", &value));
    assert(!clock_service_parse_utc("999999999999999999999999", &value));
    assert(!clock_service_parse_utc("", &value));
    assert(!clock_service_parse_utc(NULL, &value));
    assert(!clock_service_parse_utc("1704067200", NULL));
}

static void test_spring_dst_day_boundary(void)
{
    clock_calendar_periods_t before = periods(1711853940); // 2024-03-31 02:59 UTC, 04:59 Stockholm
    clock_calendar_periods_t after = periods(1711854000);  // 2024-03-31 03:00 UTC, 05:00 Stockholm
    assert(after.day_id == before.day_id + 1);
}

static void test_fall_dst_day_boundary(void)
{
    clock_calendar_periods_t before = periods(1730001540); // 2024-10-27 03:59 UTC, 04:59 Stockholm
    clock_calendar_periods_t after = periods(1730001600);  // 2024-10-27 04:00 UTC, 05:00 Stockholm
    assert(after.day_id == before.day_id + 1);
}

static void test_calendar_weeks_and_months(void)
{
    clock_calendar_periods_t monday = periods(1704110400);    // 2024-01-01 12:00 UTC
    clock_calendar_periods_t sunday = periods(1704628800);    // 2024-01-07 12:00 UTC
    clock_calendar_periods_t next_monday = periods(1704715200); // 2024-01-08 12:00 UTC
    assert(monday.week_id == sunday.week_id);
    assert(next_monday.week_id == monday.week_id + 1);

    clock_calendar_periods_t february = periods(1709208000); // 2024-02-29 12:00 UTC
    clock_calendar_periods_t march = periods(1709294400);    // 2024-03-01 12:00 UTC
    assert(march.month_id == february.month_id + 1);
}

int main(void)
{
    clock_service_init();
    test_clock_validity();
    test_clock_text_parsing_rejects_overflow_and_bad_ranges();
    test_spring_dst_day_boundary();
    test_fall_dst_day_boundary();
    test_calendar_weeks_and_months();
    puts("clock_service_test: OK");
    return 0;
}
