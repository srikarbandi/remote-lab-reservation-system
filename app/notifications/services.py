"""In-app notifications (LAB-F-015, DS-Notification).

Owner: Sreekar Bandi.

Notifications are persistent rows. They are written with ``create_notification``
inside the *caller's* transaction, together with the state change they describe,
so a rollback never leaves a misleading message and a failed event produces none
(SAD 4.1). Other modules call this helper; they do not insert into the table.

Event types: submission, approval, rejection, cancellation and the cancellation
of a booking to resolve a maintenance block.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

SUBMITTED = "SUBMITTED"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
CANCELLED = "CANCELLED"
MAINTENANCE_CANCELLED = "MAINTENANCE_CANCELLED"
EVENT_TYPES = frozenset({SUBMITTED, APPROVED, REJECTED, CANCELLED, MAINTENANCE_CANCELLED})

_HEADLINES = {
    SUBMITTED: "Your request has been submitted and is Pending approval",
    APPROVED: "Your request has been approved",
    REJECTED: "Your request was rejected",
    CANCELLED: "Your reservation was cancelled",
    MAINTENANCE_CANCELLED: "Your reservation was cancelled because of equipment maintenance",
}


def build_message(
    event_type: str,
    equipment_name: str,
    starts_at: datetime,
    ends_at: datetime,
    reason: str | None = None,
    timezone_name: str = "Asia/Kolkata",
) -> str:
    """Consistent wording, with times shown in the lab timezone."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown notification event type: {event_type}")
    tz = ZoneInfo(timezone_name)
    start = starts_at.astimezone(tz)
    end = ends_at.astimezone(tz)
    text = f"{_HEADLINES[event_type]}: {equipment_name}, {start:%d %b %Y} {start:%H:%M}-{end:%H:%M}."
    if reason:
        text += f" Reason: {reason}"
    return text


def create_notification(conn, user_id, event_type: str, message: str, reservation_id=None):
    """Insert a notification for ``user_id`` using the caller's connection and transaction.

    Do not commit here. Returns the new notification id.
    """
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown notification event type: {event_type}")
    row = conn.execute(
        """
        INSERT INTO notifications (user_id, reservation_id, event_type, message)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (user_id, reservation_id, event_type, message),
    ).fetchone()
    return row["id"]


def list_notifications(conn, user_id, page: int = 1, page_size: int = 20) -> dict:
    """The current user's own notifications, newest first. Never returns other users' rows."""
    rows = conn.execute(
        """
        SELECT id, reservation_id, event_type, message, created_at, read_at
        FROM notifications
        WHERE user_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT %s OFFSET %s
        """,
        (user_id, page_size + 1, (page - 1) * page_size),
    ).fetchall()
    return {
        "items": rows[:page_size],
        "page": page,
        "page_size": page_size,
        "has_more": len(rows) > page_size,
    }
