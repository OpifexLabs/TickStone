#include "habit_web_config.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int hex_digit(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static bool field(const char *body, const char *key, char *out, size_t size)
{
    size_t key_len = strlen(key);
    for (const char *p = body; p && *p;) {
        const char *end = strchr(p, '&'); if (!end) end = p + strlen(p);
        if ((size_t)(end - p) > key_len && !strncmp(p, key, key_len) && p[key_len] == '=') {
            const char *read = p + key_len + 1; size_t written = 0;
            while (read < end) {
                char c = *read++;
                if (c == '+') c = ' ';
                else if (c == '%' && read + 1 < end) {
                    int hi = hex_digit(read[0]), lo = hex_digit(read[1]);
                    if (hi < 0 || lo < 0) return false;
                    c = (char)((hi << 4) | lo); read += 2;
                }
                if (written + 1 >= size || c == 0) return false;
                out[written++] = c;
            }
            out[written] = 0; return true;
        }
        p = *end ? end + 1 : end;
    }
    out[0] = 0; return true;
}

bool habit_web_config_parse(const char *body, habit_web_config_t *out)
{
    if (!body || !out) return false;
    habit_web_config_t parsed = {0};
    char custom_ssid[sizeof(parsed.ssid)] = {0};
    if (!field(body, "ssid", parsed.ssid, sizeof(parsed.ssid)) ||
        !field(body, "ssid_custom", custom_ssid, sizeof(custom_ssid)) ||
        !field(body, "pass", parsed.password, sizeof(parsed.password)) ||
        !field(body, "url", parsed.sync_url, sizeof(parsed.sync_url))) return false;
    if (custom_ssid[0]) memcpy(parsed.ssid, custom_ssid, sizeof(parsed.ssid));
    for (size_t slot = 0; slot < HABIT_APP_MAX_HABITS; ++slot) {
        char key[8], label[8] = {0}, name[HABIT_APP_NAME_LEN + 1] = {0}, type[4] = {0}, minutes[8] = {0};
        snprintf(key, sizeof(key), "n%u", (unsigned)slot);
        if (!field(body, key, label, sizeof(label))) return false;
        if (!label[0]) continue;
        size_t len = strlen(label); if (len > HABIT_APP_LABEL_LEN) return false;
        for (size_t i = 0; i < len; ++i) {
            if (label[i] >= 'a' && label[i] <= 'z') label[i] -= 'a' - 'A';
            if (!((label[i] >= 'A' && label[i] <= 'Z') || (label[i] >= '0' && label[i] <= '9'))) return false;
        }
        snprintf(key, sizeof(key), "f%u", (unsigned)slot);
        if (!field(body, key, name, sizeof(name))) return false;
        if (!name[0]) memcpy(name, label, len + 1);
        for (size_t i = 0; name[i]; ++i) {
            if (name[i] >= 'a' && name[i] <= 'z') name[i] -= 'a' - 'A';
            if (!((name[i] >= 'A' && name[i] <= 'Z') ||
                  (name[i] >= '0' && name[i] <= '9') || name[i] == ' ')) return false;
        }
        snprintf(key, sizeof(key), "t%u", (unsigned)slot);
        if (!field(body, key, type, sizeof(type)) || (type[0] != 'c' && type[0] != 't' && type[0] != 's') || type[1]) return false;
        snprintf(key, sizeof(key), "d%u", (unsigned)slot);
        if (!field(body, key, minutes, sizeof(minutes))) return false;
        char *tail = NULL; long value = minutes[0] ? strtol(minutes, &tail, 10) : 5;
        if (!tail || *tail || value < 1 || value > 99) return false;
        habit_config_t *habit = &parsed.habits[parsed.habit_count++];
        habit->id = (uint8_t)slot; memcpy(habit->label, label, len + 1);
        memcpy(habit->name, name, strlen(name) + 1);
        habit->type = type[0] == 'c' ? HABIT_TYPE_COUNT : HABIT_TYPE_TIME;
        habit->time_mode = HABIT_TIME_TIMER;
        habit->default_minutes = (uint16_t)value;
    }
    if (!parsed.habit_count) return false;
    *out = parsed; return true;
}
