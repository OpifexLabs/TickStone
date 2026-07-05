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

#define SEG_A (1U << 0)
#define SEG_B (1U << 1)
#define SEG_C (1U << 2)
#define SEG_D (1U << 3)
#define SEG_E (1U << 4)
#define SEG_F (1U << 5)
#define SEG_G (1U << 6)

#define SEG_7_WIDTH 9
#define SEG_7_GAP 3

#define COMPACT_DIGIT_WIDTH 3
#define COMPACT_DIGIT_HEIGHT 7
#define COMPACT_DIGIT_GAP 1
#define COMPACT_CLOCK_DOT_X 7

static spi_device_handle_t s_spi;
static uint8_t s_device_count;
static uint8_t s_rotation;
static uint8_t s_framebuffer[MAX7219_MAX_DEVICES][MAX7219_ROWS];

static uint8_t matrix_width(void);

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

static const uint8_t s_7seg_digit_mask[10] = {
    SEG_A | SEG_B | SEG_C | SEG_D | SEG_E | SEG_F,
    SEG_B | SEG_C,
    SEG_A | SEG_B | SEG_D | SEG_E | SEG_G,
    SEG_A | SEG_B | SEG_C | SEG_D | SEG_G,
    SEG_B | SEG_C | SEG_F | SEG_G,
    SEG_A | SEG_C | SEG_D | SEG_F | SEG_G,
    SEG_A | SEG_C | SEG_D | SEG_E | SEG_F | SEG_G,
    SEG_A | SEG_B | SEG_C,
    SEG_A | SEG_B | SEG_C | SEG_D | SEG_E | SEG_F | SEG_G,
    SEG_A | SEG_B | SEG_C | SEG_D | SEG_F | SEG_G,
};

static const uint8_t s_compact_digit_rows[10][COMPACT_DIGIT_HEIGHT] = {
    {0x07, 0x05, 0x05, 0x05, 0x05, 0x05, 0x07},
    {0x02, 0x06, 0x02, 0x02, 0x02, 0x02, 0x07},
    {0x07, 0x01, 0x01, 0x07, 0x04, 0x04, 0x07},
    {0x07, 0x01, 0x01, 0x07, 0x01, 0x01, 0x07},
    {0x05, 0x05, 0x05, 0x07, 0x01, 0x01, 0x01},
    {0x07, 0x04, 0x04, 0x07, 0x01, 0x01, 0x07},
    {0x07, 0x04, 0x04, 0x07, 0x05, 0x05, 0x07},
    {0x07, 0x01, 0x01, 0x02, 0x02, 0x04, 0x04},
    {0x07, 0x05, 0x05, 0x07, 0x05, 0x05, 0x07},
    {0x07, 0x05, 0x05, 0x07, 0x01, 0x01, 0x07},
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
    const uint8_t width = matrix_width();

    if (x >= width || y >= MAX7219_ROWS) {
        return;
    }

    uint8_t tx = x;
    uint8_t ty = y;

    if (width == MAX7219_ROWS) {
        switch (s_rotation) {
        case MAX7219_MATRIX_ROTATION_RIGHT_90:
            tx = MAX7219_ROWS - 1 - y;
            ty = x;
            break;
        case MAX7219_MATRIX_ROTATION_180:
            tx = width - 1 - x;
            ty = MAX7219_ROWS - 1 - y;
            break;
        case MAX7219_MATRIX_ROTATION_LEFT_90:
            tx = y;
            ty = width - 1 - x;
            break;
        case MAX7219_MATRIX_ROTATION_0:
        default:
            break;
        }
    }

    const uint8_t device = tx / MAX7219_COLS_PER_DEVICE;
    const uint8_t local_x = tx % MAX7219_COLS_PER_DEVICE;
    const uint8_t bit = 7 - local_x;

    if (on) {
        s_framebuffer[device][ty] |= (1U << bit);
    } else {
        s_framebuffer[device][ty] &= ~(1U << bit);
    }
}

static uint8_t matrix_width(void)
{
    return s_device_count * MAX7219_COLS_PER_DEVICE;
}

static void draw_horizontal_line(uint8_t x0, uint8_t x1, uint8_t y)
{
    for (uint8_t x = x0; x <= x1; ++x) {
        set_pixel(x, y, true);
    }
}

