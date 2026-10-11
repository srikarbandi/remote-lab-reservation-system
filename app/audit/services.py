"""Audit events (LAB-F-019, DS-Audit).

Minimal shared helper so every module can record events from day one. The team
still needs to agree the final owner and any extra fields.

Each event stores actor, timestamp, action, target, outcome and request ID, and
must be inserted inside the same transaction as the state change it describes.
Never record passwords, tokens or session secrets.
"""

from uuid import UUID


def _as_uuid_or_none(value):
    if value is None:
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except ValueError:
        return None


def record_event(conn, actor_id, action, target_type, target_id, outcome, request_id=None) -> None:
    """Insert one audit row using the caller's connection and transaction.

    ``request_id`` that is not a valid UUID is stored as NULL rather than failing the request.
    """
    conn.execute(
        """
        INSERT INTO audit_events (actor_id, action, target_type, target_id, outcome, request_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (actor_id, action, target_type, target_id, outcome, _as_uuid_or_none(request_id)),
    )
