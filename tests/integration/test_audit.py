"""Audit event helper against a real database. Covers TC-F-019 for the shared record_event helper."""

from uuid import uuid4

import pytest
from lab_factories import seed_world

from app.audit.services import record_event


@pytest.fixture()
def world(db):
    return seed_world(db)


def test_tc_f_019_event_stores_actor_target_outcome_and_request_id(new_conn, world, db):
    target, request_id = uuid4(), uuid4()
    conn = new_conn()
    with conn.transaction():
        record_event(
            conn, world.admin1, "maintenance.create", "maintenance_block", target, "success", str(request_id)
        )
    row = db.execute("SELECT * FROM audit_events").fetchone()
    assert row["actor_id"] == world.admin1
    assert (row["action"], row["target_type"], row["outcome"]) == (
        "maintenance.create",
        "maintenance_block",
        "success",
    )
    assert row["target_id"] == target and row["request_id"] == request_id
    assert row["created_at"] is not None


def test_tc_f_019_request_id_that_is_not_a_uuid_is_stored_as_null(new_conn, world, db):
    conn = new_conn()
    with conn.transaction():
        record_event(conn, world.admin1, "usage.record", "reservation", uuid4(), "success", "not-a-uuid")
    row = db.execute("SELECT request_id, outcome FROM audit_events").fetchone()
    assert row["request_id"] is None and row["outcome"] == "success"


def test_tc_f_019_audit_row_rolls_back_with_the_state_change(new_conn, world, db):
    conn = new_conn()
    with pytest.raises(RuntimeError), conn.transaction():
        record_event(conn, world.admin1, "maintenance.create", "maintenance_block", uuid4(), "success")
        raise RuntimeError("simulated failure after the audit insert")
    assert db.execute("SELECT count(*) AS n FROM audit_events").fetchone()["n"] == 0
