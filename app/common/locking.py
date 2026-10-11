"""Equipment row lock: step 2 of the booking transaction protocol (SAD 4.1.1).

Every operation that can change what is bookable for an equipment item
(booking, approval, cancellation, maintenance, equipment status, usage
completion) must call ``lock_equipment`` first, inside its own transaction,
and then re-validate. Because all writers take the same row lock, a later
transaction always validates against the earlier committed result. Locking only
existing reservations would not protect an empty schedule.

If several equipment rows must be locked, lock them in sorted ID order.
"""

import psycopg.errors

from app.common.errors import ApiError

LOCK_TIMEOUT_MS = 5000


def lock_equipment(conn, equipment_id) -> dict:
    """Lock and return the equipment row (id, lab_id, code, name, active).

    Must be called inside ``with conn.transaction():``. Raises 404 if the
    equipment does not exist and 503 if the lock wait times out.
    """
    conn.execute("SELECT set_config('lock_timeout', %s, true)", (f"{LOCK_TIMEOUT_MS}ms",))
    try:
        row = conn.execute(
            "SELECT id, lab_id, code, name, active FROM equipment WHERE id = %s FOR UPDATE",
            (equipment_id,),
        ).fetchone()
    except psycopg.errors.LockNotAvailable:
        raise ApiError(
            503, "LOCK_TIMEOUT", "The equipment is busy with another request. Please retry."
        ) from None
    if row is None:
        raise ApiError(404, "EQUIPMENT_NOT_FOUND", "The requested equipment does not exist.")
    return row
