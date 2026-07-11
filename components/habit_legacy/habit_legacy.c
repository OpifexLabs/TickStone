#include "habit_legacy.h"

_Static_assert(sizeof(habit_legacy_log_t) == 32, "legacy log ABI mismatch");
_Static_assert(sizeof(habit_legacy_session_t) == 40, "legacy session ABI mismatch");

bool habit_legacy_convert_log(const habit_legacy_log_t *old, uint64_t id, habit_log_t *out)
{
    if (!old || !out || !id || (old->type != HABIT_TYPE_COUNT && old->type != HABIT_TYPE_TIME)) return false;
    *out = (habit_log_t){.id=id, .habit_id=old->habit_id, .type=(habit_type_t)old->type,
        .timestamp_start=old->start, .timestamp_end=old->end, .duration_seconds=old->duration,
        .count_value=old->count, .synced=old->synced != 0, .deleted=old->deleted != 0};
    return true;
}

bool habit_legacy_convert_session(const habit_legacy_session_blob_t *old, habit_session_snapshot_t *out)
{
    if (!old || !out || old->version != 1 ||
        (old->session.mode != HABIT_TIME_TIMER && old->session.mode != HABIT_TIME_STOPWATCH)) return false;
    *out = (habit_session_snapshot_t){.session_active=old->session.active != 0,
        .session_paused=old->session.paused != 0, .selected_habit_id=old->session.habit_id,
        .time_mode=(habit_time_mode_t)old->session.mode, .session_start=old->session.start,
        .session_paused_at=old->session.paused_at, .session_paused_total=old->session.paused_total,
        .timer_seconds=old->session.timer_seconds, .setup_minutes=old->session.setup_minutes};
    return true;
}
