# Running STP system cases (TC-F-014, TC-F-015, TC-F-016, TC-F-017)

`scripts/run_stp_cases.py` performs the steps of these STP cases as HTTP requests to the running application, inspects the database rows after each step, and writes a log per case. It exists so the System Validation Report rests on observed results, not on unit tests (the STP says a passing unit test supports a case but does not replace system-level evidence). TC-F-015 and the booking steps of TC-F-014 need the reservations and approvals modules; on a build without them the logs record Blocked, not Pass or Fail.

## Run it

1. Create a scratch database. The runner creates the tables with `--init-schema` and adds its own synthetic fixtures; nothing else needs to be seeded.

   ```bash
   createdb lab_cases
   ```

2. Start the application against it (the auth module cannot log users in yet, so this uses the test-only login header; see `docs/operations/load-test.md`):

   ```bash
   LOAD_TEST_HEADER_AUTH=1 FLASK_DATABASE_URL=postgresql://lab:lab@localhost:5432/lab_cases \
       gunicorn -w 2 -b 127.0.0.1:8000 scripts.load_test_app:app
   ```

3. Run the cases (commit your code first so the build is identifiable):

   ```bash
   python scripts/run_stp_cases.py --base-url http://127.0.0.1:8000 \
       --database-url postgresql://lab:lab@localhost:5432/lab_cases --init-schema \
       --where "<host, PostgreSQL version>" --server "gunicorn -w 2, test-header login" --update-register
   ```

   Logs go to `docs/test-execution/runs/<date>/<case>.md`. `--update-register` fills status, build commit, tester, date, actual result and evidence link for the cases it ran in `docs/test-execution/execution-register.csv`.

## Statuses

The STP allows Pass, Fail, Blocked and Not executed.

- **Pass**: every step ran and matched the expected result, response and database.
- **Fail**: a step ran and did not match. Log it as a defect (bug template) and put the issue number in the register.
- **Blocked**: a step needs something that does not exist yet. The step and the case are recorded as Blocked with the reason, and the case is re-run when the prerequisite lands.

## Limits to state when quoting a result

- Logins use the `X-Test-User` header. Re-run with real sessions once the auth module is merged.
- Steps are HTTP requests, not browser UI actions.
- Fixtures are synthetic and inserted directly into the database, because booking and approval are not implemented yet.
- Booking, approval, rejection and cancellation are run through the real reservations and approvals endpoints. Rows the case needs but that no endpoint creates (for example another student's Approved reservation, or the held request H1 in TC-F-014) are inserted directly into the database as fixtures; each log says so.
- If the booking endpoint is missing from a build, TC-F-014 uses the availability endpoint as the stand-in and TC-F-015 records its first step as Blocked, so the same command works on older builds.
- A Blocked case is not a failed case and not an executed one. Do not quote it as covered in the System Validation Report.
