#include "oled_frame.h"
#include <assert.h>
#include <stdio.h>

static int changed(oled_frame_t *frame)
{
    int count = 0;
    for (int page = 0; page < OLED_FRAME_PAGES; ++page) if (oled_frame_page_changed(frame, page)) ++count;
    return count;
}

static void present(oled_frame_t *frame)
{
    for (int page = 0; page < OLED_FRAME_PAGES; ++page) if (oled_frame_page_changed(frame, page)) oled_frame_page_presented(frame, page);
}

int main(void)
{
    oled_frame_t frame; oled_frame_init(&frame);
    assert(sizeof(frame.pixels) == 2048 && changed(&frame) == 16);
    present(&frame); assert(changed(&frame) == 0);
    oled_frame_page(&frame, 7)[42] = 1; assert(changed(&frame) == 1);
    present(&frame); assert(changed(&frame) == 0);
    oled_frame_clear(&frame); assert(changed(&frame) == 1);
    puts("oled_frame_test: OK");
    return 0;
}
