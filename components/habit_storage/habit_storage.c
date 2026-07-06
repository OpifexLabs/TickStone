#include "habit_storage.h"
#include "habit_storage_plan.h"

#include <stdio.h>
#include <string.h>

#include "esp_check.h"
#include "nvs.h"
#include "nvs_flash.h"

#define STORAGE_NAMESPACE "tickstone"
#define STORAGE_OLD_LOGS_KEY "logs"
#define STORAGE_HABITS_KEY "habits"
#define STORAGE_META_KEY "logmeta"
#define STORAGE_SESSION_KEY "session"
#define STORAGE_LOG_KEY_PREFIX "log"
#define STORAGE_LOGS_VERSION 2
#define STORAGE_HABITS_VERSION 1
#define STORAGE_OLD_LOGS_VERSION 1
#define STORAGE_SESSION_VERSION 1

static const char *TAG = "habit_storage";

typedef struct {
    uint32_t version;
    uint32_t count;
    habit_log_t logs[HABIT_APP_MAX_LOGS];
} old_logs_blob_t;

typedef struct {
    uint32_t version;
    uint32_t count;
} logs_meta_t;

typedef struct {
    uint32_t version;
    uint32_t count;
    habit_config_t habits[HABIT_APP_MAX_HABITS];
} habits_blob_t;

typedef struct {
    uint32_t version;
    habit_session_snapshot_t session;
} session_blob_t;

static old_logs_blob_t s_old_logs_blob;
static habits_blob_t s_habits_blob;
static habit_log_t s_log_buffer[HABIT_APP_MAX_LOGS];
static session_blob_t s_session_blob;
static size_t s_saved_log_count;

static void log_key(size_t index, char *out, size_t out_size)
{
    snprintf(out, out_size, STORAGE_LOG_KEY_PREFIX "%03u", (unsigned)index);
}

esp_err_t habit_storage_init(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_RETURN_ON_ERROR(nvs_flash_erase(), TAG, "erase nvs failed");
        err = nvs_flash_init();
    }
    return err;
}

static esp_err_t open_rw(nvs_handle_t *handle)
{
    return nvs_open(STORAGE_NAMESPACE, NVS_READWRITE, handle);
}

esp_err_t habit_storage_erase_all(void)
{
    nvs_handle_t handle = 0;
    ESP_RETURN_ON_ERROR(open_rw(&handle), TAG, "open nvs for erase failed");
    esp_err_t err = nvs_erase_all(handle);
    if (err == ESP_OK) {
        err = nvs_commit(handle);
    }
    nvs_close(handle);
    if (err == ESP_OK) {
        s_saved_log_count = 0;
        memset(&s_habits_blob, 0, sizeof(s_habits_blob));
        memset(&s_session_blob, 0, sizeof(s_session_blob));
        memset(s_log_buffer, 0, sizeof(s_log_buffer));
    }
    return err;
}

static esp_err_t load_habits(nvs_handle_t handle, habit_app_t *app)
{
    memset(&s_habits_blob, 0, sizeof(s_habits_blob));
    size_t habits_size = sizeof(s_habits_blob);
    esp_err_t err = nvs_get_blob(handle, STORAGE_HABITS_KEY, &s_habits_blob, &habits_size);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        return ESP_OK;
    }
    ESP_RETURN_ON_ERROR(err, TAG, "read habits failed");

    if (s_habits_blob.version != STORAGE_HABITS_VERSION ||
        s_habits_blob.count == 0 ||
        s_habits_blob.count > HABIT_APP_MAX_HABITS ||
        !habit_app_load_habits(app, s_habits_blob.habits, s_habits_blob.count)) {
        return ESP_ERR_INVALID_VERSION;
    }
    return ESP_OK;
}

static esp_err_t write_meta(nvs_handle_t handle, size_t count)
{
    const logs_meta_t meta = {
        .version = STORAGE_LOGS_VERSION,
        .count = count,
    };
    return nvs_set_blob(handle, STORAGE_META_KEY, &meta, sizeof(meta));
}

