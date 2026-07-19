#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define CLOCK_SERVICE_DAY_START_HOUR 5

typedef struct {
    int64_t day_id;
    int64_t week_id;
    int64_t month_id;
    int year;
    uint8_t month;
    uint8_t day;
} clock_calendar_periods_t;

void clock_service_init(void);
bool clock_service_utc_is_valid(int64_t utc_seconds);
bool clock_service_parse_utc(const char *text, int64_t *utc_seconds);
bool clock_service_now_utc(int64_t *utc_seconds);
bool clock_service_calendar_periods(int64_t utc_seconds, clock_calendar_periods_t *periods);

#ifdef __cplusplus
}
#endif
