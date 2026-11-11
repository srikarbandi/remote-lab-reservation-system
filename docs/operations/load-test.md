# Read performance load test (LAB-NF-001, TC-NF-001)

**Requirement.** Catalogue, availability and history requests respond within 2 seconds at the 95th percentile with 50 concurrent test users and 1,000 reservations. Test case: STP TC-NF-001 (2 minute warm-up, then a 10 minute mix of the three reads at 50 concurrent users). Owner: Sreekar Bandi.

## What is in the repo

| File | Purpose |
|---|---|
| `scripts/load_test.py` | The load generator and report writer. Holds 50 users in flight, drops the warm-up, then records every request: count, errors and response times per endpoint (p50, p90, p95, p99, slowest, mean). No slow request is excluded and a timeout counts as an error. |
| `scripts/load_test_app.py` | Starts the real application with a stand-in login (`X-Test-User` header), because the auth module cannot log users in yet. Refuses to start unless `LOAD_TEST_HEADER_AUTH=1`. Bind it to 127.0.0.1 and never deploy it. |
| `scripts/synthetic_data.py` | Builds the dataset (1,000 reservations, at least 50 students). |
| `tests/test_load_test_stats.py`, `tests/integration/test_load_test_run.py` | Tests of the tool's arithmetic and verdict rules and a short end-to-end run. |

## Running it

1. Create a scratch database and seed it:

   ```bash
   createdb lab_load
   python scripts/synthetic_data.py --init-schema --students 60 --reservations 1000 \
       --database-url postgresql://lab:lab@localhost:5432/lab_load
   ```

2. Start the application (gunicorn, four workers, as a deployment-like server):

   ```bash
   LOAD_TEST_HEADER_AUTH=1 FLASK_DATABASE_URL=postgresql://lab:lab@localhost:5432/lab_load \
       gunicorn -w 4 --threads 8 -b 127.0.0.1:8000 scripts.load_test_app:app
   ```

3. Run the case as written (about 12 minutes), from a different machine if you can:

   ```bash
   python scripts/load_test.py --base-url http://127.0.0.1:8000 \
       --database-url postgresql://lab:lab@localhost:5432/lab_load \
       --run-type "Formal execution" --where "<hosts, CPUs>" --server "gunicorn -w 4 --threads 8" \
       --log docs/test-execution/load-test-logs/tc-nf-001-<date>.md
   ```

   Use `--warmup-seconds 5 --duration-seconds 30` for a quick check.

4. Link the log in the `evidence_link` column of the TC-NF-001 row in `docs/test-execution/execution-register.csv`.

## Reading the result

- **PASS**: all three reads measured, 95th percentile at most 2 s on each, no errors, 50 users, at least 1,000 reservations.
- **FAIL**: any read is over the limit or any request failed (a 4xx on a valid request counts, because it means the test data is wrong).
- **INCOMPLETE**: nothing failed, but the mix or the dataset is not what the case asks for. The log lists what is missing. Exit code 1 for both FAIL and INCOMPLETE.

The default has no think time, so exactly 50 requests are in flight at all times. That is the harshest reading of "50 concurrent users"; a run that passes it also passes with pauses between requests.

## Still to do before the case can be marked executed

- **History reads.** `GET /api/reservations?scope=mine` belongs to the reservations module. Until it exists the tool reports it as not measured and the result is INCOMPLETE.
- **Real logins.** Replace the test header with real sessions once the auth module is merged.
- **Deployment-like hosts.** Run with the application, database and load generator on separate hosts. If they share a machine the log says so and the times may be overstated.
