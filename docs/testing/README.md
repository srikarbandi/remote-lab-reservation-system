# Testing evidence

This folder contains authentication/account validation evidence and historical
whole-application test and coverage reports generated during that work.

Each report applies to the code and test run recorded in it. Earlier totals and
coverage percentages do not describe later integrated builds.

Final consolidated whole-application reports are maintained in `docs/reports/`.
Check their recorded build, execution date, failures and skips before citing them.

## Route protection checks

`tests/integration/test_auth_all_routes.py` discovers API routes from Flask's
URL map and checks anonymous access and missing-CSRF rejection with a real
authenticated session.

The CSRF endpoint and equipment HTML page are intentionally public.
Login is tested separately for missing CSRF. Anonymous logout is checked with
a valid anonymous CSRF token so its authentication requirement is exercised.

These checks verify route protection, not complete business workflows or
role-based authorization for every operation.

## STP document

Authentication execution evidence was added to
`docs/Team16_Remote_Laboratory_STP.docx` through the merged authentication work.
Partially verified cases remain distinguished from fully passed cases.
Further shared STP edits are coordinated with Sreekar.