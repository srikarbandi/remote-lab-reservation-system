
"""Reservation business rules and transaction boundaries (LAB-F-006 to LAB-F-009)."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.audit.services import record_event
from app.common.errors import ApiError
from app.common.locking import lock_equipment
from app.common.permissions import ADMINISTRATOR, STUDENT, require_lab_role
from app.notifications.services import (
    CANCELLED,
    SUBMITTED,
    build_message,
    create_notification,
)

HELD_STATUSES = ("Pending", "Approved")

_COLUMNS = (
    "id, student_id, equipment_id, starts_at, ends_at, status, version, "
    "purpose, decision_reason, decided_by, created_at, updated_at"
)


def _opening_windows(conn, lab_id, tz, start, end):
    """Return UTC opening windows intersecting the requested interval."""
    first_day = start.astimezone(tz).date()
    last_day = (end - timedelta(microseconds=1)).astimezone(tz).date()

    weekly_rows = conn.execute(
        """
        SELECT weekday, open_time, close_time
        FROM lab_opening_intervals
        WHERE lab_id = %s AND weekday IS NOT NULL
        """,
        (lab_id,),
    ).fetchall()

    override_rows = conn.execute(
        """
        SELECT override_date, open_time, close_time
        FROM lab_opening_intervals
        WHERE lab_id = %s AND override_date BETWEEN %s AND %s
        """,
        (lab_id, first_day, last_day),
    ).fetchall()

    weekly = {}
    for row in weekly_rows:
        weekly.setdefault(row["weekday"], []).append(
            (row["open_time"], row["close_time"])
        )

    overrides = {}
    for row in override_rows:
        overrides.setdefault(row["override_date"], []).append(
            (row["open_time"], row["close_time"])
        )

    windows = []
    day = first_day

    while day <= last_day:
        rows = overrides.get(day, weekly.get(day.weekday(), []))

        for opens, closes in rows:
            if opens is None or closes is None or opens >= closes:
                continue

            windows.append(
                (
                    datetime.combine(day, opens, tzinfo=tz).astimezone(
                        timezone.utc
                    ),
                    datetime.combine(day, closes, tzinfo=tz).astimezone(
                        timezone.utc
                    ),
                )
            )

        day += timedelta(days=1)

    return windows


def _validate_opening_hours(conn, lab_id, timezone_name, start, end):
    tz = ZoneInfo(timezone_name)
    windows = _opening_windows(conn, lab_id, tz, start, end)

    cursor = start

    for opens, closes in sorted(windows):
        if closes <= cursor:
            continue

        if opens > cursor:
            break

        cursor = max(cursor, closes)

        if cursor >= end:
            return

    raise ApiError(
        422,
        "OUTSIDE_OPENING_HOURS",
        "The reservation must fall entirely within the lab's opening hours.",
        fields={
            "start": "Choose a time within the lab's opening hours.",
            "end": "Choose a time within the lab's opening hours.",
        },
    )


def _check_conflicts(conn, equipment_id, start, end, exclude_id=None):
    reservation_sql = """
        SELECT id FROM reservations
        WHERE equipment_id = %s AND status = ANY(%s)
          AND starts_at < %s AND ends_at > %s
    """

    params = [equipment_id, list(HELD_STATUSES), end, start]

    if exclude_id is not None:
        reservation_sql += " AND id <> %s"
        params.append(exclude_id)

    conflict = conn.execute(
        reservation_sql + " LIMIT 1",
        params,
    ).fetchone()

    if conflict:
        raise ApiError(
            409,
            "SLOT_CONFLICT",
            "The equipment is already reserved for part of this time slot.",
            details={"reservation_id": str(conflict["id"])},
        )

    maintenance = conn.execute(
        """
        SELECT id FROM maintenance_blocks
        WHERE equipment_id = %s
          AND starts_at < %s
          AND ends_at > %s
        LIMIT 1
        """,
        (equipment_id, end, start),
    ).fetchone()

    if maintenance:
        raise ApiError(
            409,
            "MAINTENANCE_CONFLICT",
            "The equipment is blocked for maintenance during this time slot.",
            details={"maintenance_block_id": str(maintenance["id"])},
        )


def create_reservation(
    conn,
    actor_id,
    equipment_id,
    start,
    end,
    purpose,
    idempotency_key,
    request_id=None,
):
    if start >= end:
        raise ApiError(
            422,
            "INVALID_INTERVAL",
            "The reservation must start before it ends.",
            fields={
                "start": "Must be before end.",
                "end": "Must be after start.",
            },
        )

    if start <= datetime.now(timezone.utc):
        raise ApiError(
            422,
            "START_NOT_IN_FUTURE",
            "Reservation start must be in the future.",
            fields={"start": "Must be in the future."},
        )

    if not idempotency_key or len(idempotency_key) > 128:
        raise ApiError(
            400,
            "INVALID_IDEMPOTENCY_KEY",
            "Idempotency-Key header must contain 1 to 128 characters.",
        )

    request_data = {
        "equipment_id": str(equipment_id),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "purpose": purpose,
    }

    request_hash = hashlib.sha256(
        json.dumps(
            request_data,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    with conn.transaction():
        equipment = lock_equipment(conn, equipment_id)

        require_lab_role(
            conn,
            actor_id,
            equipment["lab_id"],
            {STUDENT},
        )

        if not equipment["active"]:
            raise ApiError(
                409,
                "EQUIPMENT_INACTIVE",
                "This equipment is not currently bookable.",
            )

        prior = conn.execute(
            """
            SELECT request_hash, response_code, response_body
            FROM idempotency_records
            WHERE user_id = %s AND operation = %s AND key = %s
            """,
            (actor_id, "reservation.create", idempotency_key),
        ).fetchone()

        if prior:
            if prior["request_hash"] != request_hash:
                raise ApiError(
                    409,
                    "IDEMPOTENCY_KEY_REUSED",
                    "This Idempotency-Key was already used for a different request.",
                )

            return prior["response_body"]

        lab = conn.execute(
            "SELECT timezone FROM labs WHERE id = %s",
            (equipment["lab_id"],),
        ).fetchone()

        _validate_opening_hours(
            conn,
            equipment["lab_id"],
            lab["timezone"],
            start,
            end,
        )

        _check_conflicts(conn, equipment_id, start, end)

        reservation = conn.execute(
            f"""
            INSERT INTO reservations
                (student_id, equipment_id, starts_at, ends_at, purpose)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING {_COLUMNS}
            """,
            (actor_id, equipment_id, start, end, purpose),
        ).fetchone()

        response = {
            "id": str(reservation["id"]),
            "status": "Pending",
            "version": 1,
        }

        conn.execute(
            """
            INSERT INTO idempotency_records
                (user_id, operation, key, request_hash,
                 response_code, response_body)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                actor_id,
                "reservation.create",
                idempotency_key,
                request_hash,
                201,
                json.dumps(response),
            ),
        )

        message = build_message(
            SUBMITTED,
            equipment["name"],
            start,
            end,
            timezone_name=lab["timezone"],
        )

        create_notification(
            conn,
            actor_id,
            SUBMITTED,
            message,
            reservation["id"],
        )

        record_event(
            conn,
            actor_id,
            "reservation.submit",
            "reservation",
            reservation["id"],
            "success",
            request_id,
        )

        return response


