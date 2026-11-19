# Sprint 2 — Testing, Validation, Auth Hardening & Close-out

> *Reconstructed from git history on 20 Nov 2026; sprint boundaries were not tracked on GitHub at the time. Dates are from the real commit and merge history.*

**Goal:** Complete testing per the Test Plan, generate the four Part-3 reports, harden authentication, fix the outstanding TC-F-015 defect, and close out.

**Window:** testing work built 11–13 Nov 2026; integrated, reviewed and merged in a close-out on the night of 19–20 Nov 2026.

## Work and evidence

| PR | Author | What | Merged |
|---|---|---|---|
| #2 | Sreekar | Tag tests with STP case IDs, cover remaining branches | 19 Nov |
| #3 | Sreekar | Report generator + interim Unit/Code/Branch Coverage reports | 19 Nov |
| #5 | Sreekar | Backup job + restore drill (TC-NF-005) | 19 Nov |
| #14 | Sreekar | Pin PostgreSQL 16 client in CI (fix backup/restore drill) | 19 Nov |
| #7 | Sreekar | STP system-case runner + recorded runs TC-F-014…017 | 19 Nov |
| #8 | Sreekar | Generated System Validation Report | 19 Nov |
| #9 | Sreekar | STP change list for the `.docx` | 19 Nov |
| #13 | Spoorthy | Route-wide auth/CSRF sweep tests | 19 Nov |
| #15 | Soha | Admin cancel-with-reason fix + reservation tests (TC-F-015) | 20 Nov |

Reviews were done on GitHub across the team (e.g. Shristi approved #7/#8/#9 and #15; Spoorthy handled #3/#5/#6). The six stacked testing PRs were merged in dependency order with ordinary merge commits, preserving the real 11–13 Nov commit dates on `main`.

## Results (measured on `main` @ `033ef2f`)
- **Automated tests:** 290 passed, 0 failed, 0 skipped.
- **Coverage:** 90.7% line, 78.2% branch.
- **STP system cases:** TC-F-014, TC-F-015, TC-F-016, TC-F-017 all **Pass**. TC-F-015 moved from Fail → Pass after #15.
- **Reports:** Unit Test, System Validation, Code Coverage, Branch Coverage regenerated in [`docs/reports/`](../reports/).

## Not done / remaining
- **STP execution is partial:** 4 of 37 cases run as formal system cases; the other 33 are supported by the automated tests but not executed as STP system cases (no runners exist for TC-SR / TC-EDGE / TC-UAT and most TC-F cases). The System Validation Report lists them as `Not executed`.
- **STP `.docx` not yet updated** from the results — the change list is in [`docs/test-execution/stp-change-list.md`](../test-execution/stp-change-list.md); one person applies it after pulling.
- Four older commits on the testing PRs carry a different author email; left as-is (the register cites one as a build).

## Retrospective
- **Went well:** real defect fixed test-first (TC-F-015, by its module owner); contribution balanced out (Sreekar 30, Spoorthy 20, Soha 10, Shristi 7 commits); strict one-branch-per-task with real reviews and merge-commit history preserving dates.
- **Didn't go well:** a lot compressed into the final night because GitHub sprint tracking lagged the actual coding.
- **Honest framing:** the code is real and correctly dated in git; sprint tracking was loose and was tightened in the close-out. STP system-case execution is partial and reported as such. No invented burndown, story points, or meetings.
