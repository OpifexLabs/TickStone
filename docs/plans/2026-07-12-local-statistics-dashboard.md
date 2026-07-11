# Local TickStone Statistics Dashboard Implementation Plan

> **For Hermes:** Execute task-by-task with strict TDD, browser evidence, and production-like Pi deployment.

**Goal:** Deliver a minimal, polished, responsive TickStone statistics dashboard reachable only over the home LAN and Tailscale.

**Architecture:** A dependency-free Python HTTP service opens the existing SQLite database read-only for each request, computes compact summary/read models, and renders local HTML/CSS/JS assets. The service exposes only GET/HEAD health and dashboard routes, binds to port 8750, runs under systemd as `allangamal`, and is restricted by UFW to LAN plus the existing Tailscale interface policy.

**Tech Stack:** Python 3.13 standard library, SQLite read-only URI, semantic HTML, local CSS and minimal vanilla JS, systemd, UFW.

---

### Task 1: Statistics read model (RED/GREEN)
- Create `tests/tickstone_dashboard_test.py` first.
- Specify empty-state, active-event filtering, count/time totals, 05:00 TickStone-day use, seven-day activity, stable habit labels, recent events, and read-only database behavior.
- Implement in `tools/tickstone_dashboard.py` only after RED.

### Task 2: Safe HTTP contract (RED/GREEN)
- Test `/`, `/healthz`, `/assets/styles.css`, `/assets/app.js`, HEAD behavior, 404, 405, security headers, no-store policy, body limits, and no filesystem traversal.
- Implement a small `ThreadingHTTPServer`; expose no mutation routes.

### Task 3: Minimal responsive UI (RED/GREEN)
- Add source/HTML guards for semantic landmarks, accessible focus state, reduced motion, mobile breakpoint, no horizontal overflow, locally hosted assets, Swedish product copy, and useful empty states.
- Build a quiet warm-neutral design with one green accent, strong typography, summary cards, seven-day visual, habit rows, and recent activity.

### Task 4: Operations contract
- Add `deploy/tickstone-dashboard.service` with restart policy and systemd hardening.
- Document LAN/Tailscale URLs, security boundary, health check, logs, and update procedure in README.
- Add dashboard tests to `tools/run_tests.sh`.

### Task 5: Verification and delivery
- Run focused tests, all host tests, compile checks, diff checks, HTTP integration smoke, systemd verify, and security analysis.
- Review the complete diff, commit with Opifex noreply identity, open PR, privacy-safe local merge, push, and verify GitHub metadata.

### Task 6: Pi deployment and browser evidence
- Install the repo-owned unit, allow `8750/tcp` only from `192.168.86.0/24`, enable/start service, and verify localhost/LAN/Tailscale HTTP.
- Prove restart recovery, ensure SQLite remains unmodified, and inspect journald.
- Render and inspect desktop plus iPad/mobile layouts in a real browser; fix any visual/accessibility defect RED-first.
