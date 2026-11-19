from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app import create_app
from app.auth.accounts import create_user, update_user
from app.auth.passwords import hash_password
from app.auth.services import login, token_hash
from app.auth.sessions import authenticate

BASE = "https://localhost"
PASSWORD = "StpDemo2026!"


@pytest.fixture()
def stp_world(db, pg_url):
    lab_id = db.execute(
        "INSERT INTO labs (name) VALUES (%s) RETURNING id",
        ("STP Authentication Lab",),
    ).fetchone()["id"]

    admin_id = db.execute(
        "INSERT INTO users (identifier, password_hash) "
        "VALUES (%s, %s) RETURNING id",
        ("stp-admin", hash_password(PASSWORD)),
    ).fetchone()["id"]

    db.execute(
        "INSERT INTO lab_memberships (user_id, lab_id, role) "
        "VALUES (%s, %s, %s)",
        (admin_id, lab_id, "Administrator"),
    )

    student = create_user(
        db, admin_id, "stp-student", PASSWORD, lab_id, "Student"
    )

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "stp-test-secret",
            "DATABASE_URL": pg_url,
            "AUTH_COOKIE_SECURE": True,
        }
    )

    return {
        "lab": lab_id,
        "admin": admin_id,
        "student": UUID(student["id"]),
        "app": app,
    }


def sign_in(client, identifier):
    csrf = client.get(
        "/api/auth/csrf", base_url=BASE
    ).get_json()["csrf_token"]

    response = client.post(
        "/api/auth/login",
        base_url=BASE,
        json={"identifier": identifier, "password": PASSWORD},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    return response.get_json()["csrf_token"]


def test_old_failures_outside_window_reset(db, stp_world):
    for _ in range(4):
        assert login(db, "stp-student", "wrong")["status"] == 401

    db.execute(
        "UPDATE login_attempts "
        "SET window_started = now() - interval '16 minutes' "
        "WHERE identifier = %s",
        ("stp-student",),
    )

    assert login(db, "stp-student", "wrong")["status"] == 401

    attempt = db.execute(
        "SELECT failure_count, locked_until FROM login_attempts "
        "WHERE identifier = %s",
        ("stp-student",),
    ).fetchone()

    assert attempt["failure_count"] == 1
    assert attempt["locked_until"] is None
    assert login(db, "stp-student", PASSWORD)["ok"]


@pytest.mark.parametrize(
    "seconds, expected_valid",
    [(1799, True), (1800, False), (1801, False)],
)
def test_exact_inactivity_boundary(
    db, stp_world, monkeypatch, seconds, expected_valid
):
    import app.auth.sessions as session_module

    result = login(db, "stp-student", PASSWORD)
    fixed = datetime.now(timezone.utc)

    db.execute(
        "UPDATE sessions SET last_activity_at = %s WHERE token_hash = %s",
        (fixed - timedelta(seconds=seconds), token_hash(result["token"])),
    )

    class FixedClock:
        @staticmethod
        def now(tz=None):
            return fixed if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(session_module, "datetime", FixedClock)

    identity = authenticate(db, result["token"])
    assert (identity is not None) is expected_valid


def test_disable_preserves_reservation_history(db, stp_world):
    equipment_id = db.execute(
        "INSERT INTO equipment (lab_id, code, name) "
        "VALUES (%s, %s, %s) RETURNING id",
        (stp_world["lab"], "STP-E1", "STP Equipment"),
    ).fetchone()["id"]

    reservation_id = db.execute(
        "INSERT INTO reservations "
        "(student_id, equipment_id, starts_at, ends_at, purpose) "
        "VALUES (%s, %s, now() + interval '2 days', "
        "now() + interval '2 days 1 hour', %s) RETURNING id",
        (stp_world["student"], equipment_id, "History preservation check"),
    ).fetchone()["id"]

    before = db.execute(
        "SELECT * FROM reservations WHERE id = %s",
        (reservation_id,),
    ).fetchone()

    update_user(
        db,
        stp_world["admin"],
        stp_world["student"],
        stp_world["lab"],
        active=False,
    )

    after = db.execute(
        "SELECT * FROM reservations WHERE id = %s",
        (reservation_id,),
    ).fetchone()

    assert after == before


def test_disable_rejects_existing_http_session(db, stp_world):
    admin_client = stp_world["app"].test_client()
    student_client = stp_world["app"].test_client()

    admin_csrf = sign_in(admin_client, "stp-admin")
    sign_in(student_client, "stp-student")

    assert student_client.get(
        "/api/auth/me", base_url=BASE
    ).status_code == 200

    response = admin_client.patch(
        f"/api/users/{stp_world['student']}",
        base_url=BASE,
        json={"lab_id": str(stp_world["lab"]), "active": False},
        headers={"X-CSRF-Token": admin_csrf},
    )

    assert response.status_code == 200
    assert student_client.get(
        "/api/auth/me", base_url=BASE
    ).status_code == 401


def test_invalid_csrf_does_not_create_account(db, stp_world):
    client = stp_world["app"].test_client()
    sign_in(client, "stp-admin")

    response = client.post(
        "/api/users",
        base_url=BASE,
        json={
            "identifier": "csrf-must-not-exist",
            "password": PASSWORD,
            "lab_id": str(stp_world["lab"]),
            "role": "Student",
        },
        headers={"X-CSRF-Token": "invalid-token"},
    )

    assert response.status_code == 403
    assert db.execute(
        "SELECT id FROM users WHERE identifier = %s",
        ("csrf-must-not-exist",),
    ).fetchone() is None


def test_authentication_log_and_audit_secret_hygiene(
    db, stp_world, caplog, capsys
):
    caplog.set_level("DEBUG")
    client = stp_world["app"].test_client()

    csrf = client.get(
        "/api/auth/csrf", base_url=BASE
    ).get_json()["csrf_token"]

    failed = client.post(
        "/api/auth/login",
        base_url=BASE,
        json={"identifier": "stp-student", "password": "WrongStpSecret!"},
        headers={"X-CSRF-Token": csrf},
    )
    assert failed.status_code == 401

    csrf = sign_in(client, "stp-student")
    session_token = client.get_cookie("lab_session").value

    response = client.post(
        "/api/auth/logout",
        base_url=BASE,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 204

    events = db.execute(
        "SELECT * FROM audit_events WHERE actor_id = %s",
        (stp_world["student"],),
    ).fetchall()

    assert any(event["action"] == "LOGIN" for event in events)
    assert any(event["action"] == "LOGOUT" for event in events)

    captured = capsys.readouterr()
    recorded = caplog.text + captured.out + captured.err + str(events)

    for secret in (PASSWORD, "WrongStpSecret!", session_token, csrf):
        assert secret not in recorded