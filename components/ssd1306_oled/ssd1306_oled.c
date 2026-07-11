#include "ssd1306_oled.h"

#include <string.h>

#include "driver/i2c.h"
#include "esp_check.h"
#include "esp_err.h"
#include "oled_frame.h"

#define OLED_I2C_PORT I2C_NUM_0
#define OLED_I2C_FREQ_HZ 100000
#define OLED_CONTROL_COMMAND 0x00
#define OLED_CONTROL_DATA 0x40
#define OLED_WIDTH 128
#define OLED_PAGES 16
#define OLED_DEFAULT_ADDRESS 0x3C
#define OLED_LOG_TAG "sh1107"

static uint8_t s_address = OLED_DEFAULT_ADDRESS;
static bool s_driver_installed;
static oled_frame_t s_frame;

static const uint8_t s_font_5x7[][5] = {
    [' '] = {0x00, 0x00, 0x00, 0x00, 0x00},
    ['+'] = {0x08, 0x08, 0x3E, 0x08, 0x08},
    ['-'] = {0x08, 0x08, 0x08, 0x08, 0x08},
    ['0'] = {0x3E, 0x51, 0x49, 0x45, 0x3E},
    ['1'] = {0x00, 0x42, 0x7F, 0x40, 0x00},
    ['2'] = {0x42, 0x61, 0x51, 0x49, 0x46},
    ['3'] = {0x21, 0x41, 0x45, 0x4B, 0x31},
    ['4'] = {0x18, 0x14, 0x12, 0x7F, 0x10},
    ['5'] = {0x27, 0x45, 0x45, 0x45, 0x39},
    ['6'] = {0x3C, 0x4A, 0x49, 0x49, 0x30},
    ['7'] = {0x01, 0x71, 0x09, 0x05, 0x03},
    ['8'] = {0x36, 0x49, 0x49, 0x49, 0x36},
    ['9'] = {0x06, 0x49, 0x49, 0x29, 0x1E},
    [':'] = {0x00, 0x36, 0x36, 0x00, 0x00},
    ['<'] = {0x08, 0x14, 0x22, 0x41, 0x00},
    ['>'] = {0x00, 0x41, 0x22, 0x14, 0x08},
    ['@'] = {0x1C, 0x22, 0x2E, 0x2A, 0x1C},
    ['A'] = {0x7E, 0x11, 0x11, 0x11, 0x7E},
    ['B'] = {0x7F, 0x49, 0x49, 0x49, 0x36},
    ['C'] = {0x3E, 0x41, 0x41, 0x41, 0x22},
    ['D'] = {0x7F, 0x41, 0x41, 0x22, 0x1C},
    ['E'] = {0x7F, 0x49, 0x49, 0x49, 0x41},
    ['F'] = {0x7F, 0x09, 0x09, 0x09, 0x01},
    ['G'] = {0x3E, 0x41, 0x49, 0x49, 0x7A},
    ['H'] = {0x7F, 0x08, 0x08, 0x08, 0x7F},
    ['I'] = {0x00, 0x41, 0x7F, 0x41, 0x00},
    ['J'] = {0x20, 0x40, 0x41, 0x3F, 0x01},
    ['K'] = {0x7F, 0x08, 0x14, 0x22, 0x41},
    ['L'] = {0x7F, 0x40, 0x40, 0x40, 0x40},
    ['M'] = {0x7F, 0x02, 0x0C, 0x02, 0x7F},
    ['N'] = {0x7F, 0x04, 0x08, 0x10, 0x7F},
    ['O'] = {0x3E, 0x41, 0x41, 0x41, 0x3E},
    ['P'] = {0x7F, 0x09, 0x09, 0x09, 0x06},
    ['Q'] = {0x3E, 0x41, 0x51, 0x21, 0x5E},
    ['R'] = {0x7F, 0x09, 0x19, 0x29, 0x46},
    ['S'] = {0x46, 0x49, 0x49, 0x49, 0x31},
    ['T'] = {0x01, 0x01, 0x7F, 0x01, 0x01},
    ['U'] = {0x3F, 0x40, 0x40, 0x40, 0x3F},
    ['V'] = {0x1F, 0x20, 0x40, 0x20, 0x1F},
    ['W'] = {0x3F, 0x40, 0x38, 0x40, 0x3F},
    ['X'] = {0x63, 0x14, 0x08, 0x14, 0x63},
    ['Y'] = {0x07, 0x08, 0x70, 0x08, 0x07},
    ['Z'] = {0x61, 0x51, 0x49, 0x45, 0x43},
    ['a'] = {0x20, 0x54, 0x54, 0x54, 0x78},
    ['b'] = {0x7F, 0x48, 0x44, 0x44, 0x38},
    ['d'] = {0x38, 0x44, 0x44, 0x48, 0x7F},
    ['e'] = {0x38, 0x54, 0x54, 0x54, 0x18},
    ['h'] = {0x7F, 0x08, 0x04, 0x04, 0x78},
    ['j'] = {0x20, 0x40, 0x44, 0x3D, 0x00},
    ['l'] = {0x00, 0x41, 0x7F, 0x40, 0x00},
    ['o'] = {0x38, 0x44, 0x44, 0x44, 0x38},
    ['r'] = {0x7C, 0x08, 0x04, 0x04, 0x08},
    ['u'] = {0x3C, 0x40, 0x40, 0x20, 0x7C},
    ['w'] = {0x3C, 0x40, 0x30, 0x40, 0x3C},
    ['y'] = {0x0C, 0x50, 0x50, 0x50, 0x3C},
};

