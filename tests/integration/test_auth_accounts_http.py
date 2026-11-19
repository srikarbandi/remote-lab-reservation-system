import pytest

from app import create_app
from app.auth.passwords import hash_password

BASE = "https://localhost"


@pytest.fixture()
def account_http(pg_url, db):
    lab_id = db.execute(
        "INSERT INTO labs (name) VALUES (%s) RETURNING id",
        ("Account HTTP Lab",),
    ).fetchone()["id"]

    password_hash = hash_password("LabDemo2026!")

    for identifier, role in [
        ("http-admin", "Administrator"),
        ("http-student", "Student"),
    ]:
        user_id = db.execute(
            """
            INSERT INTO users (identifier, password_hash)
            VALUES (%s, %s)
            RETURNING id
            """,
            (identifier, password_hash),
        ).fetchone()["id"]

        db.execute(
            """
            INSERT INTO lab_memberships (user_id, lab_id, role)
            VALUES (%s, %s, %s)
            """,
            (user_id, lab_id, role),
        )

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "account-http-test-secret",
            "DATABASE_URL": pg_url,
        }
    )

    return {"client": app.test_client(), "lab_id": str(lab_id)}


def sign_in(client, identifier):
    csrf = client.get(
        "/api/auth/csrf",
        base_url=BASE,
    ).get_json()["csrf_token"]

    response = client.post(
        "/api/auth/login",
        base_url=BASE,
        json={"identifier": identifier, "password": "LabDemo2026!"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    return response.get_json()["csrf_token"]


def account_body(world):
    return {
        "identifier": "new-http-account",
        "password": "StudentDemo2026!",
        "lab_id": world["lab_id"],
        "role": "Student",
    }


def test_admin_creates_account_over_http(account_http):
    client = account_http["client"]
    csrf = sign_in(client, "http-admin")

    response = client.post(
        "/api/users",
        base_url=BASE,
        json=account_body(account_http),
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 201
    assert response.get_json()["user"]["role"] == "Student"
    assert "password_hash" not in response.get_json()["user"]


def test_student_cannot_create_account_over_http(account_http):
    client = account_http["client"]
    csrf = sign_in(client, "http-student")

    response = client.post(
        "/api/users",
        base_url=BASE,
        json=account_body(account_http),
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 403


def test_anonymous_cannot_create_account(account_http):
    response = account_http["client"].post(
        "/api/users",
        base_url=BASE,
        json=account_body(account_http),
    )

    assert response.status_code == 401


def test_account_creation_requires_csrf(account_http):
    client = account_http["client"]
    sign_in(client, "http-admin")

    response = client.post(
        "/api/users",
        base_url=BASE,
        json=account_body(account_http),
    )

    assert response.status_code == 403


def test_admin_changes_role_over_http(account_http):
    client = account_http["client"]
    csrf = sign_in(client, "http-admin")
    headers = {"X-CSRF-Token": csrf}

    created = client.post(
        "/api/users",
        base_url=BASE,
        json=account_body(account_http),
        headers=headers,
    ).get_json()["user"]

    response = client.patch(
        f"/api/users/{created['id']}",
        base_url=BASE,
        json={"lab_id": account_http["lab_id"], "role": "Technician"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.get_json()["user"]["role"] == "Technician"


def test_admin_disables_account_over_http(account_http):
    client = account_http["client"]
    csrf = sign_in(client, "http-admin")
    headers = {"X-CSRF-Token": csrf}

    created = client.post(
        "/api/users",
        base_url=BASE,
        json=account_body(account_http),
        headers=headers,
    ).get_json()["user"]

    response = client.patch(
        f"/api/users/{created['id']}",
        base_url=BASE,
        json={"lab_id": account_http["lab_id"], "active": False},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.get_json()["user"]["active"] is False


def test_active_must_be_boolean(account_http):
    client = account_http["client"]
    csrf = sign_in(client, "http-admin")

    response = client.patch(
        "/api/users/00000000-0000-0000-0000-000000000001",
        base_url=BASE,
        json={"lab_id": account_http["lab_id"], "active": "false"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 422