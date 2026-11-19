# Unit Test Report

Project: Remote Laboratory Equipment Reservation System
Contributor: Spoorthy M
SRN: PES1UG24AM280

## Execution

Command:
python -m coverage run --branch --source=app -m pytest -q -rs --junitxml=docs/testing/test-results.xml

Total tests: 201
Passed: 201
Failed: 0
Skipped: 0

Classification by test module path:
- Integration: 122
- Unit and other tests outside the integration directory: 79

This classification follows directory placement, not an independent review of each test's isolation.

## Scope

The suite includes password verification, authentication, sessions,
account management, HTTP endpoints, and existing shared-module tests.

These are suite-wide results, not tests authored solely by this contributor.

## Evidence

- test-results.xml: individual test outcomes
- coverage-summary.txt: coverage by Python module
- coverage.json and coverage.xml: machine-readable coverage
- htmlcov/index.html: detailed coverage report

Statement coverage: 95.37%
Branch coverage: 88.16% (201/228 branches)

## Limitations

Passing tests do not establish completion of unimplemented modules or the full STP.
Manual authentication and account checks are recorded separately in
System_Validation_Report.md.

