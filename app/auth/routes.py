import secrets

from flask import Blueprint, current_app, g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.auth.services import login, token_hash
from app.auth.sessions import authenticate, logout
from app.common.errors import ApiError
from app.db import connect, translate_db_errors

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

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

    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise ApiError(403, "CSRF_FAILED", "Refresh the page and try again.")

    try:
        payload = csrf_serializer().loads(cookie, max_age=3600)
    except (BadSignature, SignatureExpired):
        raise ApiError(403, "CSRF_FAILED", "Refresh the page and try again.") from None

    if not isinstance(payload, dict) or payload.get("binding") != csrf_binding():
        raise ApiError(403, "CSRF_FAILED", "Refresh the page and try again.")


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
        auth_endpoint = request.endpoint in {"auth.login_route", "auth.logout_route"}

        if token or auth_endpoint:
            require_csrf()


@bp.after_app_request
def prevent_auth_caching(response):
    if request.blueprint == "auth":
        response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/csrf")
def csrf_route():
    response = jsonify({})
    token = issue_csrf(response, csrf_binding())
    response.set_data(current_app.json.dumps({"csrf_token": token}))
    return response


@bp.post("/login")
def login_route():
    if not request.is_json:
        raise ApiError(400, "INVALID_JSON", "Send a JSON request body.")

    body = request.get_json(silent=True)

    if not isinstance(body, dict):
        raise ApiError(400, "INVALID_JSON", "Send a JSON object.")

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


@bp.get("/me")
def me_route():
    if g.get("user_id") is None:
        raise ApiError(401, "UNAUTHENTICATED", "Please log in.")

    return jsonify(user_id=str(g.user_id))


@bp.post("/logout")
def logout_route():
    if g.get("user_id") is None:
        raise ApiError(401, "UNAUTHENTICATED", "Please log in.")

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