
from flask import Blueprint, jsonify, request

from app.common.auth_context import current_user_id
from app.common.errors import ApiError
from app.common.validation import parse_page, parse_uuid
from app.db import connect, translate_db_errors
from app.equipment.services import list_equipment

bp = Blueprint("equipment", __name__, url_prefix="/api/equipment")


@bp.get("")
def equipment_catalogue():
    user_id = current_user_id()

    name = request.args.get("name", "").strip()

    if len(name) > 500:
        raise ApiError(422, "INVALID_FIELDS", "Search term is too long.")

    lab_value = request.args.get("lab_id")
    lab_id = parse_uuid(lab_value, "lab_id") if lab_value is not None else None

    page, page_size = parse_page(request.args)

    with translate_db_errors():
        with connect() as conn:
            items, total = list_equipment(
                conn, user_id, name, lab_id, page, page_size
            )

    return jsonify({
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size
    })
