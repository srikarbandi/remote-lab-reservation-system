"""HTTP controllers for reservations (LAB-F-006 to LAB-F-009)."""

from flask import Blueprint, g, jsonify, request

from app.common.auth_context import current_user_id
from app.common.validation import (
    check_fields,
    clean_text,
    json_body,
    parse_datetime,
    parse_int,
    parse_page,
    parse_uuid,
)
from app.db import connect, translate_db_errors
from app.reservations import services

bp = Blueprint("reservations", __name__, url_prefix="/api/reservations")


def _reservation_json(row):
    result = {}
    for key, value in row.items():
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
        elif value is not None and key in {"id", "student_id", "equipment_id", "decided_by"}:
            result[key] = str(value)
        else:
            result[key] = value
    return result


@bp.post("")
def create():
    actor_id = current_user_id()
    body = json_body()
    check_fields(body, {"equipment_id", "start", "end", "purpose"})
    equipment_id = parse_uuid(body["equipment_id"], "equipment_id")
    start = parse_datetime(body["start"], "start")
    end = parse_datetime(body["end"], "end")
    purpose = clean_text(body["purpose"], "purpose")
    key = request.headers.get("Idempotency-Key")
    with translate_db_errors(), connect() as conn:
        result = services.create_reservation(
            conn, actor_id, equipment_id, start, end, purpose, key, g.request_id
        )
    return jsonify(result), 201


@bp.get("")
def list_own_or_lab():
    actor_id = current_user_id()
    scope = request.args.get("scope", "mine")
    lab_value = request.args.get("lab_id")
    lab_id = parse_uuid(lab_value, "lab_id") if lab_value is not None else None
    status = request.args.get("status")
    page, page_size = parse_page(request.args)
    with translate_db_errors(), connect() as conn:
        result = services.list_reservations(
            conn, actor_id, scope, lab_id, status, page, page_size
        )
    return jsonify(
        items=[_reservation_json(row) for row in result["items"]],
        total=result["total"], page=result["page"], page_size=result["page_size"],
    )


@bp.post("/<uuid:reservation_id>/cancel")
def cancel(reservation_id):
    actor_id = current_user_id()
    body = json_body()
    check_fields(body, {"expected_version"})
    expected_version = parse_int(body["expected_version"], "expected_version", minimum=1)
    with translate_db_errors(), connect() as conn:
        result = services.cancel_reservation(
            conn, actor_id, reservation_id, expected_version, g.request_id
        )
    return jsonify({key: str(value) if key == "id" else value for key, value in result.items()})
