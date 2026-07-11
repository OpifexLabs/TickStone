#include "habit_storage.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_check.h"
#include "habit_codec.h"
#include "habit_ring.h"
#include "habit_legacy.h"
#include "nvs.h"
#include "nvs_flash.h"

#define NS "tickstone"
#define CFG3 "cfg3"
#define SES3 "ses3"
#define LOG_VERSION_KEY "lv"
#define LOG_COUNT_KEY "lc"
#define LOG_OLDEST_KEY "lo"
#define LOG_NEWEST_KEY "ln"
#define LOG_PREFIX "e"
#define LOG_VERSION 3
#define OLD_CFG "habits"
#define OLD_META "logmeta"
#define OLD_SESSION "session"
#define OLD_LOG_PREFIX "log"
#define DAILY_PREFIX "d"

static const char *TAG = "habit_storage";


static habit_config_t s_habits[HABIT_APP_MAX_HABITS];

static esp_err_t open_rw(nvs_handle_t *h) { return nvs_open(NS, NVS_READWRITE, h); }

static void log_key(uint64_t id, char *out, size_t size)
{
    snprintf(out, size, LOG_PREFIX "%03u", (unsigned)(id % HABIT_APP_MAX_LOGS));
}

static void slot_key(size_t slot, char *out, size_t size)
{
    snprintf(out, size, LOG_PREFIX "%03u", (unsigned)slot);
}

static void old_log_key(size_t index, char *out, size_t size)
{
    snprintf(out, size, OLD_LOG_PREFIX "%03u", (unsigned)index);
}

static size_t daily_slot(const habit_daily_summary_t *summary)
{
    uint32_t day = (uint32_t)summary->day_id;
    return (day % 70u) * HABIT_APP_MAX_HABITS + summary->habit_id;
}

static void daily_key(size_t slot, char *out, size_t size)
{
    snprintf(out, size, DAILY_PREFIX "%03u", (unsigned)slot);
}

esp_err_t habit_storage_init(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGE(TAG, "NVS recovery required; user data will not be erased automatically");
    }
    return err;
}

esp_err_t habit_storage_erase_all(void)
{
    nvs_handle_t h = 0;
    ESP_RETURN_ON_ERROR(open_rw(&h), TAG, "open erase failed");
    esp_err_t err = nvs_erase_all(h);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    if (err == ESP_OK) {
    }
    return err;
}

static esp_err_t load_cfg3(nvs_handle_t h, habit_app_t *app)
{
    uint8_t data[HABIT_CODEC_HABITS_MAX_SIZE] = {0};
    size_t size = sizeof(data), count = 0;
    esp_err_t err = nvs_get_blob(h, CFG3, data, &size);
    if (err != ESP_OK) return err;
    if (!habit_codec_decode_habits(data, size, s_habits, HABIT_APP_MAX_HABITS, &count) ||
        !habit_app_load_habits(app, s_habits, count)) return ESP_ERR_INVALID_CRC;
    return ESP_OK;
}

static esp_err_t load_old_cfg(nvs_handle_t h, habit_app_t *app)
{
    habit_legacy_config_t blob = {0};
    habit_config_t converted[HABIT_APP_MAX_HABITS] = {0};
    size_t count = 0;
    size_t size = sizeof(blob);
    esp_err_t err = nvs_get_blob(h, OLD_CFG, &blob, &size);
    if (err != ESP_OK) return err;
    if (size != sizeof(blob) ||
        !habit_legacy_convert_config(&blob, converted, HABIT_APP_MAX_HABITS, &count) ||
        !habit_app_load_habits(app, converted, count)) return ESP_ERR_INVALID_VERSION;
    return ESP_OK;
}

