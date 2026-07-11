#include "habit_legacy.h"
#include <assert.h>
#include <stdio.h>

int main(void)
{
    assert(sizeof(habit_legacy_log_t) == 32 && sizeof(habit_legacy_session_t) == 40);
    habit_legacy_log_t old = {.habit_id=4, .type=HABIT_TYPE_TIME, .start=100, .end=161,
        .duration=60, .count=2, .synced=1, .deleted=0};
    habit_log_t log; assert(habit_legacy_convert_log(&old, 9, &log));
    assert(log.id == 9 && log.habit_id == 4 && log.duration_seconds == 60 && log.synced);
    old.type = 99; assert(!habit_legacy_convert_log(&old, 10, &log));
    habit_legacy_session_blob_t session = {.version=1, .session={.active=1, .paused=1,
        .habit_id=2, .mode=HABIT_TIME_TIMER, .start=50, .paused_at=55, .paused_total=3,
        .timer_seconds=600, .setup_minutes=10}};
    habit_session_snapshot_t snapshot; assert(habit_legacy_convert_session(&session, &snapshot));
    assert(snapshot.session_active && snapshot.session_paused && snapshot.timer_seconds == 600);
    session.version = 2; assert(!habit_legacy_convert_session(&session, &snapshot));
    puts("habit_legacy_test: OK");
    return 0;
}
