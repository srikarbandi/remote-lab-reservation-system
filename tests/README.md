# Tests

Run everything with `pytest` from the repo root.

Planned layout, matching the STP test levels (STP section 5):

- `tests/` top level: smoke tests and shared-utility unit tests that need no database
- add `tests/<module>/` folders for module tests as modules are built
- integration tests (row locks, rollback, idempotency, concurrency) need the PostgreSQL container: `docker compose up -d db`

Naming: name tests after the STP case where there is one, for example `test_tc_f_014_maintenance_blocks_overlapping_booking`. Case IDs are listed in `docs/test-execution/execution-register.csv`.

Rules from the STP:

- Use synthetic data only (fixtures in STP 6.1).
- Concurrency tests use separate connections and sessions synchronized by a barrier. Do not serialize the requests in the harness, and check the committed rows afterwards.
- A passing unit test supports but does not replace system-level evidence for a case.
