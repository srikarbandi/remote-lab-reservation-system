"""Server-side role and lab checks (LAB-SR-001).

Roles come from lab_memberships in the database, never from the browser. A
disabled account has no permissions.
"""

from app.common.errors import ApiError

STUDENT = "Student"
TECHNICIAN = "Technician"
ADMINISTRATOR = "Administrator"
STAFF_ROLES = frozenset({TECHNICIAN, ADMINISTRATOR})


def require_lab_role(conn, user_id, lab_id, allowed) -> str:
    """Return the user's role in the lab, or raise 403 if it is not in ``allowed``."""
    row = conn.execute(
        """
        SELECT m.role
        FROM users u
        JOIN lab_memberships m ON m.user_id = u.id
        WHERE u.id = %s AND u.active AND m.lab_id = %s
        """,
        (user_id, lab_id),
    ).fetchone()
    if row is None or row["role"] not in allowed:
        raise ApiError(403, "FORBIDDEN", "You do not have permission to perform this action for this lab.")
    return row["role"]
