# Tests

Run everything with `pytest` from the repo root.

- **Unit tests** (`tests/*.py`) need nothing: pure rules, validation, HTTP contract checks.
- **Integration tests** (`tests/integration/`) need PostgreSQL and are skipped when `TEST_DATABASE_URL` is not set:

  ```bash
  docker compose up -d db
  export TEST_DATABASE_URL=postgresql://lab:lab@localhost:5432/lab
  pytest
  ```

  Each test session creates a throw-away schema from `db/schema.sql` inside that database and drops it afterwards, so your development data is not touched. CI runs the same tests against a `postgres:16` service.

Layout, matching the STP test levels (STP section 5):

| File | Level | STP cases |
|---|---|---|
| `test_utilization_calculations.py`, `test_usage_rules.py`, `test_validation.py`, `test_intervals.py` | Unit | TC-F-016, TC-F-017, TC-EDGE-001, TC-EDGE-006 |
| `test_routes_validation.py`, `test_smoke.py` | HTTP contract, no database | TC-SR-005 (input validation) |
| `integration/test_maintenance.py` | Integration | TC-F-014 |
| `integration/test_notifications.py` | Integration | TC-F-015, TC-EDGE-005 |
| `integration/test_usage.py` | Integration | TC-F-016 |
| `integration/test_reporting.py` | Integration | TC-F-017, TC-EDGE-006 |
| `integration/test_concurrency.py` | Integration, real concurrent connections | TC-EDGE-003 |
| `integration/test_routes_http.py` | HTTP with a real database | TC-F-014 to TC-F-017 |

These automated tests support the STP cases but do not by themselves mark them executed. The execution register (`docs/test-execution/execution-register.csv`) is updated only after the case is run as written in the STP, with evidence.

Naming: name tests after the STP case where there is one, for example `test_tc_f_014_...`. Case IDs are in the execution register.

Rules from the STP:

- Use synthetic data only (fixtures in STP 6.1, built in `lab_factories.py`).
- Concurrency tests use separate connections synchronized by a barrier. Do not serialize the requests in the harness, and check the committed rows afterwards.
- A passing unit test supports but does not replace system-level evidence for a case.