static esp_err_t write_bytes(uint8_t control, const uint8_t *data, size_t data_len)
{
    uint8_t buffer[OLED_WIDTH + 1] = {0};

    if (data_len > OLED_WIDTH) {
        return ESP_ERR_INVALID_SIZE;
    }

    buffer[0] = control;
    memcpy(&buffer[1], data, data_len);

    return i2c_master_write_to_device(OLED_I2C_PORT,
                                      s_address,
                                      buffer,
                                      data_len + 1,
                                      pdMS_TO_TICKS(100));
}

static esp_err_t command(uint8_t cmd)
{
    return write_bytes(OLED_CONTROL_COMMAND, &cmd, 1);
}

static esp_err_t probe_address(uint8_t address)
{
    i2c_cmd_handle_t cmd = i2c_cmd_link_create();
    if (cmd == NULL) {
        return ESP_ERR_NO_MEM;
    }

    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, (address << 1) | I2C_MASTER_WRITE, true);
    i2c_master_stop(cmd);
    esp_err_t err = i2c_master_cmd_begin(OLED_I2C_PORT, cmd, pdMS_TO_TICKS(100));
    i2c_cmd_link_delete(cmd);

    return err;
}

static esp_err_t set_cursor(uint8_t x, uint8_t page)
{
    if (x >= OLED_WIDTH || page >= OLED_PAGES) {
        return ESP_ERR_INVALID_ARG;
    }

    ESP_RETURN_ON_ERROR(command(0xB0 | page), OLED_LOG_TAG, "set page failed");
    ESP_RETURN_ON_ERROR(command(0x00 | (x & 0x0F)), OLED_LOG_TAG, "set low col failed");
    return command(0x10 | (x >> 4));
}

