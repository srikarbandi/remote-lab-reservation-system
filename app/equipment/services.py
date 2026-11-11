
from app.common.errors import ApiError


def list_equipment(conn, user_id, name="", lab_id=None, page=1, page_size=20):
    user = conn.execute(
        "SELECT active FROM users WHERE id = %s",
        (user_id,)
    ).fetchone()

    if user is None or not user["active"]:
        raise ApiError(403, "FORBIDDEN", "Active account required.")

    conditions = ["e.active = true"]
    params = []

    if name:
        escaped = name.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        conditions.append("e.name ILIKE %s ESCAPE '!'")
        params.append(f"%{escaped}%")

    if lab_id is not None:
        conditions.append("e.lab_id = %s")
        params.append(lab_id)

    where_clause = " AND ".join(conditions)

    total = conn.execute(
        f"""
        SELECT COUNT(*) AS total
        FROM equipment e
        WHERE {where_clause}
        """,
        params
    ).fetchone()["total"]

    offset = (page - 1) * page_size

    rows = conn.execute(
        f"""
        SELECT e.id, e.code, e.name, e.description,
               e.active, e.lab_id, l.name AS lab_name
        FROM equipment e
        JOIN labs l ON e.lab_id = l.id
        WHERE {where_clause}
        ORDER BY e.name, e.code
        LIMIT %s OFFSET %s
        """,
        params + [page_size, offset]
    ).fetchall()

    return rows, total
