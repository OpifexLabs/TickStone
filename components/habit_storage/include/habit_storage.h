#pragma once

#include "esp_err.h"
#include "habit_app.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t habit_storage_init(void);
esp_err_t habit_storage_erase_all(void);
esp_err_t habit_storage_load(habit_app_t *app, int64_t now_seconds);
esp_err_t habit_storage_save_habits(const habit_app_t *app);
esp_err_t habit_storage_save_logs(const habit_app_t *app);
esp_err_t habit_storage_save_session(const habit_app_t *app);

#ifdef __cplusplus
}
#endif
