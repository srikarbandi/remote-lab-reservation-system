# Authentication and Accounts — System Validation Report

Tester: Spoorthy M
SRN: PES1UG24AM280
Scope: Authentication and account management browser workflows.
Environment: Windows, Flask, PostgreSQL, local browser.

The following checks were executed manually and confirmed as passed by the tester.

| ID | Check | Actual result | Status |
|---|---|---|---|
| AUTH-M01 | Administrator creates a Student account | Account created and user ID returned | PASS |
| AUTH-M02 | Retain the created user ID | User ID copied for subsequent updates | PASS |
| AUTH-M03 | Student logs in after administrator logs out | Login succeeded; administrator forms hidden | PASS |
| AUTH-M04 | Incorrect password | Login rejected | PASS |
| AUTH-M05 | Administrator logs in again | Account management forms displayed | PASS |
| AUTH-M06 | Change Student role to Technician | Role update succeeded | PASS |
| AUTH-M07 | Log in with updated account | Technician role displayed | PASS |
| AUTH-M08 | Disable the account | Update returned active=false | PASS |
| AUTH-M09 | Disabled account attempts valid login | Login rejected | PASS |
| AUTH-M10 | Re-enable the account | Update returned active=true | PASS |
| AUTH-M11 | Re-enabled account logs in | Login succeeded | PASS |

Result: 11 of 11 checks passed.
Evidence: Tester-confirmed execution; screenshots were not retained for each check.

These checks validate the authentication and accounts workflows only.
They do not establish completion of the full project STP.

## Additional logout validation

Tester: Spoorthy M
STP reference: TC-F-002

- Protected /api/auth/me endpoint returned UNAUTHENTICATED after logout: PASS.
- Browser Back followed by refresh showed the login form with management controls hidden: PASS.
- Existing automated test_logout_revokes_session confirms the old session token is rejected: PASS in the recorded 193-test run.

TC-F-002 result: PASS, using combined manual and automated evidence.

## Additional authentication validation — 19 November 2026

Automated suite: 201 passed, 0 failed, 0 skipped in 82.38 seconds.
Statement coverage: 95.37%.
Branch coverage: 88.16% (201/228).

Eight additional scenarios passed in test_auth_stp.py:
- Failures outside the 15-minute counting window reset correctly.
- Session remains valid at 1,799 seconds of inactivity.
- Session expires at exactly 1,800 seconds.
- Session expires at 1,801 seconds.
- Disabling an account preserves its seeded reservation unchanged.
- Disabling an account rejects its existing authenticated HTTP session.
- An invalid CSRF token prevents account creation without inserting a user.
- Captured application output and authentication audit records contain none
  of the seeded passwords or issued session/CSRF tokens.

Timing method: database timestamp adjustment and a controlled application clock.
Log inspection scope: automated-test application output and audit records.

Local HTTPS checks:
- HTTPS health endpoint returned 200 on port 5443.
- Browser login over HTTPS succeeded.
- Browser logout over HTTPS succeeded.
- Plain HTTP on port 5443 was rejected with a connection reset.

Environment: Flask development server with a temporary self-signed certificate.
This validates the local HTTPS configuration, not production certificate trust.
