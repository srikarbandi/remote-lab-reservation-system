"""Maintenance blocks (LAB-F-014, DS-Maintenance).

Owner: Sreekar Bandi.

Rules (SRS 2.5, SAD 4.1.2):
- A maintenance block cannot overlap a Pending or Approved reservation. The
  administrator must first resolve affected bookings (cancel with a reason and
  notify the student). Existing valid records are never silently overwritten.
- Overlapping maintenance blocks may coexist; reporting counts their union once.
- Technicians and administrators of the equipment's lab may create, edit and
  remove blocks. Every change follows the equipment row-lock protocol.
"""

from app.audit.services import record_event
from app.common.errors import ApiError
from app.common.locking import lock_equipment
from app.common.permissions import STAFF_ROLES, require_lab_role

HELD_STATUSES = ("Pending", "Approved")
_COLUMNS = "id, equipment_id, created_by, starts_at, ends_at, reason, version"


def _held_overlaps(conn, equipment_id, start, end) -> list[dict]:
    """Pending/Approved reservations overlapping [start, end): starts_at < end and ends_at > start."""
    return conn.execute(
        """
        SELECT id, status, starts_at, ends_at
        FROM reservations
        WHERE equipment_id = %s
          AND status = ANY(%s)
          AND starts_at < %s
          AND ends_at > %s
        ORDER BY starts_at
        """,
        (equipment_id, list(HELD_STATUSES), end, start),
    ).fetchall()


def _reject_if_held(conn, equipment_id, start, end) -> None:
    conflicts = _held_overlaps(conn, equipment_id, start, end)
    if conflicts:
        raise ApiError(
            409,
            "MAINTENANCE_CONFLICT",
            "The interval overlaps held reservations. Resolve those bookings first, then retry.",
            details={"reservation_ids": [str(row["id"]) for row in conflicts]},
        )


def _check_interval(start, end) -> None:
    if start >= end:
        raise ApiError(
            422,
            "INVALID_INTERVAL",
            "The maintenance interval must start before it ends.",
            fields={"start": "Must be before end.", "end": "Must be after start."},
        )


def create_block(conn, actor_id, equipment_id, start, end, reason, request_id=None) -> dict:
    with conn.transaction():
        equipment = lock_equipment(conn, equipment_id)
        require_lab_role(conn, actor_id, equipment["lab_id"], STAFF_ROLES)
        _check_interval(start, end)
        _reject_if_held(conn, equipment_id, start, end)
        block = conn.execute(
            f"""
            INSERT INTO maintenance_blocks (equipment_id, created_by, starts_at, ends_at, reason)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING {_COLUMNS}
            """,
            (equipment_id, actor_id, start, end, reason),
        ).fetchone()
        record_event(
            conn, actor_id, "maintenance.create", "maintenance_block", block["id"], "success", request_id
        )
        return block


def _locked_block(conn, block_id) -> tuple[dict, dict]:
    """Find the block's equipment, take the equipment lock, then re-read the block under it."""
    found = conn.execute("SELECT equipment_id FROM maintenance_blocks WHERE id = %s", (block_id,)).fetchone()
    if found is None:
        raise ApiError(404, "MAINTENANCE_NOT_FOUND", "The maintenance block does not exist.")
    equipment = lock_equipment(conn, found["equipment_id"])
    block = conn.execute(
        f"SELECT {_COLUMNS} FROM maintenance_blocks WHERE id = %s FOR UPDATE", (block_id,)
    ).fetchone()
    if block is None:  # removed while we waited for the lock
        raise ApiError(404, "MAINTENANCE_NOT_FOUND", "The maintenance block does not exist.")
    return equipment, block


def _check_version(block, expected_version) -> None:
    if block["version"] != expected_version:
        raise ApiError(
            409, "STALE_VERSION", "The maintenance block was changed by someone else. Reload and retry."
        )


def update_block(
    conn, actor_id, block_id, expected_version, start=None, end=None, reason=None, request_id=None
) -> dict:
    """Change any of start, end, reason. Omitted fields keep their current value."""
    with conn.transaction():
        equipment, block = _locked_block(conn, block_id)
        require_lab_role(conn, actor_id, equipment["lab_id"], STAFF_ROLES)
        _check_version(block, expected_version)
        new_start = start if start is not None else block["starts_at"]
        new_end = end if end is not None else block["ends_at"]
        new_reason = reason if reason is not None else block["reason"]
        _check_interval(new_start, new_end)
        _reject_if_held(conn, block["equipment_id"], new_start, new_end)
        updated = conn.execute(
            f"""
            UPDATE maintenance_blocks
            SET starts_at = %s, ends_at = %s, reason = %s, version = version + 1
            WHERE id = %s
            RETURNING {_COLUMNS}
            """,
            (new_start, new_end, new_reason, block_id),
        ).fetchone()
        record_event(
            conn, actor_id, "maintenance.update", "maintenance_block", block_id, "success", request_id
        )
        return updated


def delete_block(conn, actor_id, block_id, expected_version, request_id=None) -> None:
    with conn.transaction():
        equipment, block = _locked_block(conn, block_id)
        require_lab_role(conn, actor_id, equipment["lab_id"], STAFF_ROLES)
        _check_version(block, expected_version)
        conn.execute("DELETE FROM maintenance_blocks WHERE id = %s", (block_id,))
        record_event(
            conn, actor_id, "maintenance.delete", "maintenance_block", block_id, "success", request_id
        )
