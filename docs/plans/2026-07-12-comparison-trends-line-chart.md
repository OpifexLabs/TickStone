# Comparison Trends and Selectable Line Chart Plan

> **For Hermes:** Implement with strict RED-GREEN-REFACTOR, browser evidence, and final Pi deployment.

**Goal:** Make period-over-period progress explicit and add an accessible multi-habit line chart with selectable habits and week/month/year ranges.

**Architecture:** Keep the dashboard read-only. Add SQL-aggregated comparison and timeline read models, expose a bounded GET-only JSON endpoint, and render the chart in local vanilla JS as accessible SVG. The overview compares event sessions consistently across count/time habits; habit detail keeps value-specific count/duration semantics.

**Tech Stack:** Python stdlib, SQLite read-only queries, semantic HTML/CSS, local vanilla JS/SVG, unittest, systemd.

---

1. **RED: comparison semantics** — test week/month current and previous calendar bounds, positive/negative/unchanged/zero-baseline labels, and deleted filtering.
2. **GREEN: comparison read model** — use bounded SQL aggregation and return human-safe Swedish labels without infinity/misleading percentages.
3. **RED: selectable timeline contract** — test week/day, month/day and year/month buckets, stable habit identities, zero-filled buckets, active-only metadata and bounded invalid range handling.
4. **GREEN: timeline/API** — add `/api/timeline?range=week|month|year`, GET/HEAD only, existing security headers, no SQLite writes.
5. **RED/GREEN: UI** — add overview comparison badges, range controls, accessible habit toggles, SVG line chart, empty state, focus/reduced-motion/responsive guards, and no external requests.
6. **Verify/deliver/deploy** — full tests, browser desktop/mobile inspection, commit/PR/privacy-safe merge, install final main, restart dashboard, prove read-only and restart recovery.
