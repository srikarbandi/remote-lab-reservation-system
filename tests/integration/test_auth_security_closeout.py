from datetime import datetime, timedelta, timezone

import pytest
from lab_factories import add_reservation, seed_world

from app import create_app
from app.auth.passwords import hash_password

BASE = "https://localhost"
PASSWORD = "SecurityCloseout2026!"


@pytest.fixture()
def security_world(db, pg_url):
    world = seed_world(db)
    password_hash = hash_password(PASSWORD)

    db.execute(
        "UPDATE users SET password_hash = %s",
        (password_hash,),
    )

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "security-closeout-test-only",
            "DATABASE_URL": pg_url,
            "AUTH_COOKIE_SECURE": True,
        }
    )

    return world, app


def signed_client(app, identifier):
    client = app.test_client()
    csrf = client.get(
        "/api/auth/csrf", base_url=BASE
    ).get_json()["csrf_token"]

    response = client.post(
        "/api/auth/login",
        base_url=BASE,
        json={"identifier": identifier, "password": PASSWORD},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200, response.get_json()
    return client, response.get_json()["csrf_token"]


def test_student_cannot_create_maintenance_with_real_session(
    db, security_world
):
    world, app = security_world
    client, csrf = signed_client(app, "s1")
    start = datetime.now(timezone.utc) + timedelta(days=2)

    response = client.post(
        "/api/maintenance",
        base_url=BASE,
        json={
            "equipment_id": str(world.e1),
            "start": start.isoformat(),
            "end": (start + timedelta(hours=1)).isoformat(),
            "reason": "Unauthorized maintenance attempt",
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 403, response.get_json()
    assert db.execute(
        "SELECT count(*) AS n FROM maintenance_blocks"
    ).fetchone()["n"] == 0


def test_technician_cannot_approve_with_real_session(
    db, security_world
):
    world, app = security_world
    start = datetime.now(timezone.utc) + timedelta(days=2)
    reservation_id = add_reservation(
        db,
        world.student1,
        world.e1,
        start,
        start + timedelta(hours=1),
    )

    before = db.execute(
        "SELECT * FROM reservations WHERE id = %s",
        (reservation_id,),
    ).fetchone()

    client, csrf = signed_client(app, "t1")
    response = client.post(
        f"/api/reservations/{reservation_id}/decision",
        base_url=BASE,
        json={"decision": "Approved", "expected_version": 1},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 403, response.get_json()
    assert db.execute(
        "SELECT * FROM reservations WHERE id = %s",
        (reservation_id,),
    ).fetchone() == before


def test_admin_cannot_modify_other_lab_equipment(
    db, security_world
):
    world, app = security_world
    before = db.execute(
        "SELECT * FROM equipment WHERE id = %s",
        (world.e3,),
    ).fetchone()

    client, csrf = signed_client(app, "a1")
    response = client.patch(
        f"/api/equipment/{world.e3}",
        base_url=BASE,
        json={"name": "Unauthorized cross-lab change"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 403, response.get_json()
    assert db.execute(
        "SELECT * FROM equipment WHERE id = %s",
        (world.e3,),
    ).fetchone() == before


def test_student_history_excludes_other_student(
    db, security_world
):
    world, app = security_world
    start = datetime.now(timezone.utc) + timedelta(days=2)

    own_id = add_reservation(
        db, world.student1, world.e1,
        start, start + timedelta(hours=1),
    )
    other_id = add_reservation(
        db, world.student2, world.e2,
        start, start + timedelta(hours=1),
    )

    client, _ = signed_client(app, "s1")
    response = client.get(
        "/api/reservations?scope=mine",
        base_url=BASE,
    )

    assert response.status_code == 200, response.get_json()
    ids = {row["id"] for row in response.get_json()["items"]}
    assert str(own_id) in ids
    assert str(other_id) not in ids


@pytest.mark.parametrize(
    "change, field",
    [
        ({"equipment_id": "not-a-uuid"}, "equipment_id"),
        ({"purpose": "x" * 501}, "purpose"),
        ({"role": "Administrator"}, "role"),
        ({"student_id": "forged-owner"}, "student_id"),
        ({"start": "2026-12-01T10:00:00"}, "start"),
    ],
)
def test_invalid_booking_changes_no_reservations(
    db, security_world, change, field
):
    world, app = security_world
    client, csrf = signed_client(app, "s1")
    start = datetime.now(timezone.utc) + timedelta(days=2)

    body = {
        "equipment_id": str(world.e1),
        "start": start.isoformat(),
        "end": (start + timedelta(hours=1)).isoformat(),
        "purpose": "Validation check",
    }
    body.update(change)

    response = client.post(
        "/api/reservations",
        base_url=BASE,
        json=body,
        headers={
            "X-CSRF-Token": csrf,
            "Idempotency-Key": f"invalid-booking-{field}",
        },
    )

    assert response.status_code == 422, response.get_json()
    assert field in response.get_json()["error"]["fields"]
    assert db.execute(
        "SELECT count(*) AS n FROM reservations"
    ).fetchone()["n"] == 0