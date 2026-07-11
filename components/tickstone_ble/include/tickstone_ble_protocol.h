#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "habit_app.h"

#define TICKSTONE_BLE_PACKET_SIZE 34
#define TICKSTONE_BLE_PACKET_VERSION 1

bool tickstone_ble_encode_log(const habit_log_t *log,
                              uint8_t out[TICKSTONE_BLE_PACKET_SIZE]);
