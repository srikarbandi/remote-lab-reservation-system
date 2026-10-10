"""Shared error contract (SAD 4.3.5).

Body shape:
    {"error": {"code": "SLOT_CONFLICT", "message": "...", "request_id": "<UUID>"}}
A "fields" object may be added for field validation errors.
"""

from flask import g, jsonify


class ApiError(Exception):
    """Raise from services or controllers to return a contract-shaped error.

    Status meanings: 400 malformed request, 401 no/expired session, 403 role,
    lab, owner or CSRF failure, 404 resource missing, 409 conflict/stale
    version/invalid state, 422 invalid fields, 503 database unavailable or
    lock timeout.
    """

    def __init__(self, status: int, code: str, message: str, fields: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.fields = fields


def error_response(status: int, code: str, message: str, fields: dict | None = None):
    body = {"error": {"code": code, "message": message, "request_id": g.get("request_id")}}
    if fields:
        body["error"]["fields"] = fields
    response = jsonify(body)
    response.status_code = status
    return response
