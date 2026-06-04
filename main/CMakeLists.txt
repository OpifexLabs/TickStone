idf_component_register(
    SRCS "app_main.c"
    INCLUDE_DIRS "."
    REQUIRES buttons driver esp_timer habit_leds max7219_matrix
)
