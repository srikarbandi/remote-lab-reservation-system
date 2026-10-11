"""Equipment row-lock behaviour with real concurrent connections.

Covers TC-EDGE-003 (booking versus maintenance race) and the lock-timeout contract
(503, SAD 4.2.1). The "booking" side below follows the booking transaction protocol
(SAD 4.1.1) so these tests also pin down the contract the reservations module must keep.
"""

import threading
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from lab_factories import add_equipment, count, seed_world

from app.common import locking
from app.common.errors import ApiError
from app.common.locking import lock_equipment
from app.maintenance import services as maintenance

H = timedelta(hours=1)
BASE = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)


@pytest.fixture()
def world(db):
    return seed_world(db)


def book(conn, equipment_id, student_id, start, end):
    """Reference booking transaction: lock, re-validate against maintenance and held bookings, insert."""
    with conn.transaction():
        lock_equipment(conn, equipment_id)
        clash = conn.execute(
            """
            SELECT 1 FROM maintenance_blocks WHERE equipment_id = %s AND starts_at < %s AND ends_at > %s
            UNION ALL
            SELECT 1 FROM reservations
            WHERE equipment_id = %s AND status IN ('Pending', 'Approved') AND starts_at < %s AND ends_at > %s
            """,
            (equipment_id, end, start, equipment_id, end, start),
        ).fetchone()
        if clash:
            raise ApiError(409, "SLOT_CONFLICT", "This equipment is unavailable for the selected interval.")
        return conn.execute(
            "INSERT INTO reservations (student_id, equipment_id, starts_at, ends_at, purpose) "
            "VALUES (%s, %s, %s, %s, 'race test') RETURNING id",
            (student_id, equipment_id, start, end),
        ).fetchone()["id"]


def test_maintenance_waits_for_the_equipment_lock_then_revalidates(new_conn, world, db):
    """Deterministic TC-EDGE-003: a booking committed while maintenance waits must block the block."""
    holder = new_conn()
    outcome = {}

    def run_maintenance():
        try:
            outcome["block"] = maintenance.create_block(
                new_conn(), world.tech1, world.e1, BASE, BASE + 2 * H, "Calibration", str(uuid4())
            )
        except ApiError as exc:
            outcome["error"] = exc

    with holder.transaction():
        lock_equipment(holder, world.e1)  # booking transaction is in flight, holding the row lock
        worker = threading.Thread(target=run_maintenance)
        worker.start()
        time.sleep(0.5)
        assert worker.is_alive(), "maintenance must wait for the equipment lock"
        holder.execute(
            "INSERT INTO reservations (student_id, equipment_id, starts_at, ends_at, purpose) "
            "VALUES (%s, %s, %s, %s, 'in-flight booking')",
            (world.student1, world.e1, BASE + H, BASE + 3 * H),
        )
    worker.join(timeout=10)

    assert "block" not in outcome, "maintenance saw a stale empty schedule"
    assert outcome["error"].status == 409 and outcome["error"].code == "MAINTENANCE_CONFLICT"
    assert count(db, "maintenance_blocks") == 0 and count(db, "reservations") == 1


def test_booking_waits_for_maintenance_and_is_rejected(new_conn, world, db):
    """The mirror image: maintenance is in flight, the booking must see its block."""
    holder = new_conn()
    outcome = {}

    def run_booking():
        try:
            outcome["id"] = book(new_conn(), world.e1, world.student1, BASE + H, BASE + 3 * H)
        except ApiError as exc:
            outcome["error"] = exc

    with holder.transaction():
        lock_equipment(holder, world.e1)
        worker = threading.Thread(target=run_booking)
        worker.start()
        time.sleep(0.5)
        assert worker.is_alive(), "booking must wait for the equipment lock"
        holder.execute(
            "INSERT INTO maintenance_blocks (equipment_id, created_by, starts_at, ends_at, reason) "
            "VALUES (%s, %s, %s, %s, 'in-flight maintenance')",
            (world.e1, world.tech1, BASE, BASE + 2 * H),
        )
    worker.join(timeout=10)

    assert outcome["error"].code == "SLOT_CONFLICT"
    assert count(db, "reservations") == 0 and count(db, "maintenance_blocks") == 1


def race_once(new_conn, world, equipment):
    """Run one booking and one overlapping maintenance request at the same instant."""
    barrier = threading.Barrier(2)
    results = {}

    def run_booking():
        conn = new_conn()
        barrier.wait()
        try:
            book(conn, equipment, world.student1, BASE, BASE + 2 * H)
            results["booking"] = "ok"
        except ApiError as exc:
            results["booking"] = exc.code

    def run_maintenance():
        conn = new_conn()
        barrier.wait()
        try:
            maintenance.create_block(conn, world.tech1, equipment, BASE + H, BASE + 3 * H, "Race", None)
            results["maintenance"] = "ok"
        except ApiError as exc:
            results["maintenance"] = exc.code

    threads = [threading.Thread(target=run_booking), threading.Thread(target=run_maintenance)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    return results


def test_racing_booking_and_maintenance_never_both_win(new_conn, world, db):
    """TC-EDGE-003 with synchronized independent connections, repeated on fresh equipment."""
    for round_number in range(20):
        equipment = add_equipment(db, world.l1, f"RACE{round_number}")
        results = race_once(new_conn, world, equipment)
        wins = [name for name, value in results.items() if value == "ok"]
        assert len(wins) == 1, f"round {round_number}: {results}"
        blocks = count(db, "maintenance_blocks", "equipment_id = %s", (equipment,))
        held = count(db, "reservations", "equipment_id = %s", (equipment,))
        assert blocks + held == 1


def test_lock_timeout_returns_503_and_changes_nothing(new_conn, world, db, monkeypatch):
    monkeypatch.setattr(locking, "LOCK_TIMEOUT_MS", 300)
    holder = new_conn()
    with holder.transaction():
        lock_equipment(holder, world.e1)
        with pytest.raises(ApiError) as caught:
            maintenance.create_block(new_conn(), world.tech1, world.e1, BASE, BASE + H, "Blocked", None)
    assert (caught.value.status, caught.value.code) == (503, "LOCK_TIMEOUT")
    assert count(db, "maintenance_blocks") == 0


def test_different_equipment_does_not_contend(new_conn, world):
    holder = new_conn()
    with holder.transaction():
        lock_equipment(holder, world.e1)
        started = time.monotonic()
        maintenance.create_block(new_conn(), world.tech1, world.e2, BASE, BASE + H, "Other item", None)
        assert time.monotonic() - started < 2
