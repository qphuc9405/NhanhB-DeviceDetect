idf_component_register(SRCS "main.c" INCLUDE_DIRS "." "../../common" REQUIRES esp_wifi esp_event esp_netif nvs_flash esp_timer esp_driver_uart lwip esp_hw_support)
