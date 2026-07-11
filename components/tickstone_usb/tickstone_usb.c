#include "tickstone_usb.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "habit_web_config.h"

#define USB_LINE_SIZE 1024

static SemaphoreHandle_t s_lock;
static habit_config_t s_habits[HABIT_APP_MAX_HABITS];
static size_t s_count;
static bool s_habits_pending;
static bool s_time_pending;
static bool s_sync_pending;
static int64_t s_utc_seconds;

static void write_config(void)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    printf("@TS1 BEGIN %u\n", (unsigned)s_count);
    for (size_t i = 0; i < s_count; ++i) {
        const habit_config_t *h = &s_habits[i];
        printf("@TS1 HABIT %u %s %u %u %s\n",
               h->id,
               h->label,
               h->type == HABIT_TYPE_COUNT ? 0u : 1u,
               h->default_minutes,
               h->name);
    }
    printf("@TS1 END\n");
    fflush(stdout);
    xSemaphoreGive(s_lock);
}

static void handle_line(char *line)
{
    line[strcspn(line, "\r\n")] = 0;
    if (strcmp(line, "TS1 GET") == 0) {
        write_config();
        return;
    }
    if (strcmp(line, "TS1 SYNC") == 0) {
        xSemaphoreTake(s_lock, portMAX_DELAY);
        s_sync_pending = true;
        xSemaphoreGive(s_lock);
        printf("@TS1 OK SYNC\n");
        fflush(stdout);
        return;
    }
    if (strncmp(line, "TS1 TIME ", 9) == 0) {
        char *end = NULL;
        long long value = strtoll(line + 9, &end, 10);
        if (end && *end == 0 && value >= 1704067200LL) {
            xSemaphoreTake(s_lock, portMAX_DELAY);
            s_utc_seconds = (int64_t)value;
            s_time_pending = true;
            xSemaphoreGive(s_lock);
            printf("@TS1 OK TIME\n");
        } else {
            printf("@TS1 ERROR TIME\n");
        }
        fflush(stdout);
        return;
    }
    if (strncmp(line, "TS1 SET ", 8) == 0) {
        habit_web_config_t parsed;
        if (!habit_web_config_parse(line + 8, &parsed)) {
            printf("@TS1 ERROR CONFIG\n");
            fflush(stdout);
            return;
        }
        xSemaphoreTake(s_lock, portMAX_DELAY);
        memcpy(s_habits, parsed.habits, parsed.habit_count * sizeof(*s_habits));
        s_count = parsed.habit_count;
        s_habits_pending = true;
        xSemaphoreGive(s_lock);
        printf("@TS1 OK CONFIG\n");
        fflush(stdout);
    }
}

static void usb_task(void *argument)
{
    char line[USB_LINE_SIZE];
    size_t used = 0;
    uint8_t chunk[64];
    while (true) {
        ssize_t count = read(STDIN_FILENO, chunk, sizeof(chunk));
        if (count <= 0) {
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }
        for (ssize_t i = 0; i < count; ++i) {
            const char c = (char)chunk[i];
            if (c == '\r') continue;
            if (c == '\n') {
                line[used] = 0;
                if (used > 0) handle_line(line);
                used = 0;
            } else if (used + 1 < sizeof(line)) {
                line[used++] = c;
            } else {
                used = 0;
                printf("@TS1 ERROR LINE_TOO_LONG\n");
                fflush(stdout);
            }
        }
    }
}

esp_err_t tickstone_usb_start(const habit_config_t *habits, size_t count)
{
    if (!habits || count == 0 || count > HABIT_APP_MAX_HABITS) return ESP_ERR_INVALID_ARG;
    s_lock = xSemaphoreCreateMutex();
    if (!s_lock) return ESP_ERR_NO_MEM;
    tickstone_usb_update_habits(habits, count);
    if (xTaskCreate(usb_task, "usb_config", 6144, NULL, 5, NULL) != pdPASS) return ESP_ERR_NO_MEM;
    return ESP_OK;
}

void tickstone_usb_update_habits(const habit_config_t *habits, size_t count)
{
    if (!s_lock || !habits || count == 0 || count > HABIT_APP_MAX_HABITS) return;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    memcpy(s_habits, habits, count * sizeof(*habits));
    s_count = count;
    xSemaphoreGive(s_lock);
}

bool tickstone_usb_take_habits(habit_config_t *habits, size_t *count)
{
    if (!s_lock || !habits || !count) return false;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    const bool pending = s_habits_pending;
    if (pending) {
        memcpy(habits, s_habits, s_count * sizeof(*habits));
        *count = s_count;
        s_habits_pending = false;
    }
    xSemaphoreGive(s_lock);
    return pending;
}

bool tickstone_usb_take_time(int64_t *utc_seconds)
{
    if (!s_lock || !utc_seconds) return false;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    const bool pending = s_time_pending;
    if (pending) {
        *utc_seconds = s_utc_seconds;
        s_time_pending = false;
    }
    xSemaphoreGive(s_lock);
    return pending;
}

bool tickstone_usb_take_sync_request(void)
{
    if (!s_lock) return false;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    const bool pending = s_sync_pending;
    s_sync_pending = false;
    xSemaphoreGive(s_lock);
    return pending;
}
