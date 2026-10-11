"""HTTP controllers for the notifications module.

Owner: Sreekar Bandi
Requirements: LAB-F-015 (DS-Notification)

GET /api/notifications?page=&page_size=   current user's notifications only
"""

from flask import Blueprint, jsonify, request

from app.common.auth_context import current_user_id
from app.common.validation import parse_page
from app.db import connect, translate_db_errors
from app.notifications import services

bp = Blueprint("notifications", __name__, url_prefix="/api/notifications")


def _iso(value):
    return value.isoformat() if value else None


@bp.get("")
def list_own():
    user_id = current_user_id()
    page, page_size = parse_page(request.args)
    with translate_db_errors(), connect() as conn:
        result = services.list_notifications(conn, user_id, page, page_size)
    items = [
        {
            "id": str(row["id"]),
            "reservation_id": str(row["reservation_id"]) if row["reservation_id"] else None,
            "event_type": row["event_type"],
            "message": row["message"],
            "created_at": _iso(row["created_at"]),
            "read_at": _iso(row["read_at"]),
        }
        for row in result["items"]
    ]
    return jsonify(
        items=items, page=result["page"], page_size=result["page_size"], has_more=result["has_more"]
    )
