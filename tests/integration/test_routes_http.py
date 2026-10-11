"""End-to-end HTTP checks (JSON in, JSON out) with a real database behind the routes."""

from datetime import datetime, timedelta, timezone

import pytest
from lab_factories import add_reservation, add_weekly_opening, count, seed_world

UTC = timezone.utc
H = timedelta(hours=1)
START = datetime(2026, 10, 20, 4, 30, tzinfo=UTC)  # 10:00 IST
END = START + 2 * H


@pytest.fixture()
def world(db):
    return seed_world(db)


def as_user(user):
    return {"X-Test-User": str(user)}


def test_maintenance_create_update_delete_over_http(db_client, world, db):
    created = db_client.post(
        "/api/maintenance",
        json={
            "equipment_id": str(world.e1),
            "start": "2026-10-20T10:00:00+05:30",
            "end": "2026-10-20T12:00:00+05:30",
            "reason": "  Calibration  ",
        },
        headers=as_user(world.tech1),
    )
    assert created.status_code == 201
    block = created.get_json()
    assert block["reason"] == "Calibration" and block["version"] == 1
    assert block["start"] == "2026-10-20T04:30:00+00:00"

    patched = db_client.patch(
        f"/api/maintenance/{block['id']}",
        json={"expected_version": 1, "reason": "Lamp replacement"},
        headers=as_user(world.admin1),
    )
    assert patched.status_code == 200 and patched.get_json()["version"] == 2

    stale = db_client.patch(
        f"/api/maintenance/{block['id']}",
        json={"expected_version": 1, "reason": "again"},
        headers=as_user(world.admin1),
    )
    assert stale.status_code == 409 and stale.get_json()["error"]["code"] == "STALE_VERSION"

    removed = db_client.delete(
        f"/api/maintenance/{block['id']}?expected_version=2", headers=as_user(world.tech1)
    )
    assert removed.status_code == 204 and removed.data == b""
    assert count(db, "maintenance_blocks") == 0


def test_maintenance_conflict_names_the_blocking_reservations(db_client, world, db):
    held = add_reservation(db, world.student1, world.e1, START + H, START + 2 * H, "Approved")
    response = db_client.post(
        "/api/maintenance",
        json={
            "equipment_id": str(world.e1),
            "start": "2026-10-20T10:00:00+05:30",
            "end": "2026-10-20T12:00:00+05:30",
            "reason": "Calibration",
        },
        headers=as_user(world.tech1),
    )
    assert response.status_code == 409
    error = response.get_json()["error"]
    assert error["code"] == "MAINTENANCE_CONFLICT" and error["details"] == {"reservation_ids": [str(held)]}


def test_student_cannot_create_maintenance_over_http(db_client, world, db):
    response = db_client.post(
        "/api/maintenance",
        json={
            "equipment_id": str(world.e1),
            "start": "2026-10-20T10:00:00+05:30",
            "end": "2026-10-20T12:00:00+05:30",
            "reason": "Sneaky",
        },
        headers=as_user(world.student1),
    )
    assert response.status_code == 403 and count(db, "maintenance_blocks") == 0


def test_usage_over_http(db_client, world, db):
    past_start = datetime.now(UTC) - 5 * H
    past_end = past_start + 2 * H
    reservation = add_reservation(db, world.student1, world.e1, past_start, past_end, "Approved", version=2)
    response = db_client.post(
        f"/api/reservations/{reservation}/usage",
        json={
            "expected_version": 2,
            "used_start": past_start.isoformat(),
            "used_end": (past_end - H // 2).isoformat(),
        },
        headers=as_user(world.tech1),
    )
    assert response.status_code == 200
    assert response.get_json() == {
        "id": str(reservation),
        "status": "Completed",
        "version": 3,
        "used_minutes": 90,
    }


def test_usage_no_show_and_rejection_over_http(db_client, world, db):
    past_start = datetime.now(UTC) - 5 * H
    reservation = add_reservation(
        db, world.student1, world.e1, past_start, past_start + H, "Approved", version=1
    )
    too_long = db_client.post(
        f"/api/reservations/{reservation}/usage",
        json={
            "expected_version": 1,
            "used_start": past_start.isoformat(),
            "used_end": (past_start + 3 * H).isoformat(),
        },
        headers=as_user(world.tech1),
    )
    assert too_long.status_code == 422 and too_long.get_json()["error"]["code"] == "INVALID_USAGE"
    no_show = db_client.post(
        f"/api/reservations/{reservation}/usage",
        json={"expected_version": 1, "no_show": True},
        headers=as_user(world.tech1),
    )
    assert no_show.status_code == 200 and no_show.get_json()["used_minutes"] == 0


def test_report_over_http(db_client, world, db):
    for weekday in range(5):
        add_weekly_opening(db, world.l1, weekday)
    response = db_client.get(
        f"/api/reports/utilization?lab_id={world.l1}&from_date=2026-10-05&to_date=2026-10-05",
        headers=as_user(world.admin1),
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["timezone"] == "Asia/Kolkata"
    assert [e["code"] for e in body["equipment"]] == ["E1", "E2"]
    assert body["equipment"][0]["bookable_minutes"] == 480

    forbidden = db_client.get(
        f"/api/reports/utilization?lab_id={world.l1}&from_date=2026-10-05&to_date=2026-10-05",
        headers=as_user(world.student1),
    )
    assert forbidden.status_code == 403


def test_notifications_over_http_show_only_own(db_client, world, db):
    db.execute(
        "INSERT INTO notifications (user_id, event_type, message) VALUES (%s, 'APPROVED', 'mine'), (%s, 'REJECTED', 'theirs')",
        (world.student1, world.student2),
    )
    response = db_client.get("/api/notifications", headers=as_user(world.student1))
    assert response.status_code == 200
    body = response.get_json()
    assert [n["message"] for n in body["items"]] == ["mine"]
    assert body["page"] == 1 and body["page_size"] == 20 and body["has_more"] is False
