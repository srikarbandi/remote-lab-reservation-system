"""In-app notifications against a real database. Covers TC-F-015 for the notification service."""

from datetime import datetime, timezone

import pytest
from lab_factories import add_reservation, count, seed_world

from app.notifications import services

START = datetime(2026, 10, 20, 4, 30, tzinfo=timezone.utc)  # 10:00 IST
END = datetime(2026, 10, 20, 6, 30, tzinfo=timezone.utc)  # 12:00 IST


@pytest.fixture()
def world(db):
    return seed_world(db)


def test_create_and_list_own_notification(new_conn, world, db):
    reservation = add_reservation(db, world.student1, world.e1, START, END)
    conn = new_conn()
    with conn.transaction():
        services.create_notification(conn, world.student1, services.SUBMITTED, "Submitted.", reservation)
    page = services.list_notifications(new_conn(), world.student1)
    assert [n["event_type"] for n in page["items"]] == ["SUBMITTED"]
    assert page["items"][0]["reservation_id"] == reservation
    assert page["items"][0]["read_at"] is None
    assert page["has_more"] is False


def test_users_never_see_each_others_notifications(new_conn, world):
    conn = new_conn()
    with conn.transaction():
        services.create_notification(conn, world.student1, services.APPROVED, "For S1 only.")
        services.create_notification(conn, world.student2, services.REJECTED, "For S2 only.")
    mine = services.list_notifications(new_conn(), world.student1)["items"]
    assert [n["message"] for n in mine] == ["For S1 only."]
    assert services.list_notifications(new_conn(), world.admin1)["items"] == []


def test_rolled_back_transaction_leaves_no_notification(new_conn, world, db):
    # TC-EDGE-005: the notification commits or rolls back with the state change it describes.
    conn = new_conn()
    with pytest.raises(RuntimeError), conn.transaction():
        services.create_notification(conn, world.student1, services.SUBMITTED, "Should vanish.")
        raise RuntimeError("simulated failure after the notification insert")
    assert count(db, "notifications") == 0


def test_pagination_newest_first_and_has_more(new_conn, world):
    conn = new_conn()
    for i in range(5):
        with conn.transaction():
            services.create_notification(conn, world.student1, services.CANCELLED, f"message {i}")
    first = services.list_notifications(new_conn(), world.student1, page=1, page_size=2)
    assert [n["message"] for n in first["items"]] == ["message 4", "message 3"]
    assert first["has_more"] is True
    last = services.list_notifications(new_conn(), world.student1, page=3, page_size=2)
    assert [n["message"] for n in last["items"]] == ["message 0"]
    assert last["has_more"] is False


def test_unknown_event_type_is_rejected(new_conn, world):
    with pytest.raises(ValueError):
        services.create_notification(new_conn(), world.student1, "NOT_A_TYPE", "x")


def test_message_builder_uses_lab_time_and_reason():
    text = services.build_message(services.REJECTED, "Oscilloscope", START, END, reason="Class booked")
    assert "Oscilloscope" in text and "10:00-12:00" in text and "20 Oct 2026" in text
    assert text.endswith("Reason: Class booked")
    with pytest.raises(ValueError):
        services.build_message("NOPE", "x", START, END)
