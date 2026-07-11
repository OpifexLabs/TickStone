#pragma once
#include <stdbool.h>
#include <stddef.h>
#include "habit_app.h"

bool sync_payload_build(const habit_log_t *log, char *json, size_t json_size, char *key, size_t key_size);
