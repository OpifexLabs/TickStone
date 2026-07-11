idf_component_register(
    SRCS "tickstone_network.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_event esp_http_client esp_http_server esp_netif esp_wifi lwip mbedtls nvs_flash habit_app habit_web_config sync_payload
)
