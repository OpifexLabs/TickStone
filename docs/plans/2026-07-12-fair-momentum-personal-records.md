# Fair Momentum, Comparisons, and Personal Records Implementation Plan

> **For Hermes:** Execute this plan with strict RED–GREEN–REFACTOR and review each behavior against real 1024×768 and wide-screen browser output.

**Goal:** Expand the local TickStone dashboard to a 3000 px canvas, add fair week/month habit comparisons, choose a time-aligned momentum KPI, and surface relevant milestones or newly broken personal records without a permanent record panel.

**Architecture:** Add one read-only intelligence model built from canonical events and active habit identities. It computes elapsed-period comparisons using TickStone-local 05:00 boundaries, historical weekly/daily/session records, transient record events, milestone gaps, and ranked momentum candidates. The overview model consumes these fields; rendering remains server-side HTML plus local CSS.

**Tech Stack:** Python 3.11, SQLite read-only queries, standard-library datetime/zoneinfo, vanilla HTML/CSS, unittest, Firefox/browser QA.

---

### Task 1: Encode fair elapsed-period boundaries

**Files:**
- Modify: `tests/tickstone_dashboard_test.py`
- Modify: `tools/tickstone_dashboard.py`

1. Add RED tests for current week/month cutoff versus the equivalent prior local period cutoff.
2. Cover Monday partial-week behavior, month-to-date behavior, 05:00 TickStone day boundary, and zero baselines.
3. Implement local logical-time boundary helpers without assuming fixed UTC offsets.
4. Verify focused GREEN.

### Task 2: Add per-habit week/month comparisons

**Files:**
- Modify: `tests/tickstone_dashboard_test.py`
- Modify: `tools/tickstone_dashboard.py`

1. Add RED assertions for `V: +N%` and `M: -N%`, independent tones, and `Ny`/`0%` zero-baseline states.
2. Aggregate each habit using its honest unit: count values for count habits and duration seconds for time habits.
3. Attach `comparisons.week` and `comparisons.month` to each habit row.
4. Render two independently colored comparison fragments.

### Task 3: Add fair momentum ranking

**Files:**
- Modify: `tests/tickstone_dashboard_test.py`
- Modify: `tools/tickstone_dashboard.py`

1. Add RED tests proving current week is compared only with the previous week up to the same local weekday/time.
2. Add candidates for log delta, active-day delta, habit growth, and best equivalent partial week in the last month.
3. Rank only positive candidates deterministically; provide a neutral fallback.
4. Replace the static trend KPI with `På väg upp` or `Veckans vinst` and grounded detail copy.

### Task 4: Compute personal records and milestones

**Files:**
- Modify: `tests/tickstone_dashboard_test.py`
- Modify: `tools/tickstone_dashboard.py`

1. Add RED tests for longest streak, best week, most count value in one day, longest time session, and highest weekly time total.
2. Require a prior comparable baseline before declaring a new record.
3. Detect records broken during the current TickStone week.
4. Compute the closest positive gap to a prior best weekly habit total.
5. Expose deterministic record and milestone insight objects.

### Task 5: Render transient record/milestone insights

**Files:**
- Modify: `tests/tickstone_dashboard_test.py`
- Modify: `tools/tickstone_dashboard.py`
- Modify: `tools/tickstone_dashboard_web/styles.css`

1. Add RED markup/CSS tests for transient `.record-insight` and `.milestone-insight` states.
2. Show records only when newly broken/relevant; do not add a permanent record panel.
3. Add a restrained accent and one-shot reduced-motion-safe animation.
4. Preserve the ordinary weekday/leader insights as fallback content.

### Task 6: Expand and verify the layout

**Files:**
- Modify: `tests/tickstone_dashboard_test.py`
- Modify: `tools/tickstone_dashboard_web/styles.css`
- Modify: `README.md`

1. Add RED assertion for `3000px` workspace maximum.
2. Change both normal and desktop workspace limits from 1240 px to 3000 px.
3. Browser-QA at 1024×768, 1366×1024, and a wide 2560×1440 viewport.
4. Verify no clipping in the richer comparison column.

### Task 7: Release gate

1. Run 23+ dashboard tests and the full host suite.
2. Run compile, diff, and all TickStone systemd unit verification.
3. Review the final diff for read-only behavior, DST/calendar correctness, escaping, and deterministic ranking.
4. Commit with the Opifex noreply identity, push, merge, restart production.
5. Verify LAN/Tailscale health, exact viewport screenshots, browser console, fair comparison copy, record/milestone conditionality, and systemd restart recovery.

## Post-merge review hardening

The independent review gate additionally requires:

- baselines partitioned by versionslagrad habit identity and type
- inactive and future events excluded consistently
- milestones measured to the first value that beats, not ties, the record
- truthful decline copy when no positive momentum exists
- current-week intelligence shown only on the current week view
- normalized deterministic momentum ranking
- measured overview latency and full-history performance monitoring
