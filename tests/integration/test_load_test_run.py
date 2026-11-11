"""The TC-NF-001 load test tool against a real application server (scripts/load_test.py).

A short run with a few users: it proves the tool logs users in, drives the read endpoints over HTTP and
counts every response. It is not the load test; the case is executed with 50 users for 10 minutes.
"""

import sys
import threading
from pathlib import Path

import psycopg
import pytest
from werkzeug.serving import make_server

from app import create_app

SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import load_test  # noqa: E402
import synthetic_data  # noqa: E402


@pytest.fixture()
def seeded(pg_url, db):
    with psycopg.connect(pg_url, autocommit=True) as conn:
        synthetic_data.seed(conn, labs=2, equipment_per_lab=3, students=12, reservations=60)
    return pg_url


def _serve(app):
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


def test_tc_nf_001_short_run_measures_catalogue_and_availability_without_errors(seeded, db_app):
    server, base_url = _serve(db_app)
    try:
        result = load_test.run_load(base_url, seeded, users=5, warmup_seconds=0.5, duration_seconds=2)
    finally:
        server.shutdown()

    measured = {s.name: s for s in result.stats}
    assert {"catalogue", "availability"} <= set(measured)
    for stats in measured.values():
        assert stats.requests > 0
        assert stats.errors == 0
    assert set(result.status_counts) == {"200"}
    # 5 users and 60 reservations are below what the case requires, so this can never read as PASS.
    assert result.verdict == "INCOMPLETE"
    assert any("5 virtual users" in p for p in result.preconditions)


def test_tc_nf_001_tool_stops_when_the_server_does_not_accept_the_test_login(seeded, pg_url):
    server, base_url = _serve(create_app({"DATABASE_URL": pg_url, "TESTING": True, "SECRET_KEY": "x"}))
    try:
        with pytest.raises(SystemExit, match="401"):
            load_test.run_load(base_url, seeded, users=2, warmup_seconds=0, duration_seconds=1)
    finally:
        server.shutdown()


def test_tc_nf_001_log_names_the_run_but_not_the_database_url(seeded, db_app, tmp_path):
    server, base_url = _serve(db_app)
    log = tmp_path / "run.md"
    try:
        code = load_test.main(
            ["--base-url", base_url, "--database-url", seeded, "--users", "2"]
            + ["--warmup-seconds", "0", "--duration-seconds", "1", "--log", str(log)]
            + ["--run-type", "Unit test run", "--where", "pytest"]
        )
    finally:
        server.shutdown()

    text = log.read_text()
    assert code == 1  # 2 users and 60 reservations: not the dataset the case requires
    assert text.startswith("# TC-NF-001 Read response performance: INCOMPLETE")
    assert "Unit test run" in text
    assert "<database-url>" in text
    assert seeded not in text
