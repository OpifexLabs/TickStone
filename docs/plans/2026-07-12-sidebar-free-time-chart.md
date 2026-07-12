# Sidebar-free Warm Dashboard and Time Chart

**Goal:** Apply the user's post-redesign feedback without weakening the local/read-only architecture.

## Product decisions

- Remove the sidebar and return to the earlier warm paper, serif-heading and muted-green visual language.
- Keep calendar period navigation, KPI cards, habit table, heatmap, insights and detail pages.
- Replace the normalized count/time stack with actual duration data only. Count events remain visible in KPI/table/history but never enter this chart.
- Let users select individual time-based habits and switch between grouped bars and lines.
- Persist chart type and selected habits in `sessionStorage`.
- Stretch the 12-week heatmap's twelve week columns across the full card width.

## Data contract

`GET /api/time-chart?period=week|month|year|all&offset=N` returns bounded, read-only JSON. Values are integer seconds. Week/month use daily buckets; year/all-time use monthly buckets. Positive future offsets are rejected.

## Verification

- RED/GREEN tests for real seconds, exclusion of count habits, endpoint bounds/read-only behavior, sidebar absence, chart controls and heatmap width.
- Complete host suite, compile check, diff check and systemd unit verification.
- Real-browser bar/line switching, habit selection, visual review and console inspection.
- Production health, LAN/Tailscale and restart recovery after deployment.
