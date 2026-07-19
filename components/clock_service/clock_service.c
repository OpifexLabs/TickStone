#define _POSIX_C_SOURCE 200809L

#include "clock_service.h"

#include <errno.h>
#include <stddef.h>
#include <stdlib.h>
#include <time.h>

#define CLOCK_VALID_FROM_UTC 1704067200LL
#define CLOCK_VALID_UNTIL_UTC 4102444800LL
#define STOCKHOLM_TZ "CET-1CEST,M3.5.0/2,M10.5.0/3"

static int64_t floor_div_i64(int64_t value, int64_t divisor)
{
    int64_t quotient = value / divisor;
    int64_t remainder = value % divisor;
    if (remainder != 0 && ((remainder < 0) != (divisor < 0))) {
        quotient--;
    }
    return quotient;
}

static int64_t days_from_civil(int year, unsigned month, unsigned day)
{
    year -= month <= 2;
    const int era = (year >= 0 ? year : year - 399) / 400;
    const unsigned year_of_era = (unsigned)(year - era * 400);
    const unsigned shifted_month = month > 2 ? month - 3 : month + 9;
    const unsigned day_of_year = (153 * shifted_month + 2) / 5 + day - 1;
    const unsigned day_of_era = year_of_era * 365 + year_of_era / 4 -
                                year_of_era / 100 + day_of_year;
    return (int64_t)era * 146097 + (int64_t)day_of_era - 719468;
}

void clock_service_init(void)
{
    setenv("TZ", STOCKHOLM_TZ, 1);
    tzset();
}

bool clock_service_utc_is_valid(int64_t utc_seconds)
{
    return utc_seconds >= CLOCK_VALID_FROM_UTC && utc_seconds < CLOCK_VALID_UNTIL_UTC;
}

bool clock_service_parse_utc(const char *text, int64_t *utc_seconds)
{
    if (text == NULL || utc_seconds == NULL || *text == '\0') return false;
    errno = 0;
    char *end = NULL;
    const long long parsed = strtoll(text, &end, 10);
    if (errno == ERANGE || end == text || *end != '\0' ||
        !clock_service_utc_is_valid((int64_t)parsed)) {
        return false;
    }
    *utc_seconds = (int64_t)parsed;
    return true;
}

bool clock_service_now_utc(int64_t *utc_seconds)
{
    if (utc_seconds == NULL) {
        return false;
    }

    const time_t now = time(NULL);
    *utc_seconds = (int64_t)now;
    return clock_service_utc_is_valid(*utc_seconds);
}

bool clock_service_calendar_periods(int64_t utc_seconds, clock_calendar_periods_t *periods)
{
    if (periods == NULL || !clock_service_utc_is_valid(utc_seconds)) {
        return false;
    }

    const time_t timestamp = (time_t)utc_seconds;
    struct tm local = {0};
    if (localtime_r(&timestamp, &local) == NULL) {
        return false;
    }

    int64_t day_id = days_from_civil(local.tm_year + 1900,
                                     (unsigned)local.tm_mon + 1,
                                     (unsigned)local.tm_mday);
    if (local.tm_hour < CLOCK_SERVICE_DAY_START_HOUR) {
        day_id--;
    }

    periods->day_id = day_id;
    periods->week_id = floor_div_i64(day_id + 3, 7);
    periods->month_id = (int64_t)(local.tm_year + 1900) * 12 + local.tm_mon;
    periods->year = local.tm_year + 1900;
    periods->month = (uint8_t)local.tm_mon + 1;
    periods->day = (uint8_t)local.tm_mday;
    return true;
}
