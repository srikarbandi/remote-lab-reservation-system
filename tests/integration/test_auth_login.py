import pytest

from app.auth.passwords import hash_password
from app.auth.services import login, token_hash


@pytest.fixture()
def account(db):
    return db.execute(
        """
        INSERT INTO users (identifier, password_hash)
        VALUES (%s, %s)
        RETURNING id, identifier
        """,
        ("spoorthy-test", hash_password("LabDemo2026!")),
    ).fetchone()


def test_login_creates_hashed_session(db, account):
    result = login(db, account["identifier"], "LabDemo2026!")

    assert result["ok"]
    assert result["user"]["id"] == str(account["id"])

    stored = db.execute(
        "SELECT token_hash FROM sessions WHERE user_id = %s",
        (account["id"],),
    ).fetchone()

    assert stored["token_hash"] == token_hash(result["token"])
    assert stored["token_hash"] != result["token"]


def test_wrong_password_creates_no_session(db, account):
    result = login(db, account["identifier"], "wrong")

    assert not result["ok"]
    assert result["status"] == 401
    assert db.execute("SELECT count(*) AS total FROM sessions").fetchone()["total"] == 0


def test_unknown_account_returns_same_error(db, account):
    known = login(db, account["identifier"], "wrong")
    unknown = login(db, "missing-account", "wrong")

    assert known == unknown


def test_disabled_account_cannot_login(db, account):
    db.execute(
        "UPDATE users SET active = false WHERE id = %s",
        (account["id"],),
    )

    result = login(db, account["identifier"], "LabDemo2026!")

    assert not result["ok"]
    assert result["status"] == 401


def test_five_failures_block_correct_password(db, account):
    for _ in range(5):
        result = login(db, account["identifier"], "wrong")
        assert result["status"] == 401

    result = login(db, account["identifier"], "LabDemo2026!")

    assert not result["ok"]
    assert result["status"] == 429


def test_success_clears_failure_counter(db, account):
    login(db, account["identifier"], "wrong")
    result = login(db, account["identifier"], "LabDemo2026!")

    assert result["ok"]
    assert db.execute(
        "SELECT identifier FROM login_attempts WHERE identifier = %s",
        (account["identifier"],),
    ).fetchone() is None


def test_expired_lock_allows_login(db, account):
    for _ in range(5):
        login(db, account["identifier"], "wrong")

    db.execute(
        """
        UPDATE login_attempts
        SET locked_until = now() - interval '1 minute'
        WHERE identifier = %s
        """,
        (account["identifier"],),
    )

    assert login(db, account["identifier"], "LabDemo2026!")["ok"]


def test_success_records_audit_event(db, account):
    login(db, account["identifier"], "LabDemo2026!")

    event = db.execute(
        """
        SELECT action, outcome
        FROM audit_events
        WHERE actor_id = %s
        """,
        (account["id"],),
    ).fetchone()

    assert event["action"] == "LOGIN"
    assert event["outcome"] == "SUCCESS"