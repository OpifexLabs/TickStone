idf_component_register(
    SRCS "habit_storage.c" "habit_storage_plan.c"
    INCLUDE_DIRS "include"
    REQUIRES habit_app nvs_flash
)
