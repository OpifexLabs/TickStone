# Responsive Dashboard Density and Chart Width

**Goal:** Preserve the 1024×768 iPad above-the-fold guarantee while using extra vertical space on taller screens, widening the time chart, narrowing the habits card to roughly 70–75% of its former width, and preventing month-axis label overlap.

## Decisions

- Keep the compact dimensions as hard minimums at 1024×768.
- Scale chart height, KPI-card height, brand height, and heatmap row height with viewport height, capped at readable maxima.
- Use a primary-grid ratio of `1.7fr / .9fr` with a 390 px habits-card minimum.
- Compact the habits table columns and show long comparison text as `Ny`/`Samma` with the full text retained in `title`.
- Render month labels as day numbers and thin x-axis labels according to available plot width.

## Verification gates

- 1024×768 week: full first page visible.
- 1024×768 month: full first page visible and no x-label overlap.
- 1366×1024: chart, cards, and heatmap grow without excessive blank space.
- Loaded browser month view: no clipping in the compact habits table.
- Full tests, compile, diff, systemd verify, post-deploy screenshots and browser console.
