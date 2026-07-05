#include <stddef.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "driver/gpio.h"
#include "esp_check.h"
#include "esp_log.h"

#include "app_config.h"
#include "ssd1306_oled.h"

static const char *TAG = APP_NAME;

static esp_err_t show_word(const char *word, uint8_t x)
{
    ESP_RETURN_ON_ERROR(ssd1306_oled_clear(), TAG, "clear display failed");
    return ssd1306_oled_draw_text_2x(x, 7, word);
}

typedef struct {
    gpio_num_t pin;
    const char *label;
    uint8_t x;
} button_display_t;

static esp_err_t init_oled_on_known_pins(ssd1306_oled_config_t *active_config)
{
    static const ssd1306_oled_config_t preferred_candidates[] = {
        {.sda_pin = OLED_SDA_PIN, .scl_pin = OLED_SCL_PIN, .address = OLED_I2C_ADDRESS},
    };

    for (size_t i = 0; i < sizeof(preferred_candidates) / sizeof(preferred_candidates[0]); ++i) {
        ESP_LOGI(TAG,
                 "Trying OLED on SDA GPIO%ld / SCL GPIO%ld",
                 (long)preferred_candidates[i].sda_pin,
                 (long)preferred_candidates[i].scl_pin);

        esp_err_t err = ssd1306_oled_init(&preferred_candidates[i]);
        if (err == ESP_OK) {
            *active_config = preferred_candidates[i];
            return ESP_OK;
        }
    }

    return ESP_ERR_NOT_FOUND;
}

void app_main(void)
{
    ESP_LOGI(TAG, "OLED test starting");
    vTaskDelay(pdMS_TO_TICKS(200));

    ssd1306_oled_config_t oled_config = {0};
    esp_err_t err = init_oled_on_known_pins(&oled_config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG,
                 "OLED not found. Check power, GND, and which GPIO your board labels D4/D5 actually map to.");
        while (true) {
            vTaskDelay(pdMS_TO_TICKS(1000));
        }
    }

    static const button_display_t buttons[] = {
        {.pin = GPIO_NUM_20, .label = "d7", .x = 52},
        {.pin = GPIO_NUM_8, .label = "d8", .x = 52},
        {.pin = GPIO_NUM_9, .label = "d9", .x = 52},
    };

    gpio_config_t button_config = {
        .pin_bit_mask = 0,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };

    for (size_t i = 0; i < sizeof(buttons) / sizeof(buttons[0]); ++i) {
        button_config.pin_bit_mask |= (1ULL << buttons[i].pin);
    }

    ESP_ERROR_CHECK(gpio_config(&button_config));

    gpio_num_t last_pressed_pin = GPIO_NUM_NC;
    ESP_ERROR_CHECK(show_word("d7", 52));

    ESP_LOGI(TAG,
             "OLED should show d7/d8/d9; SDA GPIO%ld / SCL GPIO%ld",
             (long)oled_config.sda_pin,
             (long)oled_config.scl_pin);

    while (true) {
        gpio_num_t pressed_pin = GPIO_NUM_NC;
        const button_display_t *pressed_button = NULL;

        for (size_t i = 0; i < sizeof(buttons) / sizeof(buttons[0]); ++i) {
            if (gpio_get_level(buttons[i].pin) == 0) {
                pressed_pin = buttons[i].pin;
                pressed_button = &buttons[i];
                break;
            }
        }

        if (pressed_button != NULL && pressed_pin != last_pressed_pin) {
            ESP_LOGI(TAG,
                     "Button %s detected on GPIO%ld",
                     pressed_button->label,
                     (long)pressed_pin);
            ESP_ERROR_CHECK(show_word(pressed_button->label, pressed_button->x));
        }
        last_pressed_pin = pressed_pin;

        vTaskDelay(pdMS_TO_TICKS(MAIN_LOOP_DELAY_MS));
    }
}
