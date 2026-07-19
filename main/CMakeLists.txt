idf_component_register(
    SRCS "app_main.c"
    INCLUDE_DIRS "."
    REQUIRES esp_pm esp_timer buttons clock_service clock_sync_policy display_idle finish_alert habit_app habit_storage ssd1306_oled tickstone_ble tickstone_usb
)
