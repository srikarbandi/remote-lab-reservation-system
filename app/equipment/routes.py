
from flask import Blueprint, g, jsonify, request

from app.common.auth_context import current_user_id
from app.common.errors import ApiError
from app.common.validation import (
    check_fields,
    json_body,
    parse_date,
    parse_page,
    parse_uuid,
)
from app.db import connect, translate_db_errors
from app.equipment.services import (
    create_equipment,
    get_availability,
    list_equipment,
    update_equipment,
)

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


@bp.get("/<equipment_id>/availability")
def equipment_availability(equipment_id):
    user_id = current_user_id()

    equipment_uuid = parse_uuid(equipment_id, "equipment_id")
    selected_date = parse_date(request.args.get("date"), "date")

    with translate_db_errors():
        with connect() as conn:
            result = get_availability(
                conn, user_id, equipment_uuid, selected_date
            )

    return jsonify(result)


@bp.post("")
def add_equipment():
    actor_id = current_user_id()
    payload = json_body()

    check_fields(
        payload,
        {"lab_id", "code", "name"},
        {"description"}
    )

    lab_id = parse_uuid(payload["lab_id"], "lab_id")

    with translate_db_errors():
        with connect() as conn:
            result = create_equipment(
                conn,
                actor_id,
                lab_id,
                payload["code"],
                payload["name"],
                payload.get("description", ""),
                request_id=g.request_id
            )

    return jsonify(result), 201


@bp.patch("/<equipment_id>")
def edit_equipment(equipment_id):
    actor_id = current_user_id()
    equipment_uuid = parse_uuid(equipment_id, "equipment_id")
    payload = json_body()

    check_fields(
        payload,
        set(),
        {"code", "name", "description", "active"}
    )

    with translate_db_errors():
        with connect() as conn:
            result = update_equipment(
                conn,
                actor_id,
                equipment_uuid,
                payload,
                request_id=g.request_id
            )

    return jsonify(result)

