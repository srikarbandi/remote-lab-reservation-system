"""HTTP controllers for the maintenance module.

Owner: Sreekar Bandi
Requirements: LAB-F-014 (DS-Maintenance)
Design: docs/Team16_Remote_Laboratory_SAD.docx, sections 3.4 and 4.3.4

POST   /api/maintenance        equipment_id, start, end, reason          -> 201 block
PATCH  /api/maintenance/{id}   expected_version + any of start/end/reason -> 200 block
DELETE /api/maintenance/{id}   expected_version (query string or body)    -> 204

Controllers only parse input and call the service layer.
"""

from flask import Blueprint, g, jsonify, request

from app.common.auth_context import current_user_id
from app.common.errors import ApiError
from app.common.validation import check_fields, clean_text, json_body, parse_datetime, parse_int, parse_uuid
from app.db import connect, translate_db_errors
from app.maintenance import services

bp = Blueprint("maintenance", __name__, url_prefix="/api/maintenance")


def _block_json(block: dict) -> dict:
    return {
        "id": str(block["id"]),
        "equipment_id": str(block["equipment_id"]),
        "start": block["starts_at"].isoformat(),
        "end": block["ends_at"].isoformat(),
        "reason": block["reason"],
        "version": block["version"],
    }


@bp.post("")
def create():
    actor_id = current_user_id()
    body = json_body()
    check_fields(body, {"equipment_id", "start", "end", "reason"})
    equipment_id = parse_uuid(body["equipment_id"], "equipment_id")
    start = parse_datetime(body["start"], "start")
    end = parse_datetime(body["end"], "end")
    reason = clean_text(body["reason"], "reason")
    with translate_db_errors(), connect() as conn:
        block = services.create_block(conn, actor_id, equipment_id, start, end, reason, g.request_id)
    return jsonify(_block_json(block)), 201


@bp.patch("/<uuid:block_id>")
def update(block_id):
    actor_id = current_user_id()
    body = json_body()
    check_fields(body, {"expected_version"}, {"start", "end", "reason"})
    if not ({"start", "end", "reason"} & set(body)):
        raise ApiError(
            422,
            "INVALID_FIELDS",
            "Provide at least one of start, end or reason.",
            fields={"start": "Provide at least one field to change."},
        )
    expected_version = parse_int(body["expected_version"], "expected_version", minimum=1)
    start = parse_datetime(body["start"], "start") if "start" in body else None
    end = parse_datetime(body["end"], "end") if "end" in body else None
    reason = clean_text(body["reason"], "reason") if "reason" in body else None
    with translate_db_errors(), connect() as conn:
        block = services.update_block(
            conn, actor_id, block_id, expected_version, start, end, reason, g.request_id
        )
    return jsonify(_block_json(block))


@bp.delete("/<uuid:block_id>")
def remove(block_id):
    actor_id = current_user_id()
    raw = request.args.get("expected_version")
    if raw is None:
        body = json_body()
        check_fields(body, {"expected_version"})
        raw = body["expected_version"]
    expected_version = parse_int(raw, "expected_version", minimum=1)
    with translate_db_errors(), connect() as conn:
        services.delete_block(conn, actor_id, block_id, expected_version, g.request_id)
    return "", 204