static esp_err_t write_log_at(nvs_handle_t handle, size_t index, const habit_log_t *log)
{
    char key[8];
    log_key(index, key, sizeof(key));
    return nvs_set_blob(handle, key, log, sizeof(*log));
}

static esp_err_t load_v2_logs(nvs_handle_t handle, habit_app_t *app)
{
    logs_meta_t meta = {0};
    size_t meta_size = sizeof(meta);
    esp_err_t err = nvs_get_blob(handle, STORAGE_META_KEY, &meta, &meta_size);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        return ESP_ERR_NVS_NOT_FOUND;
    }
    ESP_RETURN_ON_ERROR(err, TAG, "read log meta failed");

    if (meta.version != STORAGE_LOGS_VERSION || meta.count > HABIT_APP_MAX_LOGS) {
        return ESP_ERR_INVALID_VERSION;
    }

    memset(s_log_buffer, 0, sizeof(s_log_buffer));
    for (size_t i = 0; i < meta.count; ++i) {
        char key[8];
        log_key(i, key, sizeof(key));
        size_t log_size = sizeof(s_log_buffer[i]);
        err = nvs_get_blob(handle, key, &s_log_buffer[i], &log_size);
        ESP_RETURN_ON_ERROR(err, TAG, "read log entry failed");
    }

    habit_app_load_logs(app, s_log_buffer, meta.count);
    s_saved_log_count = meta.count;
    return ESP_OK;
}

static esp_err_t migrate_old_logs(nvs_handle_t handle, habit_app_t *app)
{
    memset(&s_old_logs_blob, 0, sizeof(s_old_logs_blob));
    size_t old_size = sizeof(s_old_logs_blob);
    esp_err_t err = nvs_get_blob(handle, STORAGE_OLD_LOGS_KEY, &s_old_logs_blob, &old_size);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        s_saved_log_count = 0;
        return ESP_OK;
    }
    ESP_RETURN_ON_ERROR(err, TAG, "read old logs failed");

    if (s_old_logs_blob.version != STORAGE_OLD_LOGS_VERSION) {
        return ESP_ERR_INVALID_VERSION;
    }

    if (s_old_logs_blob.count > HABIT_APP_MAX_LOGS) {
        s_old_logs_blob.count = HABIT_APP_MAX_LOGS;
    }

    for (size_t i = 0; i < s_old_logs_blob.count; ++i) {
        ESP_RETURN_ON_ERROR(write_log_at(handle, i, &s_old_logs_blob.logs[i]), TAG, "migrate log failed");
    }
    ESP_RETURN_ON_ERROR(write_meta(handle, s_old_logs_blob.count), TAG, "write migrated meta failed");
    err = nvs_erase_key(handle, STORAGE_OLD_LOGS_KEY);
    if (err != ESP_ERR_NVS_NOT_FOUND) {
        ESP_RETURN_ON_ERROR(err, TAG, "erase old logs failed");
    }
    ESP_RETURN_ON_ERROR(nvs_commit(handle), TAG, "commit migrated logs failed");

    habit_app_load_logs(app, s_old_logs_blob.logs, s_old_logs_blob.count);
    s_saved_log_count = s_old_logs_blob.count;
    return ESP_OK;
}

esp_err_t habit_storage_load(habit_app_t *app, int64_t now_seconds)
{
    nvs_handle_t handle = 0;
    ESP_RETURN_ON_ERROR(open_rw(&handle), TAG, "open nvs failed");

    esp_err_t err = load_habits(handle, app);
    if (err != ESP_OK) {
        nvs_close(handle);
        return err;
    }

    err = load_v2_logs(handle, app);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        err = migrate_old_logs(handle, app);
    }
    if (err != ESP_OK) {
        nvs_close(handle);
        return err;
    }

    memset(&s_session_blob, 0, sizeof(s_session_blob));
    size_t session_size = sizeof(s_session_blob);
    err = nvs_get_blob(handle, STORAGE_SESSION_KEY, &s_session_blob, &session_size);
    if (err == ESP_OK && s_session_blob.version == STORAGE_SESSION_VERSION) {
        habit_app_restore_session(app, &s_session_blob.session, now_seconds);
    } else if (err != ESP_ERR_NVS_NOT_FOUND) {
        nvs_close(handle);
        return err;
    }

    nvs_close(handle);
    return ESP_OK;
}

