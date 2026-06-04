#include "max7219_matrix.h"

#include <stdbool.h>
#include <string.h>

#define MAX7219_MAX_DEVICES 8
#define MAX7219_ROWS 8
#define MAX7219_COLS_PER_DEVICE 8

#define REG_NO_OP 0x00
#define REG_DIGIT_0 0x01
#define REG_DECODE_MODE 0x09
#define REG_INTENSITY 0x0A
#define REG_SCAN_LIMIT 0x0B
#define REG_SHUTDOWN 0x0C
#define REG_DISPLAY_TEST 0x0F

static spi_device_handle_t s_spi;
static uint8_t s_device_count;
static uint8_t s_framebuffer[MAX7219_MAX_DEVICES][MAX7219_ROWS];

static const uint8_t s_digit_font_5x7[10][5] = {
    {0x3E, 0x51, 0x49, 0x45, 0x3E},
    {0x00, 0x42, 0x7F, 0x40, 0x00},
    {0x62, 0x51, 0x49, 0x49, 0x46},
    {0x22, 0x49, 0x49, 0x49, 0x36},
    {0x18, 0x14, 0x12, 0x7F, 0x10},
    {0x2F, 0x49, 0x49, 0x49, 0x31},
    {0x3E, 0x49, 0x49, 0x49, 0x32},
    {0x01, 0x71, 0x09, 0x05, 0x03},
    {0x36, 0x49, 0x49, 0x49, 0x36},
    {0x26, 0x49, 0x49, 0x49, 0x3E},
};

static esp_err_t write_all_devices(uint8_t reg, uint8_t data)
{
    uint8_t tx[MAX7219_MAX_DEVICES * 2] = {0};

    for (uint8_t i = 0; i < s_device_count; ++i) {
        tx[i * 2] = reg;
        tx[i * 2 + 1] = data;
    }

    spi_transaction_t transaction = {
        .length = s_device_count * 16,
        .tx_buffer = tx,
    };

    return spi_device_transmit(s_spi, &transaction);
}

static esp_err_t push_framebuffer(void)
{
    uint8_t tx[MAX7219_MAX_DEVICES * 2] = {0};

    for (uint8_t row = 0; row < MAX7219_ROWS; ++row) {
        for (uint8_t device = 0; device < s_device_count; ++device) {
            tx[device * 2] = REG_DIGIT_0 + row;
            tx[device * 2 + 1] = s_framebuffer[s_device_count - 1 - device][row];
        }

        spi_transaction_t transaction = {
            .length = s_device_count * 16,
            .tx_buffer = tx,
        };

        esp_err_t err = spi_device_transmit(s_spi, &transaction);
        if (err != ESP_OK) {
            return err;
        }
    }

    return ESP_OK;
}

static void set_pixel(uint8_t x, uint8_t y, bool on)
{
    if (x >= s_device_count * MAX7219_COLS_PER_DEVICE || y >= MAX7219_ROWS) {
        return;
    }

    const uint8_t device = x / MAX7219_COLS_PER_DEVICE;
    const uint8_t local_x = x % MAX7219_COLS_PER_DEVICE;
    const uint8_t bit = 7 - local_x;

    if (on) {
        s_framebuffer[device][y] |= (1U << bit);
    } else {
        s_framebuffer[device][y] &= ~(1U << bit);
    }
}

static void draw_digit(uint8_t x, uint8_t digit)
{
    if (digit > 9) {
        return;
    }

    for (uint8_t col = 0; col < 5; ++col) {
        const uint8_t column_bits = s_digit_font_5x7[digit][col];

        for (uint8_t row = 0; row < 7; ++row) {
            set_pixel(x + col, row, (column_bits & (1U << row)) != 0);
        }
    }
}

static void draw_colon(uint8_t x)
{
    set_pixel(x, 2, true);
    set_pixel(x, 4, true);
}

esp_err_t max7219_matrix_init(const max7219_matrix_config_t *config)
{
    if (config == NULL ||
        config->device_count == 0 ||
        config->device_count > MAX7219_MAX_DEVICES) {
        return ESP_ERR_INVALID_ARG;
    }

    s_device_count = config->device_count;

    spi_bus_config_t bus_config = {
        .mosi_io_num = config->mosi_pin,
        .miso_io_num = -1,
        .sclk_io_num = config->clk_pin,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = MAX7219_MAX_DEVICES * 2,
    };

    esp_err_t err = spi_bus_initialize(config->host, &bus_config, SPI_DMA_DISABLED);
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        return err;
    }

    spi_device_interface_config_t device_config = {
        .clock_speed_hz = 1000000,
        .mode = 0,
        .spics_io_num = config->cs_pin,
        .queue_size = 1,
    };

    err = spi_bus_add_device(config->host, &device_config, &s_spi);
    if (err != ESP_OK) {
        return err;
    }

    err = write_all_devices(REG_DISPLAY_TEST, 0x00);
    if (err != ESP_OK) {
        return err;
    }

    err = write_all_devices(REG_DECODE_MODE, 0x00);
    if (err != ESP_OK) {
        return err;
    }

    err = write_all_devices(REG_SCAN_LIMIT, 0x07);
    if (err != ESP_OK) {
        return err;
    }

    err = max7219_matrix_set_intensity(config->intensity);
    if (err != ESP_OK) {
        return err;
    }

    err = write_all_devices(REG_SHUTDOWN, 0x01);
    if (err != ESP_OK) {
        return err;
    }

    return max7219_matrix_clear();
}

esp_err_t max7219_matrix_clear(void)
{
    memset(s_framebuffer, 0, sizeof(s_framebuffer));
    return push_framebuffer();
}

esp_err_t max7219_matrix_set_intensity(uint8_t intensity)
{
    if (intensity > 0x0F) {
        intensity = 0x0F;
    }

    return write_all_devices(REG_INTENSITY, intensity);
}

esp_err_t max7219_matrix_draw_time_mm_ss(uint8_t minutes, uint8_t seconds)
{
    if (seconds > 59) {
        seconds = 59;
    }

    if (minutes > 99) {
        minutes = 99;
    }

    memset(s_framebuffer, 0, sizeof(s_framebuffer));

    uint8_t x = 3;
    draw_digit(x, minutes / 10);
    x += 6;
    draw_digit(x, minutes % 10);
    x += 6;
    draw_colon(x);
    x += 2;
    draw_digit(x, seconds / 10);
    x += 6;
    draw_digit(x, seconds % 10);

    return push_framebuffer();
}
