
from zoneinfo import ZoneInfo

import psycopg

from app.audit.services import record_event
from app.common.errors import ApiError
from app.common.locking import lock_equipment
from app.common.permissions import ADMINISTRATOR, require_lab_role
from app.common.validation import clean_text
from app.reporting.calculations import (
    merge_intervals,
    opening_windows,
    range_bounds,
)


def list_equipment(conn, user_id, name="", lab_id=None, page=1, page_size=20):
    user = conn.execute(
        "SELECT active FROM users WHERE id = %s",
        (user_id,)
    ).fetchone()

    if user is None or not user["active"]:
        raise ApiError(403, "FORBIDDEN", "Active account required.")

    conditions = ["e.active = true"]
    params = []

    if name:
        escaped = name.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        conditions.append("e.name ILIKE %s ESCAPE '!'")
        params.append(f"%{escaped}%")

    if lab_id is not None:
        conditions.append("e.lab_id = %s")
        params.append(lab_id)

    where_clause = " AND ".join(conditions)

    total = conn.execute(
        f"""
        SELECT COUNT(*) AS total
        FROM equipment e
        WHERE {where_clause}
        """,
        params
    ).fetchone()["total"]

    offset = (page - 1) * page_size

    rows = conn.execute(
        f"""
        SELECT e.id, e.code, e.name, e.description,
               e.active, e.lab_id, l.name AS lab_name
        FROM equipment e
        JOIN labs l ON e.lab_id = l.id
        WHERE {where_clause}
        ORDER BY e.name, e.code
        LIMIT %s OFFSET %s
        """,
        params + [page_size, offset]
    ).fetchall()

    return rows, total


def subtract_intervals(windows, blocks):
    free = []
    merged_blocks = merge_intervals(blocks)

    for start, end in windows:
        current = start

        for blocked_start, blocked_end in merged_blocks:
            if blocked_end <= current:
                continue

            if blocked_start >= end:
                break

            if blocked_start > current:
                free.append((current, min(blocked_start, end)))

            current = max(current, blocked_end)

            if current >= end:
                break

        if current < end:
            free.append((current, end))

    return free


def format_intervals(intervals, tz):
    return [
        {
            "start": start.astimezone(tz).isoformat(),
            "end": end.astimezone(tz).isoformat()
        }
        for start, end in intervals
    ]


def get_availability(conn, user_id, equipment_id, selected_date):
    user = conn.execute(
        "SELECT active FROM users WHERE id = %s",
        (user_id,)
    ).fetchone()

    if user is None or not user["active"]:
        raise ApiError(403, "FORBIDDEN", "Active account required.")

    equipment = conn.execute(
        """
        SELECT e.id, e.code, e.name, e.active,
               e.lab_id, l.name AS lab_name, l.timezone
        FROM equipment e
        JOIN labs l ON l.id = e.lab_id
        WHERE e.id = %s
        """,
        (equipment_id,)
    ).fetchone()

    if equipment is None:
        raise ApiError(
            404,
            "EQUIPMENT_NOT_FOUND",
            "The requested equipment does not exist."
        )

    tz = ZoneInfo(equipment["timezone"])

    weekly_rows = conn.execute(
        """
        SELECT weekday, open_time, close_time
        FROM lab_opening_intervals
        WHERE lab_id = %s AND weekday IS NOT NULL
        """,
        (equipment["lab_id"],)
    ).fetchall()

    override_rows = conn.execute(
        """
        SELECT override_date, open_time, close_time
        FROM lab_opening_intervals
        WHERE lab_id = %s AND override_date = %s
        """,
        (equipment["lab_id"], selected_date)
    ).fetchall()

    weekly = [
        (row["weekday"], row["open_time"], row["close_time"])
        for row in weekly_rows
    ]

    overrides = [
        (row["override_date"], row["open_time"], row["close_time"])
        for row in override_rows
    ]

    windows = opening_windows(
        tz, selected_date, selected_date, weekly, overrides
    )

    day_start, day_end = range_bounds(
        tz, selected_date, selected_date
    )

    reservation_rows = conn.execute(
        """
        SELECT starts_at, ends_at
        FROM reservations
        WHERE equipment_id = %s
          AND status IN ('Pending', 'Approved')
          AND starts_at < %s
          AND ends_at > %s
        """,
        (equipment_id, day_end, day_start)
    ).fetchall()

    maintenance_rows = conn.execute(
        """
        SELECT starts_at, ends_at
        FROM maintenance_blocks
        WHERE equipment_id = %s
          AND starts_at < %s
          AND ends_at > %s
        """,
        (equipment_id, day_end, day_start)
    ).fetchall()

    reserved = [
        (row["starts_at"], row["ends_at"])
        for row in reservation_rows
    ]

    maintenance = [
        (row["starts_at"], row["ends_at"])
        for row in maintenance_rows
    ]

    reserved = merge_intervals(reserved)
    maintenance = merge_intervals(maintenance)

    all_blocks = merge_intervals(reserved + maintenance)

    free = subtract_intervals(windows, all_blocks)

    if not equipment["active"]:
        free = []

    return {
        "equipment_id": str(equipment["id"]),
        "equipment_code": equipment["code"],
        "equipment_name": equipment["name"],
        "lab_id": str(equipment["lab_id"]),
        "lab_name": equipment["lab_name"],
        "date": selected_date.isoformat(),
        "timezone": equipment["timezone"],
        "active": equipment["active"],
        "opening_hours": format_intervals(windows, tz),
        "reserved": format_intervals(reserved, tz),
        "maintenance": format_intervals(maintenance, tz),
        "available": format_intervals(free, tz)
    }


