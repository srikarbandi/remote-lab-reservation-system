
"""Approval business rules (LAB-F-010 to LAB-F-012)."""

from datetime import datetime, timezone

from app.audit.services import record_event
from app.common.errors import ApiError
from app.common.locking import lock_equipment
from app.common.permissions import ADMINISTRATOR, require_lab_role
from app.notifications.services import (
    APPROVED,
    REJECTED,
    build_message,
    create_notification,
)
from app.reservations.services import (
    _check_conflicts,
    _validate_opening_hours,
)

_COLUMNS = (
    "id, student_id, equipment_id, starts_at, ends_at, status, version, "
    "purpose, decision_reason, decided_by"
)


def decide_reservation(
    conn,
    actor_id,
    reservation_id,
    decision,
    expected_version,
    reason=None,
    request_id=None,
):
    if decision not in {"Approved", "Rejected"}:
        raise ApiError(
            422,
            "INVALID_FIELDS",
            "decision must be Approved or Rejected.",
            fields={"decision": "Must be Approved or Rejected."},
        )

    if decision == "Rejected" and not reason:
        raise ApiError(
            422,
            "INVALID_FIELDS",
            "A rejection reason is required.",
            fields={"reason": "This field is required when rejecting."},
        )

    with conn.transaction():
        found = conn.execute(
            "SELECT equipment_id FROM reservations WHERE id = %s",
            (reservation_id,),
        ).fetchone()

        if found is None:
            raise ApiError(
                404,
                "RESERVATION_NOT_FOUND",
                "The reservation does not exist.",
            )

        equipment = lock_equipment(conn, found["equipment_id"])

        require_lab_role(
            conn,
            actor_id,
            equipment["lab_id"],
            {ADMINISTRATOR},
        )

        reservation = conn.execute(
            f"SELECT {_COLUMNS} FROM reservations "
            "WHERE id = %s FOR UPDATE",
            (reservation_id,),
        ).fetchone()

        if reservation is None:
            raise ApiError(
                404,
                "RESERVATION_NOT_FOUND",
                "The reservation does not exist.",
            )

        if reservation["version"] != expected_version:
            raise ApiError(
                409,
                "STALE_VERSION",
                "The reservation changed. Reload and try again.",
            )

        if reservation["status"] != "Pending":
            raise ApiError(
                409,
                "INVALID_STATE",
                "Only Pending reservations can be decided.",
            )

        if decision == "Approved":
            if reservation["starts_at"] <= datetime.now(timezone.utc):
                raise ApiError(
                    409,
                    "RESERVATION_EXPIRED",
                    "A reservation cannot be approved after it starts.",
                )

            lab = conn.execute(
                "SELECT timezone FROM labs WHERE id = %s",
                (equipment["lab_id"],),
            ).fetchone()

            _validate_opening_hours(
                conn,
                equipment["lab_id"],
                lab["timezone"],
                reservation["starts_at"],
                reservation["ends_at"],
            )

            _check_conflicts(
                conn,
                equipment["id"],
                reservation["starts_at"],
                reservation["ends_at"],
                exclude_id=reservation_id,
            )

            event_type = APPROVED
        else:
            event_type = REJECTED

        updated = conn.execute(
            """
            UPDATE reservations
            SET status = %s,
                decision_reason = %s,
                decided_by = %s,
                version = version + 1,
                updated_at = now()
            WHERE id = %s
            RETURNING id, status, version
            """,
            (decision, reason, actor_id, reservation_id),
        ).fetchone()

        lab = conn.execute(
            "SELECT timezone FROM labs WHERE id = %s",
            (equipment["lab_id"],),
        ).fetchone()

        message = build_message(
            event_type,
            equipment["name"],
            reservation["starts_at"],
            reservation["ends_at"],
            reason,
            lab["timezone"],
        )

        create_notification(
            conn,
            reservation["student_id"],
            event_type,
            message,
            reservation_id,
        )

        record_event(
            conn,
            actor_id,
            f"reservation.{decision.lower()}",
            "reservation",
            reservation_id,
            "success",
            request_id,
        )

        return updated