static esp_err_t recover_logs3(nvs_handle_t h, habit_app_t *app)
{
    habit_log_t *logs = calloc(HABIT_APP_MAX_LOGS, sizeof(*logs));
    if (!logs) return ESP_ERR_NO_MEM;
    size_t found = 0;
    for (size_t slot = 0; slot < HABIT_APP_MAX_LOGS; ++slot) {
        char key[8]; slot_key(slot, key, sizeof(key));
        uint8_t data[HABIT_CODEC_LOG_SIZE]; size_t size = sizeof(data);
        if (nvs_get_blob(h, key, data, &size) != ESP_OK) continue;
        habit_log_t log;
        if (!habit_codec_decode_log(data, size, &log) || log.id == 0 ||
            log.id % HABIT_APP_MAX_LOGS != slot) continue;
        logs[found++] = log;
    }
    if (!found) { free(logs); return ESP_ERR_NVS_NOT_FOUND; }
    size_t best_count = habit_ring_select_contiguous(logs, found);
    habit_app_load_logs(app, logs, best_count);
    esp_err_t err = nvs_set_u8(h, LOG_VERSION_KEY, LOG_VERSION);
    if (err == ESP_OK) err = nvs_set_u16(h, LOG_COUNT_KEY, (uint16_t)best_count);
    if (err == ESP_OK) err = nvs_set_u64(h, LOG_OLDEST_KEY, logs[0].id);
    if (err == ESP_OK) err = nvs_set_u64(h, LOG_NEWEST_KEY, logs[best_count - 1].id);
    free(logs);
    ESP_RETURN_ON_ERROR(err, TAG, "repair metadata failed");
    ESP_LOGW(TAG, "Recovered %u logs from ring slots", (unsigned)best_count);
    return nvs_commit(h);
}

static esp_err_t load_logs3(nvs_handle_t h, habit_app_t *app)
{
    uint8_t version = 0;
    uint16_t count = 0;
    uint64_t oldest = 0, newest = 0;
    esp_err_t err = nvs_get_u8(h, LOG_VERSION_KEY, &version);
    if (err == ESP_ERR_NVS_NOT_FOUND) return recover_logs3(h, app);
    if (err != ESP_OK || nvs_get_u16(h, LOG_COUNT_KEY, &count) != ESP_OK ||
        nvs_get_u64(h, LOG_OLDEST_KEY, &oldest) != ESP_OK ||
        nvs_get_u64(h, LOG_NEWEST_KEY, &newest) != ESP_OK) return recover_logs3(h, app);
    if (version != LOG_VERSION || count > HABIT_APP_MAX_LOGS ||
        (count && (!oldest || newest < oldest || newest - oldest + 1 != count))) {
        return recover_logs3(h, app);
    }
    habit_log_t *logs = calloc(count ? count : 1, sizeof(*logs));
    if (!logs) return ESP_ERR_NO_MEM;
    for (size_t i = 0; i < count; ++i) {
        uint64_t id = oldest + i;
        char key[8]; log_key(id, key, sizeof(key));
        uint8_t data[HABIT_CODEC_LOG_SIZE] = {0};
        size_t size = sizeof(data);
        if (nvs_get_blob(h, key, data, &size) != ESP_OK ||
            !habit_codec_decode_log(data, size, &logs[i]) || logs[i].id != id) {
            free(logs); return recover_logs3(h, app);
        }
    }
    habit_app_load_logs(app, logs, count); free(logs);
    return ESP_OK;
}

static esp_err_t load_old_logs(nvs_handle_t h, habit_app_t *app)
{
    habit_legacy_meta_t meta = {0};
    size_t meta_size = sizeof(meta);
    esp_err_t err = nvs_get_blob(h, OLD_META, &meta, &meta_size);
    if (err != ESP_OK) return err;
    if (meta_size != sizeof(meta) || meta.version != 2 || meta.count > 128) {
        return ESP_ERR_INVALID_VERSION;
    }
    habit_log_t *logs = calloc(meta.count ? meta.count : 1, sizeof(*logs));
    if (!logs) return ESP_ERR_NO_MEM;
    for (size_t i = 0; i < meta.count; ++i) {
        char key[8]; old_log_key(i, key, sizeof(key));
        habit_legacy_log_t old = {0}; size_t size = sizeof(old);
        err = nvs_get_blob(h, key, &old, &size);
        if (err != ESP_OK || size != sizeof(old)) { free(logs); return err == ESP_OK ? ESP_ERR_INVALID_SIZE : err; }
        if (!habit_legacy_convert_log(&old, i + 1, &logs[i])) { free(logs); return ESP_ERR_INVALID_VERSION; }
    }
    habit_app_load_logs(app, logs, meta.count); free(logs);
    return ESP_OK;
}

