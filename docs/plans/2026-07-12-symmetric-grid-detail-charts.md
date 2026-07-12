# Symmetric Overview Grid and Habit Detail Charts

**Goal:** Make the overview grid symmetric and slightly shorter, simplify the habits table, and make habit detail charts self-explanatory with visible y-axis units plus bar/line switching.

## Overview decisions

- Primary and secondary rows use the same `1.7fr / .9fr` columns so `Tidsaktivitet` and `Aktivitet senaste 12 veckorna` have identical widths.
- Reduce responsive chart height to 150–235 px and heatmap rows to 12–17 px.
- Remove the `Typ` column.
- Render streak as a number only; preserve the full Swedish streak phrase in a tooltip.

## Habit detail decisions

- Keep the existing bar chart as default.
- Add a bar/line toggle stored per habit in `sessionStorage`.
- Render a real SVG y-axis with a visible title:
  - `Tid` and seconds/minutes/hours for time habits.
  - `Tillfällen` and integer `st` ticks for count habits.
- Keep adaptive x-axis labels, accessible chart labels, point/bar titles, responsive redraw, and local assets only.

## Verification gates

- Exact 1024×768 overview remains above fold.
- Left card widths are pixel-identical.
- Count and time detail pages show correct units.
- Bar and line modes both render and update ARIA state.
- Full tests, browser QA, compile/diff/systemd checks, deployment screenshots, and restart recovery.
