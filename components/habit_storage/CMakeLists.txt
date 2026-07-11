idf_component_register(
    SRCS "habit_storage.c"
    INCLUDE_DIRS "include"
    REQUIRES habit_app habit_codec habit_legacy habit_ring nvs_flash
)
