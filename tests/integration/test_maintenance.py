"""Maintenance blocks against a real database. Covers TC-F-014 and part of TC-EDGE-007."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from lab_factories import add_reservation, count, seed_world

from app.common.errors import ApiError
from app.maintenance import services

H = timedelta(hours=1)
BASE = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)


@pytest.fixture()
def world(db):
    return seed_world(db)


def expect_error(status, code=None):
    return _Expect(status, code)


class _Expect:
    def __init__(self, status, code):
        self.status, self.code = status, code

    def __enter__(self):
        self.ctx = pytest.raises(ApiError)
        self.info = self.ctx.__enter__()
        return self.info

    def __exit__(self, *exc):
        suppressed = self.ctx.__exit__(*exc)
        if suppressed:
            assert self.info.value.status == self.status
            if self.code:
                assert self.info.value.code == self.code
        return suppressed


def create(new_conn, world, actor=None, equipment=None, start=BASE, end=BASE + 2 * H, reason="Calibration"):
    return services.create_block(
        new_conn(), actor or world.tech1, equipment or world.e1, start, end, reason, str(uuid4())
    )


def test_tc_f_014_technician_creates_block_with_audit(new_conn, world, db):
    block = create(new_conn, world)
    assert block["version"] == 1
    assert block["starts_at"] == BASE and block["ends_at"] == BASE + 2 * H
    audit = db.execute("SELECT actor_id, action, target_id, outcome FROM audit_events").fetchall()
    assert len(audit) == 1
    assert audit[0]["action"] == "maintenance.create" and audit[0]["target_id"] == block["id"]
    assert audit[0]["actor_id"] == world.tech1 and audit[0]["outcome"] == "success"


def test_administrator_can_create_block(new_conn, world):
    assert create(new_conn, world, actor=world.admin1)["reason"] == "Calibration"


@pytest.mark.parametrize("status", ["Pending", "Approved"])
def test_held_reservation_prevents_block(new_conn, world, db, status):
    held = add_reservation(db, world.student1, world.e1, BASE + H, BASE + 2 * H, status)
    with expect_error(409, "MAINTENANCE_CONFLICT") as caught:
        create(new_conn, world)
    assert caught.value.details == {"reservation_ids": [str(held)]}
    assert count(db, "maintenance_blocks") == 0
    assert count(db, "audit_events") == 0  # failed attempt leaves no success event


@pytest.mark.parametrize("status", ["Rejected", "Cancelled", "Completed"])
def test_released_reservations_do_not_block(new_conn, world, db, status):
    add_reservation(db, world.student1, world.e1, BASE + H, BASE + 2 * H, status)
    assert create(new_conn, world)["version"] == 1


def test_adjacent_booking_does_not_block(new_conn, world, db):
    # [08:00,10:00) and [12:00,14:00) touch the block [10:00,12:00) but do not overlap it.
    add_reservation(db, world.student1, world.e1, BASE - 2 * H, BASE, "Approved")
    add_reservation(db, world.student1, world.e1, BASE + 2 * H, BASE + 4 * H, "Pending")
    assert create(new_conn, world)["version"] == 1


def test_booking_on_other_equipment_does_not_block(new_conn, world, db):
    add_reservation(db, world.student1, world.e2, BASE, BASE + 2 * H, "Approved")
    assert create(new_conn, world, equipment=world.e1)["version"] == 1


def test_overlapping_maintenance_blocks_may_coexist(new_conn, world, db):
    create(new_conn, world)
    create(new_conn, world, start=BASE + H, end=BASE + 3 * H)
    assert count(db, "maintenance_blocks") == 2


def test_interval_must_start_before_it_ends(new_conn, world):
    with expect_error(422, "INVALID_INTERVAL"):
        create(new_conn, world, start=BASE, end=BASE)
    with expect_error(422, "INVALID_INTERVAL"):
        create(new_conn, world, start=BASE + H, end=BASE)


@pytest.mark.parametrize("who", ["student1", "student2", "admin2", "disabled_admin"])
def test_only_active_staff_of_the_equipment_lab_may_create(new_conn, world, db, who):
    with expect_error(403, "FORBIDDEN"):
        create(new_conn, world, actor=getattr(world, who))
    assert count(db, "maintenance_blocks") == 0


def test_user_without_any_membership_is_denied(new_conn, world, db):
    from lab_factories import add_user

    outsider = add_user(db, "outsider")
    with expect_error(403):
        create(new_conn, world, actor=outsider)


def test_unknown_equipment_is_404(new_conn, world):
    with expect_error(404, "EQUIPMENT_NOT_FOUND"):
        create(new_conn, world, equipment=uuid4())


# --- update -----------------------------------------------------------------


def test_update_changes_fields_and_bumps_version(new_conn, world, db):
    block = create(new_conn, world)
    updated = services.update_block(
        new_conn(),
        world.admin1,
        block["id"],
        1,
        end=BASE + 3 * H,
        reason="Replace lamp",
        request_id=str(uuid4()),
    )
    assert updated["version"] == 2
    assert updated["starts_at"] == BASE  # untouched field kept
    assert updated["ends_at"] == BASE + 3 * H and updated["reason"] == "Replace lamp"
    assert count(db, "audit_events", "action = 'maintenance.update'") == 1


def test_update_cannot_expand_into_a_held_booking(new_conn, world, db):
    block = create(new_conn, world)  # [10:00, 12:00)
    add_reservation(db, world.student1, world.e1, BASE + 3 * H, BASE + 4 * H, "Approved")
    with expect_error(409, "MAINTENANCE_CONFLICT"):
        services.update_block(new_conn(), world.tech1, block["id"], 1, end=BASE + 5 * H)
    row = db.execute("SELECT ends_at, version FROM maintenance_blocks").fetchone()
    assert row["ends_at"] == BASE + 2 * H and row["version"] == 1


def test_update_may_shrink_or_move_to_a_free_interval(new_conn, world, db):
    block = create(new_conn, world)
    add_reservation(db, world.student1, world.e1, BASE + 3 * H, BASE + 4 * H, "Approved")
    moved = services.update_block(new_conn(), world.tech1, block["id"], 1, start=BASE, end=BASE + H)
    assert moved["ends_at"] == BASE + H


def test_update_with_stale_version_is_409(new_conn, world):
    block = create(new_conn, world)
    services.update_block(new_conn(), world.tech1, block["id"], 1, reason="First change")
    with expect_error(409, "STALE_VERSION"):
        services.update_block(new_conn(), world.tech1, block["id"], 1, reason="Second change")


def test_update_validates_resulting_interval(new_conn, world):
    block = create(new_conn, world)
    with expect_error(422, "INVALID_INTERVAL"):
        services.update_block(new_conn(), world.tech1, block["id"], 1, start=BASE + 5 * H)


def test_update_by_wrong_lab_admin_is_403_and_unknown_block_404(new_conn, world):
    block = create(new_conn, world)
    with expect_error(403):
        services.update_block(new_conn(), world.admin2, block["id"], 1, reason="Nope")
    with expect_error(404, "MAINTENANCE_NOT_FOUND"):
        services.update_block(new_conn(), world.tech1, uuid4(), 1, reason="Nope")


# --- delete -----------------------------------------------------------------


def test_delete_removes_block_and_audits(new_conn, world, db):
    block = create(new_conn, world)
    services.delete_block(new_conn(), world.tech1, block["id"], 1, str(uuid4()))
    assert count(db, "maintenance_blocks") == 0
    assert count(db, "audit_events", "action = 'maintenance.delete'") == 1


def test_delete_stale_version_and_permissions(new_conn, world, db):
    block = create(new_conn, world)
    with expect_error(409, "STALE_VERSION"):
        services.delete_block(new_conn(), world.tech1, block["id"], 7)
    with expect_error(403):
        services.delete_block(new_conn(), world.student1, block["id"], 1)
    assert count(db, "maintenance_blocks") == 1


def test_deleting_twice_is_404(new_conn, world):
    block = create(new_conn, world)
    services.delete_block(new_conn(), world.tech1, block["id"], 1)
    with expect_error(404, "MAINTENANCE_NOT_FOUND"):
        services.delete_block(new_conn(), world.tech1, block["id"], 1)