def list_reservations(
    conn,
    actor_id,
    scope="mine",
    lab_id=None,
    status=None,
    page=1,
    page_size=20,
):
    if scope == "mine":
        where = ["r.student_id = %s"]
        params = [actor_id]

    elif scope == "lab":
        if lab_id is None:
            raise ApiError(
                422,
                "INVALID_FIELDS",
                "lab_id is required for lab scope.",
                fields={"lab_id": "This field is required."},
            )

        require_lab_role(
            conn,
            actor_id,
            lab_id,
            {ADMINISTRATOR},
        )

        where = ["e.lab_id = %s"]
        params = [lab_id]

    else:
        raise ApiError(
            422,
            "INVALID_FIELDS",
            "scope must be 'mine' or 'lab'.",
            fields={"scope": "Must be mine or lab."},
        )

    if status:
        if status not in {
            "Pending",
            "Approved",
            "Rejected",
            "Cancelled",
            "Completed",
        }:
            raise ApiError(
                422,
                "INVALID_FIELDS",
                "Unknown reservation status.",
                fields={"status": "Choose a valid status."},
            )

        where.append("r.status = %s")
        params.append(status)

    clause = " AND ".join(where)

    total = conn.execute(
        f"SELECT count(*) AS total FROM reservations r "
        f"JOIN equipment e ON e.id = r.equipment_id "
        f"WHERE {clause}",
        params,
    ).fetchone()["total"]

    rows = conn.execute(
        f"""
        SELECT r.id, r.student_id, r.equipment_id, r.starts_at, r.ends_at,
               r.status, r.version, r.purpose, r.decision_reason, r.decided_by,
               r.created_at, r.updated_at, e.name AS equipment_name,
               e.code AS equipment_code
        FROM reservations r
        JOIN equipment e ON e.id = r.equipment_id
        WHERE {clause}
        ORDER BY r.starts_at DESC, r.id DESC
        LIMIT %s OFFSET %s
        """,
        params + [page_size, (page - 1) * page_size],
    ).fetchall()

    return {
        "items": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def cancel_reservation(
    conn,
    actor_id,
    reservation_id,
    expected_version,
    request_id=None,
):
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

        reservation = conn.execute(
            f"SELECT {_COLUMNS} FROM reservations WHERE id = %s FOR UPDATE",
            (reservation_id,),
        ).fetchone()

        if reservation is None:
            raise ApiError(
                404,
                "RESERVATION_NOT_FOUND",
                "The reservation does not exist.",
            )

        if reservation["student_id"] != actor_id:
            raise ApiError(
                403,
                "FORBIDDEN",
                "You can only cancel your own reservations.",
            )

        require_lab_role(
            conn,
            actor_id,
            equipment["lab_id"],
            {STUDENT},
        )

        if reservation["version"] != expected_version:
            raise ApiError(
                409,
                "STALE_VERSION",
                "The reservation changed. Reload and try again.",
            )

        if reservation["status"] not in HELD_STATUSES:
            raise ApiError(
                409,
                "INVALID_STATE",
                "Only Pending or Approved reservations can be cancelled.",
            )

        if reservation["starts_at"] <= datetime.now(timezone.utc):
            raise ApiError(
                409,
                "CANCELLATION_CLOSED",
                "A reservation cannot be cancelled after it starts.",
            )

        updated = conn.execute(
            """
            UPDATE reservations
            SET status = 'Cancelled',
                version = version + 1,
                updated_at = now()
            WHERE id = %s
            RETURNING id, status, version
            """,
            (reservation_id,),
        ).fetchone()

        lab = conn.execute(
            "SELECT timezone FROM labs WHERE id = %s",
            (equipment["lab_id"],),
        ).fetchone()

        message = build_message(
            CANCELLED,
            equipment["name"],
            reservation["starts_at"],
            reservation["ends_at"],
            timezone_name=lab["timezone"],
        )

        create_notification(
            conn,
            actor_id,
            CANCELLED,
            message,
            reservation_id,
        )

        record_event(
            conn,
            actor_id,
            "reservation.cancel",
            "reservation",
            reservation_id,
            "success",
            request_id,
        )

        return updated
