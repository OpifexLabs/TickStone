# Statistics Dashboard Redesign Plan

> **For Hermes:** Execute with strict RED-GREEN-REFACTOR and real browser evidence.

**Goal:** Rebuild the local TickStone dashboard to match the supplied desktop reference: navigation rail, calendar period controls, KPI cards, normalized activity chart, habit performance table, 12-week heatmap, and grounded insights—while preserving read-only/privacy guarantees and responsive usability.

**Architecture:** Replace the overview read model with one bounded period-aware aggregate. The URL owns `period=week|month|year|all` and `offset<=0`; server-rendered HTML provides all essential content, while local vanilla JavaScript progressively enhances chart selection and mobile navigation. SQLite remains `mode=ro` + `query_only`.

**Statistics contract:**
- TickStone day remains the stored Europe/Stockholm 05:00 day.
- Count habit daily target is 1 occurrence; time habit daily target is `default_minutes * 60`, minimum one minute when metadata is missing.
- Daily/habit completion is capped at 100%; aggregate completion is achieved target units divided by possible active habit-days.
- Overview activity splits normalized count and normalized time progress. Sessions, raw counts and raw duration remain visible in habit rows/details.
- Deleted events never contribute. A zero prior baseline renders “Ny aktivitet”, never infinity.
- Insights are deterministic statements computed from actual history only.

---

1. **RED: period selection/navigation** — exact calendar week/month/year/all bounds, offset navigation, future navigation blocked, Swedish date labels.
2. **RED: KPI and normalized activity model** — active days, completion %, total duration, period comparison, count/time target semantics, deleted filtering, zero baseline.
3. **RED: habit performance rows** — type, progress, streak, raw value, previous-period comparison, stable metadata/fallback.
4. **RED: heatmap and insights** — exactly 12 Monday-based weeks, bounded intensity levels, deterministic weekday/trend insights, truthful empty states.
5. **GREEN/REFACTOR: model + routes** — SQL-bounded reads, safe query parsing, GET/HEAD only, existing detail and timeline compatibility.
6. **GREEN: reference UI** — sidebar, top period control, KPI cards, normalized stacked bars, performance table, 12-week heatmap, insights; local SVG/CSS/icons only.
7. **Responsive/accessibility** — compact mobile header/nav, horizontally safe tables/charts, semantic controls, text alternatives, focus-visible, reduced motion, 320px guard.
8. **Verification/delivery** — full tests, compile/diff/systemd checks, database mtime proof, browser interaction/console/visual QA, PR, privacy-safe local merge, deploy and restart recovery.
