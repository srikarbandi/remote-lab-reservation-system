"""Who is making this request.

Integration contract with the auth module (DS-Authentication): once a session
cookie has been validated (active account, not revoked, not expired), the auth
layer sets ``g.user_id`` to the user's UUID. Every protected controller calls
``current_user_id()``. Roles are never read from the request; services load
them from the database (see ``app.common.permissions``).
"""

from uuid import UUID

from flask import g

from app.common.errors import ApiError


def current_user_id() -> UUID:
    user_id = g.get("user_id")
    if user_id is None:
        raise ApiError(401, "UNAUTHENTICATED", "Authentication is required.")
    return user_id
