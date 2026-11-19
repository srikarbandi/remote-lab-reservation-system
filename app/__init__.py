import uuid
from importlib import import_module

from flask import Flask, g, jsonify, render_template, request

from app.common.errors import ApiError, error_response

MODULES = [
    "auth",
    "equipment",
    "reservations",
    "approvals",
    "maintenance",
    "notifications",
    "usage",
    "reporting",
]


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY="change-me-in-env",
        DATABASE_URL="postgresql://lab:lab@localhost:5432/lab",
        TIMEZONE="Asia/Kolkata",
    )
    app.config.from_prefixed_env()
    if test_config:
        app.config.update(test_config)

    @app.before_request
    def assign_request_id() -> None:
        g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

    @app.after_request
    def expose_request_id(response):
        response.headers["X-Request-ID"] = g.get("request_id", "")
        return response

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok")

    @app.get("/accounts")
    def accounts_page():
        response = app.make_response(render_template("accounts.html"))
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_response(
            exc.status, exc.code, exc.message, exc.fields, exc.details
        )

    @app.errorhandler(404)
    def handle_404(_exc):
        return error_response(
            404, "NOT_FOUND", "The requested resource does not exist."
        )

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response(
            405, "METHOD_NOT_ALLOWED", "Method not allowed for this endpoint."
        )

    @app.errorhandler(500)
    def handle_500(_exc):
        return error_response(
            500, "INTERNAL_ERROR", "An unexpected error occurred."
        )

    for name in MODULES:
        module = import_module(f"app.{name}.routes")
        app.register_blueprint(module.bp)

    return app