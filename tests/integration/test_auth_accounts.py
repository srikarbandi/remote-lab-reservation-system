from uuid import UUID

import pytest

from app.auth.accounts import create_user, update_user
from app.auth.passwords import hash_password, verify_password
from app.auth.services import login
from app.auth.sessions import authenticate
from app.common.errors import ApiError


@pytest.fixture()
def admin_world(db):
    lab = db.execute(
        "INSERT INTO labs (name) VALUES (%s) RETURNING id",
        ("Auth Test Lab",),
    ).fetchone()["id"]

    admin = db.execute(
        """
        INSERT INTO users (identifier, password_hash)
        VALUES (%s, %s)
        RETURNING id
        """,
        ("account-admin", hash_password("LabDemo2026!")),
    ).fetchone()["id"]

    db.execute(
        """
        INSERT INTO lab_memberships (user_id, lab_id, role)
        VALUES (%s, %s, 'Administrator')
        """,
        (admin, lab),
    )

    return {"admin": admin, "lab": lab}


def make_student(db, world):
    return create_user(
        db,
        world["admin"],
        "account-student",
        "StudentDemo2026!",
        world["lab"],
        "Student",
    )


def test_admin_creates_account(db, admin_world):
    user = make_student(db, admin_world)

    stored = db.execute(
        "SELECT password_hash FROM users WHERE identifier = %s",
        ("account-student",),
    ).fetchone()

    assert user["role"] == "Student"
    assert verify_password(stored["password_hash"], "StudentDemo2026!")
    assert "password_hash" not in user


def test_duplicate_identifier_rejected(db, admin_world):
    make_student(db, admin_world)

    with pytest.raises(ApiError) as error:
        make_student(db, admin_world)

    assert error.value.status == 409


def test_student_cannot_create_accounts(db, admin_world):
    student = make_student(db, admin_world)

    with pytest.raises(ApiError) as error:
        create_user(
            db,
            student["id"],
            "another-account",
            "StudentDemo2026!",
            admin_world["lab"],
            "Student",
        )

    assert error.value.status == 403


def test_admin_cannot_manage_other_lab(db, admin_world):
    other_lab = db.execute(
        "INSERT INTO labs (name) VALUES (%s) RETURNING id",
        ("Other Auth Lab",),
    ).fetchone()["id"]

    with pytest.raises(ApiError) as error:
        create_user(
            db,
            admin_world["admin"],
            "other-lab-student",
            "StudentDemo2026!",
            other_lab,
            "Student",
        )

    assert error.value.status == 403


def test_admin_changes_role(db, admin_world):
    student = make_student(db, admin_world)

    updated = update_user(
        db,
        admin_world["admin"],
        student["id"],
        admin_world["lab"],
        role="Technician",
    )

    assert updated["role"] == "Technician"


def test_disabling_revokes_session(db, admin_world):
    student = make_student(db, admin_world)
    signed_in = login(db, "account-student", "StudentDemo2026!")

    update_user(
        db,
        admin_world["admin"],
        student["id"],
        admin_world["lab"],
        active=False,
    )

    assert authenticate(db, signed_in["token"]) is None

    remaining = db.execute(
        """
        SELECT count(*) AS total
        FROM sessions
        WHERE user_id = %s AND revoked_at IS NULL
        """,
        (UUID(student["id"]),),
    ).fetchone()["total"]

    assert remaining == 0
    assert not login(db, "account-student", "StudentDemo2026!")["ok"]


def test_cannot_disable_user_in_unmanaged_lab(db, admin_world):
    student = make_student(db, admin_world)

    other_lab = db.execute(
        "INSERT INTO labs (name) VALUES (%s) RETURNING id",
        ("Shared Account Lab",),
    ).fetchone()["id"]

    db.execute(
        """
        INSERT INTO lab_memberships (user_id, lab_id, role)
        VALUES (%s, %s, 'Student')
        """,
        (UUID(student["id"]), other_lab),
    )

    with pytest.raises(ApiError) as error:
        update_user(
            db,
            admin_world["admin"],
            student["id"],
            admin_world["lab"],
            active=False,
        )

    assert error.value.status == 403


def test_invalid_role_rejected(db, admin_world):
    with pytest.raises(ApiError) as error:
        create_user(
            db,
            admin_world["admin"],
            "invalid-role-user",
            "StudentDemo2026!",
            admin_world["lab"],
            "SuperAdmin",
        )

    assert error.value.status == 422
    