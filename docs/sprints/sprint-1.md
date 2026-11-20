# Sprint 1 — Module Implementation

> *Reconstructed from git history on 20 Nov 2026; sprint boundaries were not tracked on GitHub at the time. Dates are from the real commit and merge history.*

**Goal:** Build the core modules of the Remote Laboratory Equipment Reservation System on Flask + psycopg3 + PostgreSQL 16, with CI (ruff + pytest) on every PR.

**Window:** 10 Oct 2026 (first commit) → ~13 Nov 2026 for equipment and reservations. The authentication module (Spoorthy) was built during this sprint but **merged later, on 19 Nov (#11, #12), as spillover** into the Sprint 2 close-out.

## Who did what

| Member | Module | Evidence (PR) | Merged |
|---|---|---|---|
| Sreekar Bandi (`srikarbandi`) | Maintenance, usage, reporting, notifications | #1 | — |
| Shristi Shukla (`shukla99`) | Equipment catalogue, availability, admin equipment mgmt, Velvet OS frontend | #4 | 11 Nov |
| Soha Rafiq (`soharafiq`) | Reservations, conflict detection, approvals | #10 | 13 Nov |
| Spoorthy M (`spoorthy0805`) | Authentication, accounts, sessions, CSRF, roles | #11, #12 | 19 Nov |

Shared foundations (schema, audit `record_event()`, notification creation) were agreed as a team before the modules were built.

## Planned vs delivered
- **Planned:** all four modules implemented against the SRS/SAD and integrated on `main`, with CI in place.
- **Delivered:** all four modules built and merged. The application runs; CI (ruff + pytest on Python 3.12 with a `postgres:16` service) is green.

## Not done in Sprint 1 (carried into Sprint 2)
- Admin cancellation with a reason (TC-F-015) — not implemented (fixed in Sprint 2).
- Reservation/approval and route-auth test coverage incomplete.
- Most equipment tests not yet tagged with STP case IDs.
- The four Part-3 reports (Unit, System Validation, Code Coverage, Branch Coverage) not yet generated on `main`.

## Retrospective
- **Went well:** clear one-module-per-owner split; real, dated commits; working CI from early on.
- **Didn't go well:** sprint activity wasn't tracked on GitHub day by day, so the history is more bunched than ideal, and testing lagged implementation.
- **Action for Sprint 2:** dedicate the sprint to testing, validation, auth hardening and close-out, one branch per task with real reviews.
