import secrets

from flask import Blueprint, current_app, g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.auth.accounts import create_user, update_user
from app.auth.services import login, token_hash
from app.auth.sessions import authenticate, logout
from app.common.errors import ApiError
from app.db import connect, translate_db_errors

bp = Blueprint("auth", __name__, url_prefix="/api")

SESSION_COOKIE = "lab_session"
CSRF_COOKIE = "lab_csrf"


def csrf_serializer():
    return URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"],
        salt="lab-csrf",
    )


def csrf_binding():
    token = request.cookies.get(SESSION_COOKIE)
    return token_hash(token) if token else "anonymous"


def issue_csrf(response, binding):
    token = csrf_serializer().dumps(
        {"nonce": secrets.token_urlsafe(32), "binding": binding}
    )
    response.set_cookie(
        CSRF_COOKIE,
        token,
        secure=current_app.config.get("AUTH_COOKIE_SECURE", True),
        httponly=True,
        samesite="Lax",
        path="/",
    )
    return token


def require_csrf():
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get("X-CSRF-Token", "")

    matches = secrets.compare_digest(
        cookie.encode("utf-8"),
        header.encode("utf-8"),
    )

    if not cookie or not header or not matches:
        raise ApiError(403, "CSRF_FAILED", "Refresh the page and try again.")

    try:
        payload = csrf_serializer().loads(cookie, max_age=3600)
    except (BadSignature, SignatureExpired):
        raise ApiError(
            403,
            "CSRF_FAILED",
            "Refresh the page and try again.",
        ) from None

    if not isinstance(payload, dict) or payload.get("binding") != csrf_binding():
        raise ApiError(403, "CSRF_FAILED", "Refresh the page and try again.")


def json_object():
    if not request.is_json:
        raise ApiError(400, "INVALID_JSON", "Send a JSON request body.")

    body = request.get_json(silent=True)

    if not isinstance(body, dict):
        raise ApiError(400, "INVALID_JSON", "Send a JSON object.")

    return body


def require_session():
    if g.get("user_id") is None or g.get("auth_session_id") is None:
        raise ApiError(401, "UNAUTHENTICATED", "Please log in.")

    return g.user_id


@bp.before_app_request
def load_authentication():
    token = request.cookies.get(SESSION_COOKIE)

    if token:
        with translate_db_errors(), connect() as conn:
            identity = authenticate(conn, token)

        if identity:
            g.user_id = identity["user_id"]
            g.auth_session_id = identity["session_id"]

    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        auth_endpoint = request.endpoint in {
            "auth.login_route",
            "auth.logout_route",
        }

        if token or auth_endpoint:
            require_csrf()


@bp.after_app_request
def prevent_auth_caching(response):
    if request.blueprint == "auth":
        response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/auth/csrf")
def csrf_route():
    response = jsonify({})
    token = issue_csrf(response, csrf_binding())
    response.set_data(current_app.json.dumps({"csrf_token": token}))
    return response


@bp.post("/auth/login")
def login_route():
    body = json_object()

    if set(body) != {"identifier", "password"}:
        raise ApiError(
            422,
            "INVALID_FIELDS",
            "Provide only identifier and password.",
        )

    with translate_db_errors(), connect() as conn:
        result = login(
            conn,
            body["identifier"],
            body["password"],
            g.get("request_id"),
        )

        if result["ok"]:
            old_token = request.cookies.get(SESSION_COOKIE)
            if old_token:
                logout(conn, old_token, g.get("request_id"))

    if not result["ok"]:
        raise ApiError(result["status"], result["code"], result["message"])

    response = jsonify(user=result["user"])
    response.set_cookie(
        SESSION_COOKIE,
        result["token"],
        secure=current_app.config.get("AUTH_COOKIE_SECURE", True),
        httponly=True,
        samesite="Lax",
        path="/",
    )

    csrf_token = issue_csrf(response, token_hash(result["token"]))
    response.set_data(
        current_app.json.dumps(
            {"user": result["user"], "csrf_token": csrf_token}
        )
    )
    return response


@bp.get("/auth/me")
def me_route():
    user_id = require_session()
    return jsonify(user_id=str(user_id))


@bp.post("/auth/logout")
def logout_route():
    require_session()

    with translate_db_errors(), connect() as conn:
        logout(conn, request.cookies.get(SESSION_COOKIE), g.get("request_id"))

    response = current_app.response_class(status=204)

    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(
            name,
            path="/",
            secure=current_app.config.get("AUTH_COOKIE_SECURE", True),
            httponly=True,
            samesite="Lax",
        )

    return response


@bp.post("/users")
def create_user_route():
    actor_id = require_session()
    body = json_object()
    required = {"identifier", "password", "lab_id", "role"}

    if set(body) != required:
        raise ApiError(
            422,
            "INVALID_FIELDS",
            "Provide only identifier, password, lab_id and role.",
        )

    with translate_db_errors(), connect() as conn:
        user = create_user(
            conn,
            actor_id,
            body["identifier"],
            body["password"],
            body["lab_id"],
            body["role"],
            request_id=g.get("request_id"),
        )

    return jsonify(user=user), 201


@bp.patch("/users/<user_id>")
def update_user_route(user_id):
    actor_id = require_session()
    body = json_object()
    allowed = {"lab_id", "role", "active"}

    if (
        "lab_id" not in body
        or set(body) - allowed
        or not ({"role", "active"} & set(body))
    ):
        raise ApiError(
            422,
            "INVALID_FIELDS",
            "Provide lab_id and at least one of role or active.",
        )

    if "role" in body and body["role"] is None:
        raise ApiError(422, "INVALID_ROLE", "Choose a valid lab role.")

    if "active" in body and not isinstance(body["active"], bool):
        raise ApiError(422, "INVALID_ACTIVE", "Active must be true or false.")

    with translate_db_errors(), connect() as conn:
        user = update_user(
            conn,
            actor_id,
            user_id,
            body["lab_id"],
            role=body.get("role"),
            active=body.get("active"),
            request_id=g.get("request_id"),
        )

    return jsonify(user=user)