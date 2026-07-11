#pragma once

#include <stdbool.h>
#include <stddef.h>
#include "esp_err.h"
#include "habit_app.h"

typedef struct {
    bool connected;
    bool provisioning;
    bool clock_synced;
    char address[16];
} tickstone_network_status_t;

esp_err_t tickstone_network_start(const habit_config_t *habits, size_t count);
void tickstone_network_update_habits(const habit_config_t *habits, size_t count);
bool tickstone_network_take_habits(habit_config_t *habits, size_t *count);
tickstone_network_status_t tickstone_network_status(void);
bool tickstone_network_sync_log(const habit_log_t *log);
