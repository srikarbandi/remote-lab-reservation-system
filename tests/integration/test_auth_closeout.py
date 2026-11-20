import pytest

from app import create_app
from app.auth.passwords import hash_password

BASE = "https://localhost"
PASSWORD = "Closeout2026!"


@pytest.fixture()
def closeout(pg_url, db):
    labs = [
        db.execute(
            "INSERT INTO labs (name) VALUES (%s) RETURNING id",
            (name,),
        ).fetchone()["id"]
        for name in ("Closeout L1", "Closeout L2")
    ]

    users = {}
    password_hash = hash_password(PASSWORD)

    for identifier, role in [
        ("close-admin", "Administrator"),
        ("close-student", "Student"),
    ]:
        user_id = db.execute(
            "INSERT INTO users (identifier, password_hash) "
            "VALUES (%s, %s) RETURNING id",
            (identifier, password_hash),
        ).fetchone()["id"]
        users[identifier] = user_id
        db.execute(
            "INSERT INTO lab_memberships (user_id, lab_id, role) "
            "VALUES (%s, %s, %s)",
            (user_id, labs[0], role),
        )

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "closeout-test-only",
            "DATABASE_URL": pg_url,
            "AUTH_COOKIE_SECURE": True,
        }
    )

    return app, labs, users


def sign_in(client, identifier, password=PASSWORD):
    csrf = client.get(
        "/api/auth/csrf", base_url=BASE
    ).get_json()["csrf_token"]
    return client.post(
        "/api/auth/login",
        base_url=BASE,
        json={"identifier": identifier, "password": password},
        headers={"X-CSRF-Token": csrf},
    )


def test_wrong_lab_role_grant_changes_nothing(closeout, db):
    app, labs, users = closeout
    client = app.test_client()
    signed_in = sign_in(client, "close-admin")
    assert signed_in.status_code == 200

    before = db.execute(
        "SELECT * FROM lab_memberships ORDER BY user_id, lab_id"
    ).fetchall()

    response = client.patch(
        f"/api/users/{users['close-student']}",
        base_url=BASE,
        json={"lab_id": str(labs[1]), "role": "Administrator"},
        headers={
            "X-CSRF-Token": signed_in.get_json()["csrf_token"]
        },
    )

    assert response.status_code == 403
    after = db.execute(
        "SELECT * FROM lab_memberships ORDER BY user_id, lab_id"
    ).fetchall()
    assert after == before


def test_disabled_login_creates_no_session(closeout, db):
    app, _, users = closeout
    db.execute(
        "UPDATE users SET active = false WHERE id = %s",
        (users["close-student"],),
    )
    client = app.test_client()

    response = sign_in(client, "close-student")

    assert response.status_code == 401
    assert client.get_cookie("lab_session") is None
    assert db.execute(
        "SELECT count(*) AS n FROM sessions WHERE user_id = %s",
        (users["close-student"],),
    ).fetchone()["n"] == 0


def test_anonymous_account_creation_cannot_register(closeout, db):
    app, labs, _ = closeout
    client = app.test_client()

    response = client.post(
        "/api/users",
        base_url=BASE,
        json={
            "identifier": "public-registration-attempt",
            "password": PASSWORD,
            "lab_id": str(labs[0]),
            "role": "Administrator",
        },
    )

    assert response.status_code == 401
    assert db.execute(
        "SELECT id FROM users WHERE identifier = %s",
        ("public-registration-attempt",),
    ).fetchone() is None

    assert not any(
        "register" in rule.rule.lower()
        or "signup" in rule.rule.lower()
        for rule in app.url_map.iter_rules()
    )


def test_all_api_writes_reject_invalid_csrf(closeout, db):
    app, _, _ = closeout
    client = app.test_client()
    assert sign_in(client, "close-admin").status_code == 200
    adapter = app.url_map.bind("localhost", url_scheme="https")
    checked = 0

    before = db.execute(
        "SELECT count(*) AS n FROM audit_events"
    ).fetchone()["n"]

    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api/"):
            continue

        values = {}
        for name, converter in rule._converters.items():
            kind = type(converter).__name__
            values[name] = (
                1 if kind in {"IntegerConverter", "FloatConverter"}
                else "00000000-0000-0000-0000-000000000001"
            )
            if kind == "UUIDConverter":
                from uuid import UUID

                values[name] = UUID(values[name])

        for method in sorted(
            rule.methods & {"POST", "PUT", "PATCH", "DELETE"}
        ):
            url = adapter.build(rule.endpoint, values, method=method)
            response = client.open(
                url,
                method=method,
                base_url=BASE,
                json={},
                headers={"X-CSRF-Token": "invalid-closeout-token"},
            )
            assert response.status_code == 403, (method, url)
            assert (
                response.get_json()["error"]["code"] == "CSRF_FAILED"
            ), (method, url)
            checked += 1

    assert checked > 0
    assert client.get("/api/auth/me", base_url=BASE).status_code == 200
    assert db.execute(
        "SELECT count(*) AS n FROM audit_events"
    ).fetchone()["n"] == before