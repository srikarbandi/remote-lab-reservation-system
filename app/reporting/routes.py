"""HTTP controllers for the reporting module.

Owner: Sreekar Bandi
Requirements: LAB-F-017 (DS-Reporting)
Design: docs/Team16_Remote_Laboratory_SAD.docx, section 4.3.4

GET /api/reports/utilization?lab_id=&from_date=YYYY-MM-DD&to_date=YYYY-MM-DD
    Administrator of the lab only. Past dates only; inclusive local dates; at most 366 days.
"""

from flask import Blueprint, jsonify, request

from app.common.auth_context import current_user_id
from app.common.errors import ApiError
from app.common.validation import parse_date, parse_uuid
from app.db import connect, translate_db_errors
from app.reporting import services

bp = Blueprint("reporting", __name__, url_prefix="/api/reports")


@bp.get("/utilization")
def utilization():
    actor_id = current_user_id()
    missing = {
        n: "This query parameter is required."
        for n in ("lab_id", "from_date", "to_date")
        if n not in request.args
    }
    if missing:
        raise ApiError(422, "INVALID_FIELDS", "Missing query parameters.", fields=missing)
    lab_id = parse_uuid(request.args["lab_id"], "lab_id")
    from_date = parse_date(request.args["from_date"], "from_date")
    to_date = parse_date(request.args["to_date"], "to_date")
    with translate_db_errors(), connect() as conn:
        report = services.utilization_report(conn, actor_id, lab_id, from_date, to_date)
    return jsonify(report)
