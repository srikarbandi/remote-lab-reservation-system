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