static void draw_vertical_line(uint8_t x, uint8_t y0, uint8_t y1)
{
    for (uint8_t y = y0; y <= y1; ++y) {
        set_pixel(x, y, true);
    }
}

static void draw_7seg_digit(uint8_t x, uint8_t digit)
{
    if (digit > 9) {
        return;
    }

    const uint8_t mask = s_7seg_digit_mask[digit];

    if ((mask & SEG_A) != 0) {
        draw_horizontal_line(x + 2, x + 6, 0);
    }

    if ((mask & SEG_B) != 0) {
        draw_vertical_line(x + 8, 1, 2);
    }

    if ((mask & SEG_C) != 0) {
        draw_vertical_line(x + 8, 4, 6);
    }

    if ((mask & SEG_D) != 0) {
        draw_horizontal_line(x + 2, x + 6, 7);
    }

    if ((mask & SEG_E) != 0) {
        draw_vertical_line(x, 4, 6);
    }

    if ((mask & SEG_F) != 0) {
        draw_vertical_line(x, 1, 2);
    }

    if ((mask & SEG_G) != 0) {
        draw_horizontal_line(x + 2, x + 6, 3);
    }
}

static void draw_clock_dots(uint8_t x)
{
    set_pixel(x, 2, true);
    set_pixel(x, 5, true);
}

static void draw_compact_digit(uint8_t x, uint8_t digit)
{
    if (digit > 9) {
        return;
    }

    for (uint8_t row = 0; row < COMPACT_DIGIT_HEIGHT; ++row) {
        const uint8_t row_bits = s_compact_digit_rows[digit][row];
        for (uint8_t col = 0; col < COMPACT_DIGIT_WIDTH; ++col) {
            const bool on = (row_bits & (1U << (COMPACT_DIGIT_WIDTH - 1 - col))) != 0;
            set_pixel(x + col, row, on);
        }
    }
}

static void draw_compact_clock_dots(bool dots_on)
{
    set_pixel(COMPACT_CLOCK_DOT_X, 2, dots_on);
    set_pixel(COMPACT_CLOCK_DOT_X, 5, dots_on);
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
    s_rotation = config->rotation;

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

esp_err_t max7219_matrix_set_display_test(bool enabled)
{
    return write_all_devices(REG_DISPLAY_TEST, enabled ? 0x01 : 0x00);
}

esp_err_t max7219_matrix_fill(bool on)
{
    memset(s_framebuffer, on ? 0xFF : 0x00, sizeof(s_framebuffer));
    return push_framebuffer();
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

esp_err_t max7219_matrix_draw_7seg_2_digit(uint8_t value, bool leading_zero)
{
    return max7219_matrix_draw_7seg_2_digit_clock(value, leading_zero, false);
}

esp_err_t max7219_matrix_draw_7seg_2_digit_clock(uint8_t value, bool leading_zero, bool dots_on)
{
    if (value > 99) {
        value = 99;
    }

    const uint8_t width = matrix_width();
    const uint8_t large_total_width = (SEG_7_WIDTH * 2) + SEG_7_GAP;
    const uint8_t compact_total_width = (COMPACT_DIGIT_WIDTH * 2) + COMPACT_DIGIT_GAP;

    if (width < compact_total_width) {
        return ESP_ERR_INVALID_SIZE;
    }

    memset(s_framebuffer, 0, sizeof(s_framebuffer));

    const uint8_t tens = value / 10;
    const uint8_t ones = value % 10;

    if (width >= large_total_width) {
        uint8_t x = (width - large_total_width) / 2;
        if (leading_zero || tens > 0) {
            draw_7seg_digit(x, tens);
        }

        if (dots_on) {
            draw_clock_dots(x + SEG_7_WIDTH + (SEG_7_GAP / 2));
        }

        x += SEG_7_WIDTH + SEG_7_GAP;
        draw_7seg_digit(x, ones);
    } else {
        uint8_t x = (width - compact_total_width) / 2;
        if (leading_zero || tens > 0) {
            draw_compact_digit(x, tens);
            x += COMPACT_DIGIT_WIDTH + COMPACT_DIGIT_GAP;
        } else {
            x = (width - COMPACT_DIGIT_WIDTH) / 2;
        }

        draw_compact_digit(x, ones);

        if (width > COMPACT_CLOCK_DOT_X) {
            draw_compact_clock_dots(dots_on);
        }
    }

    return push_framebuffer();
}
