import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from app.audit.services import record_event
from app.auth.passwords import hash_password, verify_password
from app.common.errors import ApiError

DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def login(conn, identifier, password, request_id=None):
    if not isinstance(identifier, str) or not identifier.strip():
        raise ApiError(422, "INVALID_IDENTIFIER", "Enter your account identifier.")

    identifier = identifier.strip()

    if len(identifier) > 100:
        raise ApiError(422, "INVALID_IDENTIFIER", "Identifier is too long.")

    if not isinstance(password, str) or not password or len(password) > 1024:
        raise ApiError(422, "INVALID_PASSWORD", "Enter a valid password.")

    with conn.transaction():
        conn.execute(
            """
            INSERT INTO login_attempts (identifier)
            VALUES (%s)
            ON CONFLICT (identifier) DO NOTHING
            """,
            (identifier,),
        )

        attempt = conn.execute(
            """
            SELECT failure_count, window_started, locked_until
            FROM login_attempts
            WHERE identifier = %s
            FOR UPDATE
            """,
            (identifier,),
        ).fetchone()

        now = datetime.now(timezone.utc)

        if attempt["locked_until"] and attempt["locked_until"] > now:
            return {
                "ok": False,
                "status": 429,
                "code": "LOGIN_LOCKED",
                "message": "Too many failed attempts. Try again later.",
            }

        user = conn.execute(
            """
            SELECT id, identifier, password_hash, active
            FROM users
            WHERE identifier = %s
            FOR UPDATE
            """,
            (identifier,),
        ).fetchone()

        stored_hash = user["password_hash"] if user else DUMMY_HASH
        valid_password = verify_password(stored_hash, password)

        if not user or not user["active"] or not valid_password:
            reset_window = (
                attempt["window_started"] <= now - timedelta(minutes=15)
                or attempt["locked_until"] is not None
            )

            failures = 1 if reset_window else attempt["failure_count"] + 1
            window_started = now if reset_window else attempt["window_started"]
            locked_until = now + timedelta(minutes=15) if failures >= 5 else None

            conn.execute(
                """
                UPDATE login_attempts
                SET failure_count = %s,
                    window_started = %s,
                    locked_until = %s
                WHERE identifier = %s
                """,
                (failures, window_started, locked_until, identifier),
            )

            record_event(
                conn,
                user["id"] if user else None,
                "LOGIN",
                "user",
                user["id"] if user else None,
                "FAILURE",
                request_id,
            )

            return {
                "ok": False,
                "status": 401,
                "code": "INVALID_CREDENTIALS",
                "message": "Invalid identifier or password.",
            }

        conn.execute(
            "DELETE FROM login_attempts WHERE identifier = %s",
            (identifier,),
        )

        token = secrets.token_urlsafe(32)

        conn.execute(
            """
            INSERT INTO sessions (token_hash, user_id)
            VALUES (%s, %s)
            """,
            (token_hash(token), user["id"]),
        )

        memberships = conn.execute(
            """
            SELECT lab_id, role
            FROM lab_memberships
            WHERE user_id = %s
            ORDER BY lab_id
            """,
            (user["id"],),
        ).fetchall()

        record_event(
            conn,
            user["id"],
            "LOGIN",
            "user",
            user["id"],
            "SUCCESS",
            request_id,
        )

        return {
            "ok": True,
            "token": token,
            "user": {
                "id": str(user["id"]),
                "identifier": user["identifier"],
                "memberships": [
                    {"lab_id": str(row["lab_id"]), "role": row["role"]}
                    for row in memberships
                ],
            },
        }