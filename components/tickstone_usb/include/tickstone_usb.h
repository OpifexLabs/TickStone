#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"
#include "habit_app.h"

esp_err_t tickstone_usb_start(const habit_config_t *habits, size_t count);
void tickstone_usb_update_habits(const habit_config_t *habits, size_t count);
bool tickstone_usb_take_habits(habit_config_t *habits, size_t *count);
bool tickstone_usb_take_time(int64_t *utc_seconds);
bool tickstone_usb_take_sync_request(void);
