"""HTTP controller for administrator approval and rejection (LAB-F-010 to LAB-F-012)."""

from flask import Blueprint, g, jsonify

from app.approvals import services
from app.common.auth_context import current_user_id
from app.common.validation import check_fields, clean_text, json_body, parse_int
from app.db import connect, translate_db_errors

bp = Blueprint("approvals", __name__, url_prefix="/api/reservations")


@bp.post("/<uuid:reservation_id>/decision")
def decide(reservation_id):
    actor_id = current_user_id()
    body = json_body()
    check_fields(body, {"decision", "expected_version"}, {"reason"})
    decision = body["decision"]
    reason = clean_text(body["reason"], "reason") if "reason" in body else None
    expected_version = parse_int(body["expected_version"], "expected_version", minimum=1)
    with translate_db_errors(), connect() as conn:
        result = services.decide_reservation(
            conn, actor_id, reservation_id, decision, expected_version, reason, g.request_id
        )
    return jsonify({key: str(value) if key == "id" else value for key, value in result.items()})
