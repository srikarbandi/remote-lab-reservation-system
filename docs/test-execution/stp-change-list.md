# STP change list for Part 3

Changes the STP (`docs/Team16_Remote_Laboratory_STP.docx`) needs so that it matches what the team has actually built and run. **One person edits the .docx, once, at the end**, from this list, so that two people never edit the Word file at the same time. Section numbers are the STP's own.

Each item says what to change and where the evidence is. Nothing here changes a requirement or a policy; if one does, update the SRS, SAD and STP together.

## Wording that is now out of date

| STP section | Current wording | Change it to | Why |
|---|---|---|---|
| 7 Test schedule | "...proposed and milestone-based because no submission deadline or implementation completion date has been provided." | State that the Part 3 evaluation slot is Friday 13 November 2026, 1:15 to 3:30 pm, and that the milestones below lead up to it. Keep the effort estimates; they are still estimates. | The deadline is now known. |
| 8 Test deliverables | "Only this plan exists as the present deliverable; execution artifacts will be produced later." | List the Part 3 reports as deliverables, all in `docs/reports/`: Unit Test Report, System Validation Report, Code Coverage Report, Branch Coverage Report. Add the execution register and the run, drill and load-test logs in `docs/test-execution/`. | Part 3 requires these four reports, and execution artifacts now exist. |
| 14 Test metrics | "The initial baseline is 37 planned cases, 0 executed..." | Replace the baseline sentence with: figures are generated into the System Validation Report from the execution register and are not copied into the STP. | Hard-coding figures in a Word file makes them stale on the next run. |
| 5.1 Entry criteria | "HTTPS test environment and test accounts are ready" | Add that each execution records which environment it ran in, and that runs on a development environment with the test-only login are labelled as such in the report. | The first system runs used a development container and the test-only `X-Test-User` login because the auth module was not merged; the logs state this as a deviation. |

## Metrics to add (section 14)

Add two metrics next to the existing ones, because Part 3 asks for code and branch coverage reports:

| Metric | Definition |
|---|---|
| Code coverage | 100 × executable lines run by the automated tests / executable lines, measured with `coverage.py` over `app/`; report per module |
| Branch coverage | 100 × branches taken / branches, measured with `coverage.py --branch` over `app/`; report per module |

State that coverage describes the automated tests only, not the system cases, and that a high figure does not replace executing the STP cases. The generator is `scripts/test_reports.py` (on the interim-reports pull request) and the output is in `docs/reports/`.

## Cases to add (section 13)

Behaviour that exists in the code and is exercised by automated tests, but that no STP case describes. Give each a case ID in the STP so it can be executed and recorded. Suggested homes are shown; keep the STP's existing ID scheme.

| Proposed case | Behaviour | Expected result | Existing automated test (supports, does not replace, the case) |
|---|---|---|---|
| TC-F-017 (extra scenario) | Utilization report range longer than 366 days | 422 `INVALID_RANGE`; nothing computed | `test_tc_f_017_invalid_ranges_are_rejected` |
| TC-F-017 (extra scenario) | Utilization report with `to_date` in the future | 422 `INVALID_RANGE` ("Must not be in the future") | same test |
| TC-EDGE-008 (new) | Booking, approval or maintenance waits more than 5 s for the equipment row lock | 503 `LOCK_TIMEOUT`; no rows change; a retry succeeds once the lock is free | `test_lock_timeout_returns_503_and_changes_nothing` |
| TC-F-014 (extra scenario) | Maintenance PATCH or DELETE with an out-of-date `expected_version` | 409 `STALE_VERSION`; block unchanged | `test_tc_f_014_update_with_stale_version_is_409`, `test_tc_f_014_delete_stale_version_and_permissions` |
| TC-F-015 (extra scenario) | Notification list paging: default page size, maximum page size, invalid `page` or `page_size` | Page size defaults to 20 and is at most 100; a `page` below 1, a `page_size` outside 1 to 100 or a non-integer is rejected; only the caller's own notifications are listed | `test_tc_sr_005_notification_paging_validation` |
| TC-F-016 (extra scenario) | Usage of whole minutes only | A 90 second interval is recorded as 1 minute (rounded down); a request on a reservation that has not ended is 409 `RESERVATION_NOT_ENDED`; an invalid interval is 422 `INVALID_USAGE`; a stale version is 409 | `test_tc_f_016_partial_minutes_round_down`, `test_tc_f_016_stale_version_is_409` |

TC-EDGE-008 needs the SAD to name the lock timeout. SAD 4.1.1 describes the lock but the 5 second value and the 503 response are an implementation choice (`app/common/locking.py`); agree it with the team and record it in the SAD before the case is added.

## Behaviour to state as a known limitation (not a case)

These are in the code today. They are not defects against the current STP, but the evaluator may ask, so decide the answer before Friday.

- **Order of 404 and 403.** On recording usage, on changing or deleting a maintenance block, and on the utilization report, a request for a reservation, block or lab that does not exist returns 404 before the role check runs, so someone without the right role can tell whether an ID exists. IDs are random UUIDs, so this is low risk, but TC-SR-001 says rejected calls must not expose private data. Either accept and document it, or check the role first.
- **Cases the register cannot mark executed yet.** TC-F-014 (booking across a block) and TC-F-015 (notifications) are Blocked because the reservations and approvals modules are not merged. TC-NF-001 needs the history endpoint and a deployment-like environment; TC-NF-005 needs the isolated test deployment. See `docs/reports/system-validation-report.md`.

## Order of work

1. Generate the reports from the final build (`scripts/test_reports.py`, `scripts/system_validation_report.py`).
2. Apply this list to the .docx in one sitting.
3. Check that every figure quoted in the STP either is generated or is not quoted.
