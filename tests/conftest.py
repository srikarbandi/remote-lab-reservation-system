"""Shared pytest fixtures.

Unit tests need nothing. Integration tests need a PostgreSQL 14+ database and are
skipped unless TEST_DATABASE_URL is set, for example:

    docker compose up -d db
    export TEST_DATABASE_URL=postgresql://lab:lab@localhost:5432/lab

Each test session creates a throw-away schema from db/schema.sql inside that
database and drops it afterwards, so your development data is never touched.
"""

import os
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from flask import g, request
from psycopg.rows import dict_row

from app import create_app

SCHEMA_SQL = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
ALL_TABLES = (
    "idempotency_records, login_attempts, sessions, audit_events, notifications, usage_records, "
    "maintenance_blocks, reservations, equipment, lab_opening_intervals, lab_memberships, labs, users"
)


def _make_app(config: dict | None = None):
    app = create_app({"TESTING": True, "SECRET_KEY": "test-only", **(config or {})})

    @app.before_request
    def test_only_login():
        # Stand-in for the auth module (it will set g.user_id from the session cookie).
        user = request.headers.get("X-Test-User")
        if user:
            g.user_id = UUID(user)

    return app


@pytest.fixture()
def app():
    return _make_app()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(scope="session")
def pg_url():
    base = os.environ.get("TEST_DATABASE_URL")
    if not base:
        pytest.skip("TEST_DATABASE_URL is not set; skipping database integration tests")
    schema = f"t_{uuid4().hex[:10]}"
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
    joiner = "&" if "?" in base else "?"
    scoped = f"{base}{joiner}options=-csearch_path%3D{schema}"
    with psycopg.connect(scoped, autocommit=True) as conn:
        conn.execute(SCHEMA_SQL.read_text())
    yield scoped
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(f'DROP SCHEMA "{schema}" CASCADE')


@pytest.fixture()
def new_conn(pg_url):
    """Factory for independent autocommit connections (each service call opens its own transaction)."""
    opened = []

    def make():
        conn = psycopg.connect(pg_url, autocommit=True, row_factory=dict_row)
        opened.append(conn)
        return conn

    yield make
    for conn in opened:
        conn.close()


@pytest.fixture()
def db(new_conn):
    """A clean database connection for seeding and assertions."""
    conn = new_conn()
    conn.execute(f"TRUNCATE {ALL_TABLES} RESTART IDENTITY CASCADE")
    return conn


@pytest.fixture()
def db_app(pg_url, db):
    return _make_app({"DATABASE_URL": pg_url})


@pytest.fixture()
def db_client(db_app):
    return db_app.test_client()
