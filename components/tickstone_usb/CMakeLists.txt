idf_component_register(
    SRCS "tickstone_usb.c"
    INCLUDE_DIRS "include"
    REQUIRES clock_service habit_app habit_web_config
)
