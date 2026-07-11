idf_component_register(
    SRCS "app_main.c"
    INCLUDE_DIRS "."
    REQUIRES esp_timer buttons display_idle habit_app habit_storage ssd1306_oled
)
