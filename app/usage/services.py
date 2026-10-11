"""Actual usage and completion (LAB-F-016, DS-Usage).

Owner: Sreekar Bandi.

Recording usage completes an Approved reservation after its end time. A no-show
is a Completed reservation with no usage timestamps and zero minutes. The
validation rules are pure and live in ``app.usage.rules``; this module adds the
transaction, the equipment lock, the permission check and the audit event.
"""

from datetime import datetime, timezone

from app.audit.services import record_event
from app.common.errors import ApiError
from app.common.locking import lock_equipment
from app.common.permissions import STAFF_ROLES, require_lab_role
from app.usage.rules import compute_usage


def record_usage(
    conn,
    actor_id,
    reservation_id,
    expected_version: int,
    used_start=None,
    used_end=None,
    no_show: bool = False,
    request_id=None,
    now: datetime | None = None,
) -> dict:
    """Complete an Approved, ended reservation. ``now`` is injectable for clock-controlled tests."""
    now = now or datetime.now(timezone.utc)
    with conn.transaction():
        found = conn.execute(
            "SELECT equipment_id FROM reservations WHERE id = %s", (reservation_id,)
        ).fetchone()
        if found is None:
            raise ApiError(404, "RESERVATION_NOT_FOUND", "The reservation does not exist.")
        # Equipment first, then the reservation (same order as approval, SAD 4.1.2).
        equipment = lock_equipment(conn, found["equipment_id"])
        reservation = conn.execute(
            "SELECT id, status, version, starts_at, ends_at FROM reservations WHERE id = %s FOR UPDATE",
            (reservation_id,),
        ).fetchone()
        require_lab_role(conn, actor_id, equipment["lab_id"], STAFF_ROLES)
        if reservation["version"] != expected_version:
            raise ApiError(
                409, "STALE_VERSION", "The reservation was changed by someone else. Reload and retry."
            )
        result = compute_usage(
            reservation["starts_at"],
            reservation["ends_at"],
            reservation["status"],
            now,
            used_start=used_start,
            used_end=used_end,
            no_show=no_show,
        )
        conn.execute(
            """
            INSERT INTO usage_records (reservation_id, used_start, used_end, used_minutes, recorded_by)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (reservation_id, result.used_start, result.used_end, result.used_minutes, actor_id),
        )
        updated = conn.execute(
            """
            UPDATE reservations
            SET status = 'Completed', version = version + 1, updated_at = now()
            WHERE id = %s
            RETURNING id, status, version
            """,
            (reservation_id,),
        ).fetchone()
        record_event(conn, actor_id, "usage.record", "reservation", reservation_id, "success", request_id)
        return {**updated, "used_minutes": result.used_minutes}
