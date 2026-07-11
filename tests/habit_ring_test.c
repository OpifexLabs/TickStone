#include "habit_ring.h"
#include <assert.h>
#include <stdio.h>

int main(void)
{
    habit_log_t after_slot_write[] = {{.id=513}, {.id=2}, {.id=512}, {.id=3}};
    size_t count = habit_ring_select_contiguous(after_slot_write, 4);
    assert(count == 2 && after_slot_write[0].id == 512 && after_slot_write[1].id == 513);

    habit_log_t after_metadata_write[] = {{.id=1}, {.id=2}, {.id=4}, {.id=3}};
    count = habit_ring_select_contiguous(after_metadata_write, 4);
    assert(count == 4 && after_metadata_write[0].id == 1 && after_metadata_write[3].id == 4);

    habit_log_t competing[] = {{.id=10}, {.id=11}, {.id=100}, {.id=101}};
    count = habit_ring_select_contiguous(competing, 4);
    assert(count == 2 && competing[0].id == 100 && competing[1].id == 101);
    assert(habit_ring_select_contiguous(NULL, 0) == 0);
    puts("habit_ring_test: OK");
    return 0;
}
