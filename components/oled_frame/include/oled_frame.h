#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define OLED_FRAME_WIDTH 128
#define OLED_FRAME_PAGES 16
#define OLED_FRAME_SIZE (OLED_FRAME_WIDTH * OLED_FRAME_PAGES)

typedef struct {
    uint8_t pixels[OLED_FRAME_SIZE];
    uint32_t presented_hash[OLED_FRAME_PAGES];
    bool presented[OLED_FRAME_PAGES];
} oled_frame_t;

void oled_frame_init(oled_frame_t *frame);
void oled_frame_clear(oled_frame_t *frame);
bool oled_frame_page_changed(const oled_frame_t *frame, uint8_t page);
void oled_frame_page_presented(oled_frame_t *frame, uint8_t page);
uint8_t *oled_frame_page(oled_frame_t *frame, uint8_t page);
const uint8_t *oled_frame_page_const(const oled_frame_t *frame, uint8_t page);
