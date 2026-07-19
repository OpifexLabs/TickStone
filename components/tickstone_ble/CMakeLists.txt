idf_component_register(
    SRCS "tickstone_ble.c" "tickstone_ble_protocol.c"
    INCLUDE_DIRS "include"
    REQUIRES bt clock_service habit_app
)
