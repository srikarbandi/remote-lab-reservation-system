"""End-to-end HTTP checks (JSON in, JSON out) with a real database behind the routes."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from lab_factories import add_reservation, add_weekly_opening, count, seed_world

from app.common.errors import ApiError
from app.reservations import services as reservation_services

UTC = timezone.utc
H = timedelta(hours=1)
START = datetime(2026, 10, 20, 4, 30, tzinfo=UTC)
END = START + 2 * H


@pytest.fixture()
def world(db):
    return seed_world(db)


def as_user(user):
    return {"X-Test-User": str(user)}


def test_tc_f_014_maintenance_create_update_delete_over_http(db_client, world, db):
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


def test_tc_f_014_maintenance_conflict_names_the_blocking_reservations(db_client, world, db):
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


def test_tc_f_014_student_cannot_create_maintenance_over_http(db_client, world, db):
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


def test_tc_f_016_usage_over_http(db_client, world, db):
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


def test_tc_f_016_usage_no_show_and_rejection_over_http(db_client, world, db):
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


def test_tc_f_017_report_over_http(db_client, world, db):
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


def test_tc_f_015_notifications_over_http_show_only_own(db_client, world, db):
    db.execute(
        "INSERT INTO notifications (user_id, event_type, message) VALUES (%s, 'APPROVED', 'mine'), (%s, 'REJECTED', 'theirs')",
        (world.student1, world.student2),
    )
    response = db_client.get("/api/notifications", headers=as_user(world.student1))
    assert response.status_code == 200
    body = response.get_json()
    assert [n["message"] for n in body["items"]] == ["mine"]
    assert body["page"] == 1 and body["page_size"] == 20 and body["has_more"] is False


def test_tc_f_014_delete_accepts_expected_version_in_the_json_body(db_client, world, db):
    created = db_client.post(
        "/api/maintenance",
        json={
            "equipment_id": str(world.e1),
            "start": "2026-10-20T10:00:00+05:30",
            "end": "2026-10-20T12:00:00+05:30",
            "reason": "Calibration",
        },
        headers=as_user(world.tech1),
    )
    block = created.get_json()

    stale = db_client.delete(
        f"/api/maintenance/{block['id']}", json={"expected_version": 99}, headers=as_user(world.admin1)
    )
    assert stale.status_code == 409 and stale.get_json()["error"]["code"] == "STALE_VERSION"
    assert count(db, "maintenance_blocks") == 1

    removed = db_client.delete(
        f"/api/maintenance/{block['id']}",
        json={"expected_version": block["version"]},
        headers=as_user(world.admin1),
    )
    assert removed.status_code == 204 and removed.data == b""
    assert count(db, "maintenance_blocks") == 0



def test_tc_f_006_overlapping_booking_returns_409(db_client, world, db):
    future_start = datetime(2027, 1, 20, 4, 30, tzinfo=UTC)
    future_end = future_start + 2 * H

    add_weekly_opening(db, world.l1, future_start.weekday())

    add_reservation(
        db,
        world.student1,
        world.e1,
        future_start,
        future_end,
        "Approved",
    )

    response = db_client.post(
        "/api/reservations",
        json={
            "equipment_id": str(world.e1),
            "start": future_start.isoformat(),
            "end": future_end.isoformat(),
            "purpose": "Another booking",
        },
        headers={
            **as_user(world.student2),
            "Idempotency-Key": "conflict-test-student-2",
        },
    )

    assert response.status_code == 409, response.get_json()
    assert response.get_json()["error"]["code"] == "SLOT_CONFLICT"

def test_tc_f_006_idempotency_key_replay_creates_one_reservation(db_client, world, db):
    future_start = datetime(2027, 1, 20, 4, 30, tzinfo=UTC)
    future_end = future_start + 2 * H

    add_weekly_opening(db, world.l1, future_start.weekday())

    payload = {
        "equipment_id": str(world.e1),
        "start": future_start.isoformat(),
        "end": future_end.isoformat(),
        "purpose": "Idempotency test booking",
    }
    headers = {
        **as_user(world.student1),
        "Idempotency-Key": "idempotency-replay-test",
    }

    first = db_client.post(
        "/api/reservations", json=payload, headers=headers
    )
    second = db_client.post(
        "/api/reservations", json=payload, headers=headers
    )

    assert first.status_code == 201, first.get_json()
    assert second.status_code == 201, second.get_json()
    assert first.get_json()["id"] == second.get_json()["id"]
    assert count(db, "reservations") == 1

def test_tc_f_009_stale_reservation_version_returns_409(db_client, world, db):
    future_start = datetime(2027, 1, 20, 4, 30, tzinfo=UTC)
    future_end = future_start + 2 * H

    reservation_id = add_reservation(
        db,
        world.student1,
        world.e1,
        future_start,
        future_end,
        "Approved",
        version=2,
    )

    response = db_client.post(
        f"/api/reservations/{reservation_id}/cancel",
        json={"expected_version": 1},
        headers=as_user(world.student1),
    )

    assert response.status_code == 409, response.get_json()
    assert response.get_json()["error"]["code"] == "STALE_VERSION"

    saved = db.execute(
        "SELECT status, version FROM reservations WHERE id = %s",
        (reservation_id,),
    ).fetchone()

    assert saved["status"] == "Approved"
    assert saved["version"] == 2

def test_tc_f_006_booking_outside_opening_hours_returns_422(db_client, world, db):
    future_start = datetime(2027, 1, 20, 3, 0, tzinfo=UTC)
    future_end = future_start + H

    add_weekly_opening(db, world.l1, future_start.weekday())

    response = db_client.post(
        "/api/reservations",
        json={
            "equipment_id": str(world.e1),
            "start": future_start.isoformat(),
            "end": future_end.isoformat(),
            "purpose": "Outside opening hours test",
        },
        headers={
            **as_user(world.student1),
            "Idempotency-Key": "outside-opening-hours-test",
        },
    )

    assert response.status_code == 422, response.get_json()
    assert response.get_json()["error"]["code"] == "OUTSIDE_OPENING_HOURS"
    assert count(db, "reservations") == 0

def test_tc_f_007_concurrent_booking_only_one_succeeds(db, new_conn, world):
    future_start = datetime(2027, 1, 20, 4, 30, tzinfo=UTC)
    future_end = future_start + 2 * H

    add_weekly_opening(db, world.l1, future_start.weekday())

    barrier = Barrier(2)

    def book(student_id, key):
        conn = new_conn()
        try:
            barrier.wait()
            result = reservation_services.create_reservation(
                conn,
                student_id,
                world.e1,
                future_start,
                future_end,
                "Concurrent booking test",
                key,
            )
            return ("success", result)
        except ApiError as exc:
            return ("error", exc.status, exc.code)
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            book, world.student1, "concurrent-student-1"
        )
        second = executor.submit(
            book, world.student2, "concurrent-student-2"
        )

        results = [first.result(), second.result()]

    successes = [r for r in results if r[0] == "success"]
    failures = [r for r in results if r[0] == "error"]

    assert len(successes) == 1, results
    assert len(failures) == 1, results
    assert failures[0][1:] == (409, "SLOT_CONFLICT")
    assert count(db, "reservations") == 1