esp_err_t ssd1306_oled_init(const ssd1306_oled_config_t *config)
{
    if (config == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    i2c_config_t i2c_config = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = config->sda_pin,
        .scl_io_num = config->scl_pin,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = OLED_I2C_FREQ_HZ,
        .clk_flags = 0,
    };

    if (s_driver_installed) {
        ESP_RETURN_ON_ERROR(i2c_driver_delete(OLED_I2C_PORT),
                            OLED_LOG_TAG,
                            "delete old i2c driver failed");
        s_driver_installed = false;
    }

    esp_err_t err = i2c_param_config(OLED_I2C_PORT, &i2c_config);
    if (err != ESP_OK) {
        return err;
    }

    err = i2c_driver_install(OLED_I2C_PORT, I2C_MODE_MASTER, 0, 0, 0);
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        return err;
    }
    s_driver_installed = true;

    if (config->address != 0) {
        s_address = config->address;
    } else if (probe_address(0x3C) == ESP_OK) {
        s_address = 0x3C;
    } else if (probe_address(0x3D) == ESP_OK) {
        s_address = 0x3D;
    } else {
        return ESP_ERR_NOT_FOUND;
    }

    static const uint8_t init_commands[] = {
        0xAE,       // Display off
        0xD5, 0x50, // Clock
        0xA8, 0x7F, // Multiplex for 128x128
        0xD3, 0x00, // Display offset
        0x40,       // Start line
        0xAD, 0x8B, // SH1107 DC-DC on
        0xA1,       // Segment remap
        0xC8,       // COM scan direction
        0xDA, 0x12, // COM pins
        0x81, 0x80, // Contrast
        0xD9, 0x22, // Pre-charge
        0xDB, 0x35, // VCOM deselect
        0xA4,       // Resume RAM display
        0xA6,       // Normal display
        0xAF,       // Display on
    };

    for (size_t i = 0; i < sizeof(init_commands); ++i) {
        ESP_RETURN_ON_ERROR(command(init_commands[i]), OLED_LOG_TAG, "init command failed");
    }

    oled_frame_init(&s_frame);
    ESP_RETURN_ON_ERROR(ssd1306_oled_clear(), OLED_LOG_TAG, "initial clear failed");
    return ssd1306_oled_present();
}

esp_err_t ssd1306_oled_set_contrast(uint8_t contrast)
{
    ESP_RETURN_ON_ERROR(command(0x81), OLED_LOG_TAG, "contrast command failed");
    return command(contrast);
}

esp_err_t ssd1306_oled_set_enabled(bool enabled)
{
    return command(enabled ? 0xAF : 0xAE);
}

esp_err_t ssd1306_oled_restore_controller(void)
{
    static const uint8_t restore_commands[] = {
        0xA8, 0x7F, // 128 rows
        0xD3, 0x00, // No display offset
        0x40,       // Start at row zero
        0xA1,       // Segment orientation
        0xC8,       // COM scan orientation
        0xDA, 0x12, // COM layout
        0xA4,       // Display framebuffer
        0xA6,       // Normal, not inverted
        0xAF,       // Display on
    };
    for (size_t i = 0; i < sizeof(restore_commands); ++i) {
        ESP_RETURN_ON_ERROR(command(restore_commands[i]), OLED_LOG_TAG, "restore command failed");
    }
    oled_frame_invalidate(&s_frame);
    return ESP_OK;
}

esp_err_t ssd1306_oled_clear(void)
{
    oled_frame_clear(&s_frame);
    return ESP_OK;
}

esp_err_t ssd1306_oled_present(void)
{
    for (uint8_t page = 0; page < OLED_PAGES; ++page) {
        const uint8_t *data = oled_frame_page_const(&s_frame, page);
        if (!oled_frame_page_changed(&s_frame, page)) continue;
        ESP_RETURN_ON_ERROR(set_cursor(0, page), OLED_LOG_TAG, "clear cursor failed");
        ESP_RETURN_ON_ERROR(write_bytes(OLED_CONTROL_DATA, data, OLED_WIDTH),
                            OLED_LOG_TAG,
                            "frame page failed");
        oled_frame_page_presented(&s_frame, page);
    }
    return ESP_OK;
}

