from datetime import datetime, timedelta, timezone

from app.audit.services import record_event
from app.auth.services import token_hash


def authenticate(conn, token):
    if not isinstance(token, str) or not token or len(token) > 256:
        return None

    hashed = token_hash(token)

    with conn.transaction():
        candidate = conn.execute(
            "SELECT user_id FROM sessions WHERE token_hash = %s",
            (hashed,),
        ).fetchone()

        if candidate is None:
            return None

        user = conn.execute(
            """
            SELECT id, identifier, active
            FROM users
            WHERE id = %s
            FOR UPDATE
            """,
            (candidate["user_id"],),
        ).fetchone()

        session = conn.execute(
            """
            SELECT id, user_id, last_activity_at, revoked_at
            FROM sessions
            WHERE token_hash = %s
            FOR UPDATE
            """,
            (hashed,),
        ).fetchone()

        if session is None or session["revoked_at"] is not None:
            return None

        now = datetime.now(timezone.utc)
        expired = session["last_activity_at"] <= now - timedelta(minutes=30)

        if user is None or not user["active"] or expired:
            conn.execute(
                "UPDATE sessions SET revoked_at = %s WHERE id = %s",
                (now, session["id"]),
            )
            return None

        conn.execute(
            "UPDATE sessions SET last_activity_at = %s WHERE id = %s",
            (now, session["id"]),
        )

        return {
            "user_id": user["id"],
            "identifier": user["identifier"],
            "session_id": session["id"],
        }


def logout(conn, token, request_id=None):
    with conn.transaction():
        identity = authenticate(conn, token)

        if identity is None:
            return False

        conn.execute(
            "UPDATE sessions SET revoked_at = now() WHERE id = %s",
            (identity["session_id"],),
        )

        record_event(
            conn,
            identity["user_id"],
            "LOGOUT",
            "session",
            identity["session_id"],
            "SUCCESS",
            request_id,
        )

        return True