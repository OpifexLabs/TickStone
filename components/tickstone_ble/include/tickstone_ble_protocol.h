#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "habit_app.h"

#define TICKSTONE_BLE_PACKET_SIZE 34
#define TICKSTONE_BLE_PACKET_VERSION 1
#define TICKSTONE_BLE_CONFIG_VERSION 1
#define TICKSTONE_BLE_CONFIG_PACKET_SIZE 28
#define TICKSTONE_BLE_CONFIG_PAGE_COUNT 11

bool tickstone_ble_encode_log(const habit_log_t *log,
                              uint8_t out[TICKSTONE_BLE_PACKET_SIZE]);
uint32_t tickstone_ble_config_hash(const habit_config_t *habits, size_t count);
bool tickstone_ble_encode_config_page(const habit_config_t *habits,
                                      size_t count,
                                      uint8_t page,
                                      uint8_t out[TICKSTONE_BLE_CONFIG_PACKET_SIZE]);
