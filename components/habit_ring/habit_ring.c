#include "habit_ring.h"
#include <stdlib.h>
#include <string.h>

static int compare_id(const void *left, const void *right)
{
    const habit_log_t *a = left, *b = right;
    return a->id < b->id ? -1 : a->id > b->id ? 1 : 0;
}

size_t habit_ring_select_contiguous(habit_log_t *logs, size_t count)
{
    if (!logs || !count) return 0;
    qsort(logs, count, sizeof(logs[0]), compare_id);
    size_t best_start = 0, best_count = 1, run_start = 0;
    for (size_t i = 1; i <= count; ++i) {
        if (i < count && logs[i].id == logs[i - 1].id + 1) continue;
        size_t run_count = i - run_start;
        if (run_count > best_count ||
            (run_count == best_count && logs[i - 1].id > logs[best_start + best_count - 1].id)) {
            best_start = run_start; best_count = run_count;
        }
        run_start = i;
    }
    if (best_start) memmove(logs, &logs[best_start], best_count * sizeof(logs[0]));
    return best_count;
}
