# Authentication closeout evidence

Executed by: Spoorthy M
Date: 20 November 2026

Automated results:
- Authentication baseline: 61 passed, 0 failed, 0 skipped.
- Real-session authorization and booking validation: 9 passed, 0 failed, 0 skipped.
- Injection-like inputs and booking log secret hygiene: 6 passed, 0 failed, 0 skipped.
- Total across three separate runs: 76 passed.
- Tested revisions are recorded separately in the accompanying commit files.

Browser observations:
- Student login succeeded and displayed the Student role.
- Student opened the equipment workspace.
- Wrong password displayed "Invalid identifier or password."
- Equipment name and description containing HTML/script payloads displayed literally.
- No alert popup appeared after refreshing.
- Cookie attributes and local HTTPS observations are recorded in cookie-inspection.txt.
- HTTPS used a temporary self-signed development certificate; certificate trust was not validated.

Scope:
- These are targeted authentication/security checks, not a full-suite result.
- Secret inspection covers captured application output and audit rows.
- Browser XSS observations cover the tested equipment rendering paths.
- STP case statuses require reconciliation against every required step before consolidation.