static esp_err_t load_session3(nvs_handle_t h, habit_app_t *app, int64_t now)
{
    uint8_t data[HABIT_CODEC_SESSION_SIZE] = {0}; size_t size = sizeof(data);
    esp_err_t err = nvs_get_blob(h, SES3, data, &size);
    if (err != ESP_OK) return err;
    habit_session_snapshot_t session = {0};
    if (!habit_codec_decode_session(data, size, &session)) return ESP_ERR_INVALID_CRC;
    habit_app_restore_session(app, &session, now);
    return ESP_OK;
}

static esp_err_t load_old_session(nvs_handle_t h, habit_app_t *app, int64_t now)
{
    habit_legacy_session_blob_t blob = {0}; size_t size = sizeof(blob);
    esp_err_t err = nvs_get_blob(h, OLD_SESSION, &blob, &size);
    if (err != ESP_OK) return err;
    habit_session_snapshot_t s;
    if (size != sizeof(blob) || !habit_legacy_convert_session(&blob, &s)) return ESP_ERR_INVALID_VERSION;
    habit_app_restore_session(app, &s, now);
    return ESP_OK;
}

static esp_err_t load_daily(nvs_handle_t h, habit_app_t *app)
{
    habit_daily_summary_t *daily = calloc(HABIT_APP_MAX_DAILY_SUMMARIES, sizeof(*daily));
    if (!daily) return ESP_ERR_NO_MEM;
    size_t count = 0;
    for (size_t slot = 0; slot < HABIT_APP_MAX_DAILY_SUMMARIES; ++slot) {
        char key[8]; daily_key(slot, key, sizeof(key));
        uint8_t data[HABIT_CODEC_DAILY_SIZE]; size_t size = sizeof(data);
        habit_daily_summary_t summary;
        if (nvs_get_blob(h, key, data, &size) != ESP_OK || !habit_codec_decode_daily(data, size, &summary) ||
            daily_slot(&summary) != slot) continue;
        daily[count++] = summary;
    }
    habit_app_load_daily(app, daily, count); free(daily); return ESP_OK;
}

esp_err_t habit_storage_load(habit_app_t *app, int64_t now)
{
    nvs_handle_t h = 0;
    ESP_RETURN_ON_ERROR(open_rw(&h), TAG, "open load failed");
    bool migrate_cfg = false, migrate_logs = false, migrate_session = false;
    esp_err_t err = load_cfg3(h, app);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        err = load_old_cfg(h, app); migrate_cfg = err == ESP_OK;
        if (err == ESP_ERR_NVS_NOT_FOUND) err = ESP_OK;
    }
    if (err == ESP_OK) {
        err = load_logs3(h, app);
        if (err == ESP_ERR_NVS_NOT_FOUND) {
            err = load_old_logs(h, app); migrate_logs = err == ESP_OK;
            if (err == ESP_ERR_NVS_NOT_FOUND) err = ESP_OK;
        }
    }
    if (err == ESP_OK) err = load_daily(h, app);
    if (err == ESP_OK) {
        err = load_session3(h, app, now);
        if (err == ESP_ERR_NVS_NOT_FOUND) {
            err = load_old_session(h, app, now); migrate_session = err == ESP_OK;
            if (err == ESP_ERR_NVS_NOT_FOUND) err = ESP_OK;
        }
    }
    nvs_close(h);
    ESP_RETURN_ON_ERROR(err, TAG, "repository data invalid");
    if (migrate_cfg) ESP_RETURN_ON_ERROR(habit_storage_save_habits(app), TAG, "migrate cfg failed");
    if (migrate_logs) ESP_RETURN_ON_ERROR(habit_storage_save_logs(app), TAG, "migrate logs failed");
    if (migrate_session) ESP_RETURN_ON_ERROR(habit_storage_save_session(app), TAG, "migrate session failed");
    return ESP_OK;
}

esp_err_t habit_storage_save_habits(const habit_app_t *app)
{
    size_t count = habit_app_copy_habits(app, s_habits, HABIT_APP_MAX_HABITS);
    uint8_t data[HABIT_CODEC_HABITS_MAX_SIZE] = {0}; size_t size = 0;
    if (!habit_codec_encode_habits(s_habits, count, data, sizeof(data), &size)) return ESP_ERR_INVALID_ARG;
    nvs_handle_t h = 0; ESP_RETURN_ON_ERROR(open_rw(&h), TAG, "open cfg failed");
    esp_err_t err = nvs_set_blob(h, CFG3, data, size);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h); return err;
}

