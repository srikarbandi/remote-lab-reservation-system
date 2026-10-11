"""Usage recording against a real database. Covers TC-F-016."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from lab_factories import add_reservation, count, seed_world

from app.common.errors import ApiError
from app.usage import services

H = timedelta(hours=1)
START = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)
END = START + 2 * H
NOW = END + H  # the reservation has ended


@pytest.fixture()
def world(db):
    return seed_world(db)


@pytest.fixture()
def approved(db, world):
    return add_reservation(db, world.student1, world.e1, START, END, "Approved", version=2)


def record(new_conn, world, reservation, actor=None, version=2, **kwargs):
    kwargs.setdefault("now", NOW)
    return services.record_usage(
        new_conn(), actor or world.tech1, reservation, version, request_id=str(uuid4()), **kwargs
    )


def fails(status, code=None):
    class _Ctx:
        def __enter__(self):
            self.ctx = pytest.raises(ApiError)
            self.info = self.ctx.__enter__()
            return self.info

        def __exit__(self, *exc):
            ok = self.ctx.__exit__(*exc)
            if ok:
                assert self.info.value.status == status
                if code:
                    assert self.info.value.code == code
            return ok

    return _Ctx()


def state(db, reservation):
    row = db.execute("SELECT status, version FROM reservations WHERE id = %s", (reservation,)).fetchone()
    return row["status"], row["version"], count(db, "usage_records", "reservation_id = %s", (reservation,))


def test_records_usage_and_completes(new_conn, world, db, approved):
    result = record(new_conn, world, approved, used_start=START + timedelta(minutes=5), used_end=END - H // 2)
    assert (result["status"], result["version"], result["used_minutes"]) == ("Completed", 3, 85)
    row = db.execute("SELECT used_minutes, recorded_by FROM usage_records").fetchone()
    assert row["used_minutes"] == 85 and row["recorded_by"] == world.tech1
    assert state(db, approved) == ("Completed", 3, 1)
    assert count(db, "audit_events", "action = 'usage.record'") == 1


def test_no_show_is_completed_with_zero_minutes_and_null_times(new_conn, world, db, approved):
    result = record(new_conn, world, approved, no_show=True, actor=world.admin1)
    assert result["used_minutes"] == 0
    row = db.execute("SELECT used_start, used_end, used_minutes FROM usage_records").fetchone()
    assert (row["used_start"], row["used_end"], row["used_minutes"]) == (None, None, 0)
    assert state(db, approved)[0] == "Completed"


def test_usage_longer_than_reservation_is_rejected_and_changes_nothing(new_conn, world, db, approved):
    with fails(422, "INVALID_USAGE"):
        record(new_conn, world, approved, used_start=START, used_end=END + timedelta(minutes=1))
    assert state(db, approved) == ("Approved", 2, 0)
    assert count(db, "audit_events") == 0


def test_cannot_record_before_the_end(new_conn, world, db, approved):
    with fails(409, "RESERVATION_NOT_ENDED"):
        record(new_conn, world, approved, no_show=True, now=END - timedelta(minutes=1))
    assert state(db, approved) == ("Approved", 2, 0)


@pytest.mark.parametrize("status", ["Pending", "Rejected", "Cancelled", "Completed"])
def test_only_approved_can_be_completed(new_conn, world, db, status):
    reservation = add_reservation(db, world.student1, world.e1, START, END, status, version=2)
    with fails(409, "INVALID_STATE"):
        record(new_conn, world, reservation, no_show=True)
    assert state(db, reservation)[0] == status


def test_recording_twice_is_rejected(new_conn, world, approved):
    record(new_conn, world, approved, no_show=True)
    with fails(409):
        record(new_conn, world, approved, no_show=True, version=3)


def test_stale_version_is_409(new_conn, world, db, approved):
    with fails(409, "STALE_VERSION"):
        record(new_conn, world, approved, no_show=True, version=1)
    assert state(db, approved) == ("Approved", 2, 0)


@pytest.mark.parametrize("who", ["student1", "admin2", "disabled_admin"])
def test_unauthorized_users_are_denied_and_nothing_changes(new_conn, world, db, approved, who):
    with fails(403, "FORBIDDEN"):
        record(new_conn, world, approved, actor=getattr(world, who), no_show=True)
    assert state(db, approved) == ("Approved", 2, 0)


def test_unknown_reservation_is_404(new_conn, world):
    with fails(404, "RESERVATION_NOT_FOUND"):
        record(new_conn, world, uuid4(), no_show=True)
