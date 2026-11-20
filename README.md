# Remote Laboratory Equipment Reservation System

**Team 16 · PES University · Software Engineering mini project**

A web application that lets students view and reserve laboratory equipment and time slots. It detects booking conflicts, supports administrator approvals and maintenance blocks, and reports equipment utilization.

> "Remote" means online reservation and administration. Equipment is still used physically in the lab. Hardware control, payments, email/SMS and university-wide identity integration are out of scope.

## Status

| Area | State |
|---|---|
| SRS (requirements) | Written, v1.0. Faculty approval pending |
| SAD (architecture and design) | Written, v1.1. Faculty approval pending |
| STP (test plan) | Written, v1.0, 37 planned test cases. Approval pending |
| Application | **Implemented.** Auth & accounts, equipment catalogue & availability, reservations & approvals, and maintenance/usage/reporting/notifications are built and merged on `main` |
| Automated tests | **290 passing, 0 failed.** 90.7% line / 78.5% branch coverage. Reports in [`docs/reports/`](docs/reports/) |
| STP execution | **15 of 37** cases executed (TC-F-001, 002, 014–017; TC-SR-001, 003, 004, 005; TC-NF-001, 005; TC-EDGE-003, 005, 006) — a mix of system-case runs, Spoorthy's auth/security closeout evidence, and tagged tests covering the exact steps. TC-F-014–017 were run against the STP revision on `main` (`7b66d52`; #17's added scenarios not yet re-run). The remaining 22 are supported by automated tests but not yet run as formal STP cases. See [`docs/reports/system-validation-report.md`](docs/reports/system-validation-report.md) |

The booking policies and numeric targets in the documents are proposals pending faculty review. If a policy changes, the SRS, SAD and STP must be updated together.

## Team and ownership

Split agreed in the team chat. Module owners are who builds that part; test owners follow STP section 9.

| Member | SRN | Builds | Main tests |
|---|---|---|---|
| Spoorthy M | PES1UG24AM280 | Login, accounts, roles, integration of everyone's code, running the combined app | Case coverage, RTM, test summary |
| Shristi Shukla | PES1UG24AM268 | Equipment catalogue, search/filter, equipment management, available slots and opening hours | Student UI, usability, accessibility |
| Soha Rafiq | PES1UG24AM278 | Booking requests, conflict detection, history, cancellation, approval/rejection | Authentication, permissions, administration, security |
| Sreekar Bandi | PES1UG24AM282 | Maintenance blocks, usage records, utilization reports, in-app notifications | Concurrency, maintenance, usage, reporting, load, recovery |

Requirement-by-requirement ownership is in [`docs/requirements-ownership.md`](docs/requirements-ownership.md).

## Documents

| Document | File |
|---|---|
| Software Requirements Specification | [`docs/Team16_Remote_Laboratory_SRS.docx`](docs/Team16_Remote_Laboratory_SRS.docx) |
| Software Architecture and Design | [`docs/Team16_Remote_Laboratory_SAD.docx`](docs/Team16_Remote_Laboratory_SAD.docx) |
| Software Test Plan | [`docs/Team16_Remote_Laboratory_STP.docx`](docs/Team16_Remote_Laboratory_STP.docx) |
| Course templates | [`docs/templates/`](docs/templates/) |
| Test execution register | [`docs/test-execution/execution-register.csv`](docs/test-execution/execution-register.csv) |
| Team assignment | [`docs/assignment.md`](docs/assignment.md) |

## Architecture in brief

A layered modular monolith (SAD 3.5): **controllers** (`routes.py`) parse HTTP input, **services** (`services.py`) apply rules and own transactions, and parameterized queries do the database work. Only the backend touches the database.

The rules every module must follow:

- **Intervals are half-open** `[start, end)`. Adjacent slots are allowed. Use `app/common/intervals.py`.
- **Pending and Approved reservations hold a slot.** Rejected, Cancelled and Completed do not.
- **The server decides conflicts**, never the browser. Booking, approval, cancellation, maintenance, equipment status and opening-hour changes all lock the equipment row (`SELECT ... FOR UPDATE`) first. See the booking transaction protocol in SAD 4.1.1.
- **Notification and audit rows are written in the same transaction** as the state change.
- **Errors use one contract** (`app/common/errors.py`): `{"error": {"code", "message", "request_id"}}`.
- Roles come from the database, never from the browser. Parameterized queries only.

## Tech stack

Python 3.11+, Flask, PostgreSQL 16, psycopg 3, pytest, ruff, GitHub Actions. HTML/CSS/JavaScript with server templates for the UI (SAD 3.6).

## Getting started

```bash
git clone <repo-url>
cd remote-lab-reservation-system

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp .env.example .env               # then edit the values

docker compose up -d db            # PostgreSQL, loads db/schema.sql on first start
flask --app app run --debug        # http://127.0.0.1:5000/healthz

pytest                             # run the tests
ruff check .                       # lint
```

To reset the local database after changing `db/schema.sql`: `docker compose down -v && docker compose up -d db`.

## Project structure

```
app/
  __init__.py        create_app(), request IDs, error handlers, module registration
  common/            shared error contract and interval rules
  auth/              login, logout, accounts, sessions          (Spoorthy)
  equipment/         catalogue, search, availability, admin     (Shristi)
  reservations/      booking, history, cancellation             (Soha)
  approvals/         approve / reject                           (Soha)
  maintenance/       maintenance blocks                         (Sreekar)
  notifications/     in-app notifications                       (Sreekar)
  usage/             actual usage, no-shows, completion         (Sreekar)
  reporting/         utilization report                         (Sreekar)
  audit/             audit events (shared, owner to be agreed)
db/schema.sql        DRAFT shared schema from the SAD data model
docs/                SRS, SAD, STP, templates, test execution register
tests/               pytest suites
.github/             CI workflow, PR and issue templates
```

Each module has `routes.py` (HTTP endpoints) and `services.py` (business logic and database access). All modules are implemented; the docstrings cite the requirement IDs each one satisfies.

## How we work

Read [`CONTRIBUTING.md`](CONTRIBUTING.md). In short: one branch per task, pull requests into `main`, one reviewer, CI must pass.

## Testing and the STP update

1. Implement a module and write its tests (case IDs match the STP, for example `TC-F-014`).
2. Run the cases. Record each result in [`docs/test-execution/execution-register.csv`](docs/test-execution/execution-register.csv): status, build commit, tester, date, actual result, evidence link and defect ID.
3. Log failures as GitHub issues using the bug template.
4. Generate the Unit, Code Coverage and Branch Coverage reports with `python scripts/test_reports.py` (needs `TEST_DATABASE_URL`). They are written to [`docs/reports/`](docs/reports/) from a real test run, so regenerate them after other modules are merged instead of editing them by hand.
5. When execution is finished, one person folds the results into the STP (actual results, metrics, deferrals, final test summary) and bumps its version.

Until a case has real evidence, its status stays `Not executed`. Do not record results that were not observed.

## Roadmap

- [x] Agree and finalize `db/schema.sql` as a team
- [x] Shared helpers: audit `record_event()` and notification creation, usable by every module
- [x] Auth and sessions (Spoorthy)
- [x] Equipment and availability (Shristi)
- [x] Reservations and approvals (Soha)
- [x] Maintenance, usage, reporting, notifications (Sreekar)
- [x] Integrated build and smoke test — CI green on `main`, 290 automated tests pass
- [ ] Execute the STP cases and fill the execution register — **partial:** 15 of 37 executed; the rest are backed by automated tests but not yet run as formal STP cases
- [ ] Update the STP `.docx` from the results and write the test summary
- [ ] Faculty review