esp_err_t habit_storage_save_logs(const habit_app_t *app)
{
    size_t count = habit_app_copy_logs(app, NULL, 0);
    nvs_handle_t h = 0; ESP_RETURN_ON_ERROR(open_rw(&h), TAG, "open logs failed");
    esp_err_t err = ESP_OK;
    for (size_t i = 0; i < count && err == ESP_OK; ++i) {
        habit_log_t log;
        if (!habit_app_get_log(app, i, &log)) { err = ESP_ERR_INVALID_STATE; break; }
        uint8_t data[HABIT_CODEC_LOG_SIZE] = {0};
        if (!habit_codec_encode_log(&log, data, sizeof(data))) { err = ESP_ERR_INVALID_ARG; break; }
        char key[8]; log_key(log.id, key, sizeof(key));
        uint8_t existing[HABIT_CODEC_LOG_SIZE]; size_t existing_size = sizeof(existing);
        if (nvs_get_blob(h, key, existing, &existing_size) == ESP_OK &&
            existing_size == sizeof(existing) && !memcmp(existing, data, sizeof(data))) continue;
        err = nvs_set_blob(h, key, data, sizeof(data));
    }
    if (err == ESP_OK) err = nvs_set_u8(h, LOG_VERSION_KEY, LOG_VERSION);
    if (err == ESP_OK) err = nvs_set_u16(h, LOG_COUNT_KEY, (uint16_t)count);
    habit_log_t first = {0}, last = {0};
    if (count) { habit_app_get_log(app, 0, &first); habit_app_get_log(app, count - 1, &last); }
    uint64_t oldest = first.id, newest = last.id;
    if (err == ESP_OK) err = nvs_set_u64(h, LOG_OLDEST_KEY, oldest);
    if (err == ESP_OK) err = nvs_set_u64(h, LOG_NEWEST_KEY, newest);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h); return err;
}

esp_err_t habit_storage_save_daily(const habit_app_t *app)
{
    size_t count = habit_app_copy_daily(app, NULL, 0);
    habit_daily_summary_t *daily = calloc(count ? count : 1, sizeof(*daily));
    if (!daily) return ESP_ERR_NO_MEM;
    habit_app_copy_daily(app, daily, count);
    nvs_handle_t h = 0; esp_err_t err = open_rw(&h);
    if (err != ESP_OK) { free(daily); return err; }
    err = ESP_OK;
    for (size_t i = 0; i < count && err == ESP_OK; ++i) {
        size_t slot = daily_slot(&daily[i]);
        uint8_t data[HABIT_CODEC_DAILY_SIZE];
        if (!habit_codec_encode_daily(&daily[i], data, sizeof(data))) { err = ESP_ERR_INVALID_ARG; break; }
        char key[8]; daily_key(slot, key, sizeof(key));
        uint8_t existing[HABIT_CODEC_DAILY_SIZE]; size_t existing_size = sizeof(existing);
        if (nvs_get_blob(h, key, existing, &existing_size) == ESP_OK &&
            existing_size == sizeof(existing) && !memcmp(existing, data, sizeof(data))) continue;
        err = nvs_set_blob(h, key, data, sizeof(data));
    }
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h); free(daily); return err;
}

esp_err_t habit_storage_save_session(const habit_app_t *app)
{
    habit_session_snapshot_t session = {0}; bool active = habit_app_export_session(app, &session);
    nvs_handle_t h = 0; ESP_RETURN_ON_ERROR(open_rw(&h), TAG, "open session failed");
    esp_err_t err = ESP_OK;
    if (active) {
        uint8_t data[HABIT_CODEC_SESSION_SIZE] = {0};
        if (!habit_codec_encode_session(&session, data, sizeof(data))) { nvs_close(h); return ESP_ERR_INVALID_ARG; }
        err = nvs_set_blob(h, SES3, data, sizeof(data));
    } else {
        err = nvs_erase_key(h, SES3); if (err == ESP_ERR_NVS_NOT_FOUND) err = ESP_OK;
    }
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h); return err;
}
