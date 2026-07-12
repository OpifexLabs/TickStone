# Rich Habit Detail Workspace Implementation Plan

> **For Hermes:** Implement with strict RED–GREEN–REFACTOR, preserving the dashboard's read-only SQLite contract and the user's reference-image hierarchy.

**Goal:** Rebuild habit detail as a calm, information-rich 1800 px workspace with above-fold status, fair comparisons, milestone, KPI row, multi-granularity development chart, records, patterns, habit heatmap, and grouped history—without goal semantics.

**Architecture:** Extend `build_habit_detail` with one semantic-identity-filtered read model. Aggregate active events as-of now into daily/weekly/monthly chart modes, historical records, evidence-gated patterns, calendar days, and grouped event history. Render server-side semantic HTML; use local JavaScript only for chart mode/type, calendar day inspection, and collapsible sections.

**Tech Stack:** Python 3.11, read-only SQLite, vanilla SVG/JavaScript/CSS, unittest, Firefox browser QA.

---

### Task 1: Fix workspace width contract
- Add RED CSS assertion for 1800 px and absence of 3000 px.
- Set overview and detail shells to `min(1800px, ...)`.
- Verify 1024, 1366, 1800, and 2560 viewports.

### Task 2: Build rich semantic habit detail model
- Add RED tests for fair week/month comparisons, total, active days, streaks, average per active day/session, and no goal fields/copy.
- Reuse exact snapshot identity filtering and `started_at < now`.
- Build honest type-specific labels for time and count habits.

### Task 3: Build chart modes and trend summary
- Add RED tests for day/week/month actual-value buckets.
- Return 14 daily, 8 weekly, and 12 monthly buckets.
- Compute previous-period change, 4-period direction count, best and weakest period using neutral copy.
- Render local SVG with bar/line controls and Dag/Vecka/Månad controls; no goal line.

### Task 4: Personal records and milestone
- Add RED tests for time/count-specific records, longest streak, latest record date, and strict beat-not-tie milestone.
- Render a compact record list, never oversized record cards.
- Keep overview record highlights transient; detail records may be persistent because the user explicitly opened the habit.

### Task 5: Evidence-gated patterns
- Add RED tests for weekday, daypart, interval, weekend/weekday difference, and insufficient-data suppression.
- Require explicit sample thresholds per pattern.
- Render only grounded pattern sentences.

### Task 6: Habit calendar and day inspection
- Add RED tests for a 12-week habit-only heatmap and per-day event payload.
- Render days as keyboard-accessible buttons.
- Add a local day-detail panel showing total, sessions, times, and source when known.
- Preserve read-only safety: editing/deletion controls explain that corrections are unavailable in this read-only view rather than mutating canonical logs.

### Task 7: Grouped log history
- Add RED tests for descending day groups, collapsed-by-default details, exact time/value/source, and escaped metadata.
- Use `<details>`/`<summary>` for native keyboard behavior and mobile collapse.

### Task 8: Visual implementation and release
- Match the reference: warm paper, subtle borders, green accent, compact icon circles, three-part hero, four KPI strip, wide chart/records split, three lower cards.
- Responsive collapse records/patterns/history on smaller screens.
- Run all tests, compile, diff, systemd, browser, LAN/Tailscale, and recovery gates.
- Merge locally with explicit Opifex noreply identity, push, deploy, and verify raw GitHub metadata.