esp_err_t ssd1306_oled_draw_text(uint8_t x, uint8_t page, const char *text)
{
    if (text == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    while (*text != '\0' && x < OLED_WIDTH) {
        const unsigned char c = (unsigned char)*text++;
        const uint8_t *glyph = s_font_5x7[' '];

        if (c < sizeof(s_font_5x7) / sizeof(s_font_5x7[0]) &&
            memcmp(s_font_5x7[c], s_font_5x7[' '], 5) != 0) {
            glyph = s_font_5x7[c];
        }

        uint8_t columns[6] = {
            glyph[0],
            glyph[1],
            glyph[2],
            glyph[3],
            glyph[4],
            0x00,
        };

        size_t write_len = x + sizeof(columns) <= OLED_WIDTH ? sizeof(columns) : OLED_WIDTH - x;
        memcpy(oled_frame_page(&s_frame, page) + x, columns, write_len);
        x += sizeof(columns);
    }

    return ESP_OK;
}

esp_err_t ssd1306_oled_draw_text_2x(uint8_t x, uint8_t page, const char *text)
{
    if (text == NULL || page + 1 >= OLED_PAGES) {
        return ESP_ERR_INVALID_ARG;
    }

    while (*text != '\0' && x < OLED_WIDTH) {
        const unsigned char c = (unsigned char)*text++;
        const uint8_t *glyph = s_font_5x7[' '];

        if (c < sizeof(s_font_5x7) / sizeof(s_font_5x7[0]) &&
            memcmp(s_font_5x7[c], s_font_5x7[' '], 5) != 0) {
            glyph = s_font_5x7[c];
        }

        uint8_t scaled[2][12] = {0};

        for (uint8_t source_x = 0; source_x < 6; ++source_x) {
            const uint8_t column = source_x < 5 ? glyph[source_x] : 0x00;

            for (uint8_t source_y = 0; source_y < 7; ++source_y) {
                if ((column & BIT(source_y)) == 0) {
                    continue;
                }

                const uint8_t target_y = source_y * 2;
                const uint8_t target_page = target_y / 8;
                const uint8_t target_bit = target_y % 8;
                const uint8_t target_x = source_x * 2;

                scaled[target_page][target_x] |= BIT(target_bit);
                scaled[target_page][target_x] |= BIT(target_bit + 1);
                scaled[target_page][target_x + 1] |= BIT(target_bit);
                scaled[target_page][target_x + 1] |= BIT(target_bit + 1);
            }
        }

        const uint8_t write_len = (x + sizeof(scaled[0]) <= OLED_WIDTH) ?
                                  sizeof(scaled[0]) :
                                  (OLED_WIDTH - x);

        memcpy(oled_frame_page(&s_frame, page) + x, scaled[0], write_len);
        memcpy(oled_frame_page(&s_frame, page + 1) + x, scaled[1], write_len);

        x += sizeof(scaled[0]);
    }

    return ESP_OK;
}

esp_err_t ssd1306_oled_draw_bitmap_8x8(uint8_t x, uint8_t page, const uint8_t rows[8])
{
    if (rows == NULL || page >= OLED_PAGES || x + 8 > OLED_WIDTH) {
        return ESP_ERR_INVALID_ARG;
    }

    uint8_t columns[8] = {0};
    for (uint8_t source_y = 0; source_y < 8; ++source_y) {
        for (uint8_t source_x = 0; source_x < 8; ++source_x) {
            if ((rows[source_y] & BIT(7 - source_x)) != 0) {
                columns[source_x] |= BIT(source_y);
            }
        }
    }

    memcpy(oled_frame_page(&s_frame, page) + x, columns, sizeof(columns));
    return ESP_OK;
}

esp_err_t ssd1306_oled_draw_bitmap_8x8_2x(uint8_t x, uint8_t page, const uint8_t rows[8])
{
    if (rows == NULL || page + 1 >= OLED_PAGES || x + 16 > OLED_WIDTH) {
        return ESP_ERR_INVALID_ARG;
    }

    uint8_t scaled[2][16] = {0};
    for (uint8_t source_y = 0; source_y < 8; ++source_y) {
        for (uint8_t source_x = 0; source_x < 8; ++source_x) {
            if ((rows[source_y] & BIT(7 - source_x)) == 0) {
                continue;
            }

            const uint8_t target_x = source_x * 2;
            const uint8_t target_y = source_y * 2;
            const uint8_t target_page = target_y / 8;
            const uint8_t target_bit = target_y % 8;
            scaled[target_page][target_x] |= BIT(target_bit) | BIT(target_bit + 1);
            scaled[target_page][target_x + 1] |= BIT(target_bit) | BIT(target_bit + 1);
        }
    }

    memcpy(oled_frame_page(&s_frame, page) + x, scaled[0], sizeof(scaled[0]));
    memcpy(oled_frame_page(&s_frame, page + 1) + x, scaled[1], sizeof(scaled[1]));
    return ESP_OK;
}
