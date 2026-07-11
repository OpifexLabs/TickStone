#pragma once
#include <stdbool.h>
#include <stddef.h>
#include "habit_app.h"

typedef struct {
    char ssid[33];
    char password[64];
    char sync_url[192];
    habit_config_t habits[HABIT_APP_MAX_HABITS];
    size_t habit_count;
} habit_web_config_t;

bool habit_web_config_parse(const char *body, habit_web_config_t *out);
