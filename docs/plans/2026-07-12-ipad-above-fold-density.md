# iPad Above-the-Fold Dashboard Density

**Goal:** At an exact 1024×768 iPad-landscape viewport, show the complete dashboard—including the full 12-week heatmap, insights and sync status—without vertical scrolling, while preserving readability.

## Layout contract

- Compact brand strip: approximately 36 px.
- Four KPI cards remain in one row for widths ≥761 px; each card is 72 px high.
- Time chart and habit table remain side-by-side and use a compact 162 px plot.
- Heatmap and insights remain side-by-side.
- Heatmap has twelve flexible columns and seven fixed 13 px rows with a shared 3 px row gap.
- Weekday labels use the exact same seven-row track definition as heat cells.
- Mobile below 761 px retains the stacked responsive flow.

## Required evidence

1. RED/GREEN CSS contract tests.
2. Full host suite, compile, diff and systemd verification.
3. A real Firefox screenshot at exactly 1024×768 before shipping.
4. Push/merge/deploy.
5. A second real screenshot from production at exactly 1024×768 after deployment.
6. Iterate again if the production screenshot clips any section or requires vertical scrolling.
