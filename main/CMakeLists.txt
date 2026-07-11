idf_component_register(
    SRCS "app_main.c"
    INCLUDE_DIRS "."
    REQUIRES esp_pm esp_timer buttons clock_service display_idle finish_alert habit_app habit_storage ssd1306_oled sync_policy tickstone_network
)
