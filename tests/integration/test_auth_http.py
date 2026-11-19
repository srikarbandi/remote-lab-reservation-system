import pytest

from app import create_app
from app.auth.passwords import hash_password

BASE = "https://localhost"


@pytest.fixture()
def auth_client(pg_url, db):
    db.execute(
        """
        INSERT INTO users (identifier, password_hash)
        VALUES (%s, %s)
        """,
        ("http-test", hash_password("LabDemo2026!")),
    )

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "auth-http-test-secret",
            "DATABASE_URL": pg_url,
        }
    )

    return app.test_client()


def sign_in(client, password="LabDemo2026!"):
    csrf = client.get(
        "/api/auth/csrf",
        base_url=BASE,
    ).get_json()["csrf_token"]

    return client.post(
        "/api/auth/login",
        base_url=BASE,
        json={"identifier": "http-test", "password": password},
        headers={"X-CSRF-Token": csrf},
    )


def test_login_and_current_user(auth_client):
    response = sign_in(auth_client)

    assert response.status_code == 200
    assert "token" not in response.get_json()
    assert response.get_json()["user"]["identifier"] == "http-test"

    current = auth_client.get("/api/auth/me", base_url=BASE)

    assert current.status_code == 200
    assert current.get_json()["user_id"] == response.get_json()["user"]["id"]


def test_login_requires_csrf(auth_client):
    response = auth_client.post(
        "/api/auth/login",
        base_url=BASE,
        json={"identifier": "http-test", "password": "LabDemo2026!"},
    )

    assert response.status_code == 403


def test_wrong_password_returns_401(auth_client):
    assert sign_in(auth_client, "wrong").status_code == 401


def test_anonymous_user_rejected(auth_client):
    response = auth_client.get("/api/auth/me", base_url=BASE)

    assert response.status_code == 401


def test_logout_ends_session(auth_client):
    signed_in = sign_in(auth_client).get_json()

    response = auth_client.post(
        "/api/auth/logout",
        base_url=BASE,
        headers={"X-CSRF-Token": signed_in["csrf_token"]},
    )

    assert response.status_code == 204
    assert auth_client.get("/api/auth/me", base_url=BASE).status_code == 401


def test_logout_requires_csrf(auth_client):
    sign_in(auth_client)

    response = auth_client.post("/api/auth/logout", base_url=BASE)

    assert response.status_code == 403
    assert auth_client.get("/api/auth/me", base_url=BASE).status_code == 200


def test_session_cookie_security(auth_client):
    response = sign_in(auth_client)
    cookies = response.headers.getlist("Set-Cookie")
    session_cookie = next(value for value in cookies if value.startswith("lab_session="))

    assert "Secure" in session_cookie
    assert "HttpOnly" in session_cookie
    assert "SameSite=Lax" in session_cookie
    assert response.headers["Cache-Control"] == "no-store"


def test_test_header_cannot_authenticate(auth_client):
    response = auth_client.get(
        "/api/auth/me",
        base_url=BASE,
        headers={"X-Test-User": "00000000-0000-0000-0000-000000000001"},
    )

    assert response.status_code == 401