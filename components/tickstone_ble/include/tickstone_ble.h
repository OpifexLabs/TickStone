#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"
#include "habit_app.h"

#define TICKSTONE_BLE_SERVICE_UUID "7e570000-7a1b-4c2d-9e10-000000000001"
#define TICKSTONE_BLE_DATA_UUID    "7e570000-7a1b-4c2d-9e10-000000000002"
#define TICKSTONE_BLE_CONTROL_UUID "7e570000-7a1b-4c2d-9e10-000000000003"
#define TICKSTONE_BLE_CONFIG_UUID  "7e570000-7a1b-4c2d-9e10-000000000004"

esp_err_t tickstone_ble_init(void);
esp_err_t tickstone_ble_request_sync(int64_t now_ms);
esp_err_t tickstone_ble_update(int64_t now_ms, bool has_pending_logs);
void tickstone_ble_publish_log(const habit_log_t *log);
void tickstone_ble_publish_habits(const habit_config_t *habits, size_t count);
bool tickstone_ble_take_ack(uint64_t *log_id);
bool tickstone_ble_take_time(int64_t *utc_seconds);
