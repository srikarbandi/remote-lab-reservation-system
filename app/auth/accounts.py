from uuid import UUID

from app.audit.services import record_event
from app.auth.passwords import hash_password
from app.common.errors import ApiError
from app.common.permissions import ADMINISTRATOR, require_lab_role

ROLES = {"Student", "Technician", "Administrator"}


def as_uuid(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ApiError(422, "INVALID_ID", "Provide a valid UUID.") from None


def validate_role(role):
    if not isinstance(role, str) or role not in ROLES:
        raise ApiError(422, "INVALID_ROLE", "Choose a valid lab role.")


def lock_users(conn, actor_id, target_id=None):
    ids = [actor_id]
    if target_id is not None:
        ids.append(target_id)

    return conn.execute(
        """
        SELECT id, identifier, active
        FROM users
        WHERE id = ANY(%s)
        ORDER BY id
        FOR UPDATE
        """,
        (ids,),
    ).fetchall()


def create_user(
    conn,
    actor_id,
    identifier,
    password,
    lab_id,
    role,
    request_id=None,
):
    actor_id = as_uuid(actor_id)
    lab_id = as_uuid(lab_id)
    validate_role(role)

    if not isinstance(identifier, str) or not identifier.strip():
        raise ApiError(422, "INVALID_IDENTIFIER", "Enter an account identifier.")

    identifier = identifier.strip()

    if len(identifier) > 100:
        raise ApiError(422, "INVALID_IDENTIFIER", "Identifier is too long.")

    if not isinstance(password, str) or not password or len(password) > 1024:
        raise ApiError(422, "INVALID_PASSWORD", "Provide a valid password.")

    with conn.transaction():
        lock_users(conn, actor_id)
        require_lab_role(conn, actor_id, lab_id, {ADMINISTRATOR})

        user = conn.execute(
            """
            INSERT INTO users (identifier, password_hash)
            VALUES (%s, %s)
            ON CONFLICT (identifier) DO NOTHING
            RETURNING id, identifier, active
            """,
            (identifier, hash_password(password)),
        ).fetchone()

        if user is None:
            raise ApiError(
                409,
                "IDENTIFIER_EXISTS",
                "That identifier already exists.",
            )

        conn.execute(
            """
            INSERT INTO lab_memberships (user_id, lab_id, role)
            VALUES (%s, %s, %s)
            """,
            (user["id"], lab_id, role),
        )

        record_event(
            conn,
            actor_id,
            "CREATE_USER",
            "user",
            user["id"],
            "SUCCESS",
            request_id,
        )

        return {
            "id": str(user["id"]),
            "identifier": user["identifier"],
            "active": user["active"],
            "lab_id": str(lab_id),
            "role": role,
        }


def update_user(
    conn,
    actor_id,
    user_id,
    lab_id,
    role=None,
    active=None,
    request_id=None,
):
    actor_id = as_uuid(actor_id)
    user_id = as_uuid(user_id)
    lab_id = as_uuid(lab_id)

    if role is not None:
        validate_role(role)

    if active is not None and not isinstance(active, bool):
        raise ApiError(422, "INVALID_ACTIVE", "Active must be true or false.")

    if role is None and active is None:
        raise ApiError(422, "INVALID_FIELDS", "Provide role or active.")

    with conn.transaction():
        users = lock_users(conn, actor_id, user_id)
        require_lab_role(conn, actor_id, lab_id, {ADMINISTRATOR})

        target = next(
            (user for user in users if user["id"] == user_id),
            None,
        )

        if target is None:
            raise ApiError(
                404,
                "USER_NOT_FOUND",
                "The account does not exist.",
            )

        memberships = conn.execute(
            """
            SELECT lab_id, role
            FROM lab_memberships
            WHERE user_id = %s
            """,
            (user_id,),
        ).fetchall()

        membership = next(
            (item for item in memberships if item["lab_id"] == lab_id),
            None,
        )

        if membership is None:
            raise ApiError(
                403,
                "FORBIDDEN",
                "The account is not in this lab.",
            )

        if active is not None:
            managed = conn.execute(
                """
                SELECT lab_id
                FROM lab_memberships
                WHERE user_id = %s AND role = %s
                """,
                (actor_id, ADMINISTRATOR),
            ).fetchall()

            managed_ids = {item["lab_id"] for item in managed}

            if any(
                item["lab_id"] not in managed_ids
                for item in memberships
            ):
                raise ApiError(
                    403,
                    "FORBIDDEN",
                    "You must administer every lab this account belongs to.",
                )

            conn.execute(
                "UPDATE users SET active = %s WHERE id = %s",
                (active, user_id),
            )

        if role is not None:
            conn.execute(
                """
                UPDATE lab_memberships
                SET role = %s
                WHERE user_id = %s AND lab_id = %s
                """,
                (role, user_id, lab_id),
            )

        role_changed = role is not None and role != membership["role"]

        if active is False or role_changed:
            conn.execute(
                """
                UPDATE sessions
                SET revoked_at = now()
                WHERE user_id = %s AND revoked_at IS NULL
                """,
                (user_id,),
            )

        record_event(
            conn,
            actor_id,
            "UPDATE_USER",
            "user",
            user_id,
            "SUCCESS",
            request_id,
        )

        return {
            "id": str(user_id),
            "identifier": target["identifier"],
            "active": target["active"] if active is None else active,
            "lab_id": str(lab_id),
            "role": membership["role"] if role is None else role,
        }