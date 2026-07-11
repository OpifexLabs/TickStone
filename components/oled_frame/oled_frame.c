#include "oled_frame.h"
#include <string.h>

static uint32_t hash_page(const uint8_t *data)
{
    uint32_t hash = 2166136261u;
    for (size_t i = 0; i < OLED_FRAME_WIDTH; ++i) hash = (hash ^ data[i]) * 16777619u;
    return hash;
}

void oled_frame_init(oled_frame_t *frame) { if (frame) memset(frame, 0, sizeof(*frame)); }
void oled_frame_clear(oled_frame_t *frame) { if (frame) memset(frame->pixels, 0, sizeof(frame->pixels)); }
void oled_frame_invalidate(oled_frame_t *frame)
{
    if (frame) memset(frame->presented, 0, sizeof(frame->presented));
}

const uint8_t *oled_frame_page_const(const oled_frame_t *frame, uint8_t page)
{
    return !frame || page >= OLED_FRAME_PAGES ? NULL : &frame->pixels[page * OLED_FRAME_WIDTH];
}

uint8_t *oled_frame_page(oled_frame_t *frame, uint8_t page)
{
    return (uint8_t *)oled_frame_page_const(frame, page);
}

bool oled_frame_page_changed(const oled_frame_t *frame, uint8_t page)
{
    const uint8_t *data = oled_frame_page_const(frame, page);
    return data && (!frame->presented[page] || frame->presented_hash[page] != hash_page(data));
}

void oled_frame_page_presented(oled_frame_t *frame, uint8_t page)
{
    const uint8_t *data = oled_frame_page_const(frame, page);
    if (!data) return;
    frame->presented_hash[page] = hash_page(data); frame->presented[page] = true;
}
