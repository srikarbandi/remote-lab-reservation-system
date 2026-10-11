"""HTTP controllers for the usage module.

Owner: Sreekar Bandi
Requirements: LAB-F-016 (DS-Usage)
Design: docs/Team16_Remote_Laboratory_SAD.docx, section 4.3.4

POST /api/reservations/{id}/usage
    {"used_start", "used_end", "expected_version"}  or  {"no_show": true, "expected_version"}
    -> 200 {"id", "status": "Completed", "version", "used_minutes"}
"""

from flask import Blueprint, g, jsonify

from app.common.auth_context import current_user_id
from app.common.errors import ApiError
from app.common.validation import check_fields, json_body, parse_datetime, parse_int
from app.db import connect, translate_db_errors
from app.usage import services

bp = Blueprint("usage", __name__, url_prefix="/api/reservations")


@bp.post("/<uuid:reservation_id>/usage")
def record(reservation_id):
    actor_id = current_user_id()
    body = json_body()
    check_fields(body, {"expected_version"}, {"used_start", "used_end", "no_show"})
    expected_version = parse_int(body["expected_version"], "expected_version", minimum=1)
    no_show = body.get("no_show", False)
    if not isinstance(no_show, bool):
        raise ApiError(
            422,
            "INVALID_FIELDS",
            "Invalid value for 'no_show'.",
            fields={"no_show": "Must be true or false."},
        )
    used_start = parse_datetime(body["used_start"], "used_start") if "used_start" in body else None
    used_end = parse_datetime(body["used_end"], "used_end") if "used_end" in body else None
    with translate_db_errors(), connect() as conn:
        result = services.record_usage(
            conn, actor_id, reservation_id, expected_version, used_start, used_end, no_show, g.request_id
        )
    return jsonify(
        id=str(result["id"]),
        status=result["status"],
        version=result["version"],
        used_minutes=result["used_minutes"],
    )
