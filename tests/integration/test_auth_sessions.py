import pytest

from app.auth.passwords import hash_password
from app.auth.services import login, token_hash
from app.auth.sessions import authenticate, logout


@pytest.fixture()
def signed_in(db):
    user = db.execute(
        """
        INSERT INTO users (identifier, password_hash)
        VALUES (%s, %s)
        RETURNING id
        """,
        ("session-test", hash_password("LabDemo2026!")),
    ).fetchone()

    result = login(db, "session-test", "LabDemo2026!")

    return {"user_id": user["id"], "token": result["token"]}


def test_valid_session_identifies_user(db, signed_in):
    identity = authenticate(db, signed_in["token"])

    assert identity["user_id"] == signed_in["user_id"]


def test_unknown_token_rejected(db):
    assert authenticate(db, "unknown-token") is None


def test_idle_session_expires(db, signed_in):
    db.execute(
        """
        UPDATE sessions
        SET last_activity_at = now() - interval '31 minutes'
        WHERE token_hash = %s
        """,
        (token_hash(signed_in["token"]),),
    )

    assert authenticate(db, signed_in["token"]) is None

    session = db.execute(
        "SELECT revoked_at FROM sessions WHERE token_hash = %s",
        (token_hash(signed_in["token"]),),
    ).fetchone()

    assert session["revoked_at"] is not None


def test_valid_session_refreshes_activity(db, signed_in):
    old = db.execute(
        """
        UPDATE sessions
        SET last_activity_at = now() - interval '10 minutes'
        WHERE token_hash = %s
        RETURNING last_activity_at
        """,
        (token_hash(signed_in["token"]),),
    ).fetchone()["last_activity_at"]

    assert authenticate(db, signed_in["token"]) is not None

    new = db.execute(
        "SELECT last_activity_at FROM sessions WHERE token_hash = %s",
        (token_hash(signed_in["token"]),),
    ).fetchone()["last_activity_at"]

    assert new > old


def test_disabled_user_session_rejected(db, signed_in):
    db.execute(
        "UPDATE users SET active = false WHERE id = %s",
        (signed_in["user_id"],),
    )

    assert authenticate(db, signed_in["token"]) is None


def test_logout_revokes_session(db, signed_in):
    assert logout(db, signed_in["token"])
    assert authenticate(db, signed_in["token"]) is None
    assert not logout(db, signed_in["token"])


def test_logout_records_audit_event(db, signed_in):
    logout(db, signed_in["token"])

    event = db.execute(
        """
        SELECT outcome FROM audit_events
        WHERE actor_id = %s AND action = 'LOGOUT'
        """,
        (signed_in["user_id"],),
    ).fetchone()

    assert event["outcome"] == "SUCCESS"