def equipment_data(row):
    return {
        "id": str(row["id"]),
        "lab_id": str(row["lab_id"]),
        "code": row["code"],
        "name": row["name"],
        "description": row["description"],
        "active": row["active"]
    }


def create_equipment(conn, actor_id, lab_id, code, name, description="", request_id=None):
    code = clean_text(code, "code")
    name = clean_text(name, "name")

    if not isinstance(description, str) or len(description) > 500:
        raise ApiError(422, "INVALID_FIELDS", "Invalid description.")

    try:
        with conn.transaction():
            lab = conn.execute(
                "SELECT id FROM labs WHERE id = %s",
                (lab_id,)
            ).fetchone()

            if lab is None:
                raise ApiError(404, "LAB_NOT_FOUND", "Lab does not exist.")

            require_lab_role(conn, actor_id, lab_id, {ADMINISTRATOR})

            row = conn.execute(
                """
                INSERT INTO equipment (lab_id, code, name, description)
                VALUES (%s, %s, %s, %s)
                RETURNING id, lab_id, code, name, description, active
                """,
                (lab_id, code, name, description.strip())
            ).fetchone()

            record_event(
                conn, actor_id, "equipment.create",
                "equipment", row["id"], "success", request_id
            )

            return equipment_data(row)

    except psycopg.errors.UniqueViolation:
        raise ApiError(
            409, "DUPLICATE_CODE", "Equipment code already exists."
        ) from None


def update_equipment(conn, actor_id, equipment_id, changes, request_id=None):
    if not changes:
        raise ApiError(422, "INVALID_FIELDS", "No changes provided.")

    permitted = {"code", "name", "description", "active"}

    if set(changes) - permitted:
        raise ApiError(422, "INVALID_FIELDS", "Unexpected equipment fields.")

    values = {}

    for field in ("code", "name"):
        if field in changes:
            values[field] = clean_text(changes[field], field)

    if "description" in changes:
        description = changes["description"]
        if not isinstance(description, str) or len(description) > 500:
            raise ApiError(422, "INVALID_FIELDS", "Invalid description.")
        values["description"] = description.strip()

    if "active" in changes:
        if not isinstance(changes["active"], bool):
            raise ApiError(422, "INVALID_FIELDS", "Active must be true or false.")
        values["active"] = changes["active"]

    try:
        with conn.transaction():
            equipment = lock_equipment(conn, equipment_id)

            require_lab_role(
                conn, actor_id, equipment["lab_id"], {ADMINISTRATOR}
            )

            if values.get("active") is False:
                held = conn.execute(
                    """
                    SELECT id FROM reservations
                    WHERE equipment_id = %s
                      AND status IN ('Pending', 'Approved')
                    LIMIT 1
                    """,
                    (equipment_id,)
                ).fetchone()

                if held is not None:
                    raise ApiError(
                        409,
                        "ACTIVE_RESERVATIONS",
                        "Resolve Pending or Approved bookings before deactivation."
                    )

            fields = list(values)
            assignments = ", ".join(f"{field} = %s" for field in fields)
            parameters = [values[field] for field in fields]

            row = conn.execute(
                f"""
                UPDATE equipment
                SET {assignments}
                WHERE id = %s
                RETURNING id, lab_id, code, name, description, active
                """,
                parameters + [equipment_id]
            ).fetchone()

            record_event(
                conn, actor_id, "equipment.update",
                "equipment", equipment_id, "success", request_id
            )

            return equipment_data(row)

    except psycopg.errors.UniqueViolation:
        raise ApiError(
            409, "DUPLICATE_CODE", "Equipment code already exists."
        ) from None