esp_err_t habit_storage_save_habits(const habit_app_t *app)
{
    size_t count = habit_app_copy_habits(app, NULL, 0);
    if (count == 0 || count > HABIT_APP_MAX_HABITS) {
        return ESP_ERR_INVALID_ARG;
    }

    memset(&s_habits_blob, 0, sizeof(s_habits_blob));
    s_habits_blob.version = STORAGE_HABITS_VERSION;
    s_habits_blob.count = count;
    habit_app_copy_habits(app, s_habits_blob.habits, HABIT_APP_MAX_HABITS);

    nvs_handle_t handle = 0;
    ESP_RETURN_ON_ERROR(open_rw(&handle), TAG, "open nvs for habits failed");
    esp_err_t err = nvs_set_blob(handle, STORAGE_HABITS_KEY, &s_habits_blob, sizeof(s_habits_blob));
    if (err == ESP_OK) {
        err = nvs_commit(handle);
    }
    nvs_close(handle);
    return err;
}

esp_err_t habit_storage_save_logs(const habit_app_t *app)
{
    const size_t count = habit_app_copy_logs(app, NULL, 0);
    habit_storage_log_plan_t plan = habit_storage_plan_logs(s_saved_log_count,
                                                            count,
                                                            HABIT_APP_MAX_LOGS,
                                                            habit_app_last_log_index(app));
    nvs_handle_t handle = 0;
    ESP_RETURN_ON_ERROR(open_rw(&handle), TAG, "open nvs for logs failed");

    esp_err_t err = ESP_OK;
    if (plan.mode == HABIT_STORAGE_LOG_WRITE_APPEND) {
        habit_log_t log = {0};
        if (habit_app_get_log(app, plan.append_index, &log)) {
            err = write_log_at(handle, plan.append_index, &log);
        }
    } else if (plan.mode == HABIT_STORAGE_LOG_WRITE_FULL) {
        for (size_t i = 0; i < count && err == ESP_OK; ++i) {
            habit_log_t log = {0};
            if (habit_app_get_log(app, i, &log)) {
                err = write_log_at(handle, i, &log);
            }
        }
    }

    if (err == ESP_OK && plan.rewrite_latest) {
        habit_log_t log = {0};
        if (habit_app_get_log(app, plan.latest_index, &log)) {
            err = write_log_at(handle, plan.latest_index, &log);
        }
    }

    if (err == ESP_OK && plan.write_meta) {
        err = write_meta(handle, count);
    }
    if (err == ESP_OK) {
        err = nvs_commit(handle);
    }
    if (err == ESP_OK) {
        s_saved_log_count = count;
    }
    nvs_close(handle);
    return err;
}

esp_err_t habit_storage_save_session(const habit_app_t *app)
{
    habit_session_snapshot_t session = {0};
    bool active = habit_app_export_session(app, &session);

    nvs_handle_t handle = 0;
    ESP_RETURN_ON_ERROR(open_rw(&handle), TAG, "open nvs for session failed");

    esp_err_t err;
    if (active) {
        s_session_blob = (session_blob_t) {
            .version = STORAGE_SESSION_VERSION,
            .session = session,
        };
        err = nvs_set_blob(handle, STORAGE_SESSION_KEY, &s_session_blob, sizeof(s_session_blob));
    } else {
        err = nvs_erase_key(handle, STORAGE_SESSION_KEY);
        if (err == ESP_ERR_NVS_NOT_FOUND) {
            err = ESP_OK;
        }
    }

    if (err == ESP_OK) {
        err = nvs_commit(handle);
    }
    nvs_close(handle);
    return err;
}
