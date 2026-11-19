"""The application, started for the load test only (TC-NF-001).

The authentication module is not finished, so a load test has no way to log 50 users in. This module
builds the real application and adds the same stand-in the integration tests use: a request that
carries an ``X-Test-User: <user uuid>`` header is treated as logged in as that user. Everything
after that point (routing, services, SQL, role checks) is the real code.

Anyone who can reach the server can act as any user, so it refuses to start unless
LOAD_TEST_HEADER_AUTH=1 is set and it must never be deployed. Bind it to 127.0.0.1.

    LOAD_TEST_HEADER_AUTH=1 FLASK_DATABASE_URL=postgresql://lab:lab@localhost:5432/lab_load \\
        gunicorn -w 4 --threads 8 -b 127.0.0.1:8000 scripts.load_test_app:app

Replace this with real logins once the auth module is merged (see docs/operations/load-test.md).
"""

import os
from uuid import UUID

from flask import g, request

from app import create_app

if os.environ.get("LOAD_TEST_HEADER_AUTH") != "1":
    raise RuntimeError(
        "scripts/load_test_app.py lets any caller act as any user. "
        "Set LOAD_TEST_HEADER_AUTH=1 to confirm this is a load-test run on a private test database."
    )

app = create_app({"SECRET_KEY": "load-test-only"})


@app.before_request
def header_login():
    user = request.headers.get("X-Test-User")
    if user:
        g.user_id = UUID(user)
