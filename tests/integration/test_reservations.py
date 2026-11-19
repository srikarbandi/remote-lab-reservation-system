
"""Reservation cancellation integration tests."""

from datetime import datetime, timezone

import pytest
from lab_factories import add_reservation, seed_world

from app.common.errors import ApiError
from app.notifications import services as notification_services
from app.reservations import services as reservation_services

START = datetime(2026, 12, 1, 4, 30, tzinfo=timezone.utc)
END = datetime(2026, 12, 1, 6, 30, tzinfo=timezone.utc)


@pytest.fixture()
def world(db):
    return seed_world(db)


@pytest.mark.parametrize("status", ["Pending", "Approved"])
def test_admin_can_cancel_reservation_with_reason(
    db, new_conn, world, status
):
    reservation_id = add_reservation(
        db, world.student1, world.e1, START, END, status=status
    )

    conn = new_conn()
    result = reservation_services.cancel_reservation(
        conn,
        world.admin1,
        reservation_id,
        1,
        reason="Equipment maintenance",
    )

    assert result["status"] == "Cancelled"
    assert result["version"] == 2

    saved = db.execute(
        "SELECT decision_reason FROM reservations WHERE id = %s",
        (reservation_id,),
    ).fetchone()
    assert saved["decision_reason"] == "Equipment maintenance"

    notifications = notification_services.list_notifications(
        new_conn(), world.student1
    )["items"]

    assert len(notifications) == 1
    assert notifications[0]["event_type"] == "MAINTENANCE_CANCELLED"
    assert notifications[0]["reservation_id"] == reservation_id
    assert "Equipment maintenance" in notifications[0]["message"]


def test_admin_cannot_cancel_without_reason(db, new_conn, world):
    reservation_id = add_reservation(
        db, world.student1, world.e1, START, END
    )

    with pytest.raises(ApiError):
        reservation_services.cancel_reservation(
            new_conn(),
            world.admin1,
            reservation_id,
            1,
            reason="",
        )


def test_student_can_still_cancel_own_reservation(db, new_conn, world):
    reservation_id = add_reservation(
        db, world.student1, world.e1, START, END
    )

    result = reservation_services.cancel_reservation(
        new_conn(),
        world.student1,
        reservation_id,
        1,
    )

    assert result["status"] == "Cancelled"

    notifications = notification_services.list_notifications(
        new_conn(), world.student1
    )["items"]

    assert len(notifications) == 1
    assert notifications[0]["event_type"] == "CANCELLED"


def test_admin_from_another_lab_cannot_cancel_reservation(
    db, new_conn, world
):
    reservation_id = add_reservation(
        db, world.student1, world.e1, START, END
    )

    with pytest.raises(ApiError):
        reservation_services.cancel_reservation(
            new_conn(),
            world.admin2,
            reservation_id,
            1,
            reason="Equipment maintenance",
        )
