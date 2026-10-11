"""Utilization report (LAB-F-017, DS-Reporting).

Owner: Sreekar Bandi.

Per-equipment actual utilization for a selected past date range (SRS 4.17, 6.1):
    bookable = opening minutes - union of maintenance minutes inside opening hours
    used     = recorded actual usage clipped to the range
    percent  = 100 x used / bookable, or "Not applicable" when bookable is zero

Approved reservations that have already ended but have no usage record are
counted separately as ``unrecorded_reservations``. They contribute zero used
minutes and are never inferred from approval. Booking occupancy is not shown
here, so it cannot be mistaken for actual utilization.
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.common.errors import ApiError
from app.common.permissions import ADMINISTRATOR, require_lab_role
from app.reporting import calculations as calc

MAX_RANGE_DAYS = 366


def _number(value: float):
    """Whole numbers as int, otherwise rounded to 2 decimals (keeps JSON tidy)."""
    rounded = round(value, 2)
    return int(rounded) if rounded == int(rounded) else rounded


def utilization_report(
    conn, actor_id, lab_id, from_date: date, to_date: date, now: datetime | None = None
) -> dict:
    now = now or datetime.now(timezone.utc)
    with conn.transaction():
        lab = conn.execute("SELECT id, name, timezone FROM labs WHERE id = %s", (lab_id,)).fetchone()
        if lab is None:
            raise ApiError(404, "LAB_NOT_FOUND", "The lab does not exist.")
        require_lab_role(conn, actor_id, lab_id, {ADMINISTRATOR})

        tz = ZoneInfo(lab["timezone"])
        today = now.astimezone(tz).date()
        if from_date > to_date:
            raise ApiError(
                422,
                "INVALID_RANGE",
                "from_date must not be after to_date.",
                fields={"from_date": "Must be on or before to_date."},
            )
        if to_date > today:
            raise ApiError(
                422,
                "INVALID_RANGE",
                "The report covers past dates only.",
                fields={"to_date": "Must not be in the future."},
            )
        if (to_date - from_date) >= timedelta(days=MAX_RANGE_DAYS):
            raise ApiError(
                422,
                "INVALID_RANGE",
                f"The date range is limited to {MAX_RANGE_DAYS} days.",
                fields={"from_date": f"Range must be at most {MAX_RANGE_DAYS} days."},
            )

        range_start, range_end = calc.range_bounds(tz, from_date, to_date)

        weekly = [
            (r["weekday"], r["open_time"], r["close_time"])
            for r in conn.execute(
                "SELECT weekday, open_time, close_time FROM lab_opening_intervals "
                "WHERE lab_id = %s AND weekday IS NOT NULL",
                (lab_id,),
            ).fetchall()
        ]
        overrides = [
            (r["override_date"], r["open_time"], r["close_time"])
            for r in conn.execute(
                "SELECT override_date, open_time, close_time FROM lab_opening_intervals "
                "WHERE lab_id = %s AND override_date BETWEEN %s AND %s",
                (lab_id, from_date, to_date),
            ).fetchall()
        ]
        windows = calc.opening_windows(tz, from_date, to_date, weekly, overrides)

        equipment = conn.execute(
            "SELECT id, code, name, active FROM equipment WHERE lab_id = %s ORDER BY code", (lab_id,)
        ).fetchall()
        ids = [row["id"] for row in equipment]

        maintenance: dict = {}
        usage: dict = {}
        unrecorded: dict = {}
        if ids:
            for r in conn.execute(
                "SELECT equipment_id, starts_at, ends_at FROM maintenance_blocks "
                "WHERE equipment_id = ANY(%s) AND starts_at < %s AND ends_at > %s",
                (ids, range_end, range_start),
            ).fetchall():
                maintenance.setdefault(r["equipment_id"], []).append((r["starts_at"], r["ends_at"]))
            for r in conn.execute(
                """
                SELECT r.equipment_id, u.used_start, u.used_end
                FROM usage_records u JOIN reservations r ON r.id = u.reservation_id
                WHERE r.equipment_id = ANY(%s) AND u.used_start IS NOT NULL
                  AND u.used_start < %s AND u.used_end > %s
                """,
                (ids, range_end, range_start),
            ).fetchall():
                usage.setdefault(r["equipment_id"], []).append((r["used_start"], r["used_end"]))
            for r in conn.execute(
                """
                SELECT r.equipment_id, count(*) AS n
                FROM reservations r
                LEFT JOIN usage_records u ON u.reservation_id = r.id
                WHERE r.equipment_id = ANY(%s) AND r.status = 'Approved' AND u.reservation_id IS NULL
                  AND r.starts_at < %s AND r.ends_at > %s AND r.ends_at <= %s
                GROUP BY r.equipment_id
                """,
                (ids, range_end, range_start, now),
            ).fetchall():
                unrecorded[r["equipment_id"]] = r["n"]

        items = []
        for row in equipment:
            bookable = calc.bookable_minutes(windows, maintenance.get(row["id"], []))
            used = calc.used_minutes(usage.get(row["id"], []), range_start, range_end)
            percent = calc.utilization_percent(used, bookable)
            items.append(
                {
                    "equipment_id": str(row["id"]),
                    "code": row["code"],
                    "name": row["name"],
                    "active": row["active"],
                    "used_minutes": _number(used),
                    "bookable_minutes": _number(bookable),
                    "utilization_percent": None if percent is None else round(percent, 2),
                    "utilization_label": "Not applicable" if percent is None else f"{round(percent, 1)}%",
                    "unrecorded_reservations": unrecorded.get(row["id"], 0),
                }
            )
        return {
            "lab_id": str(lab["id"]),
            "lab_name": lab["name"],
            "timezone": lab["timezone"],
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "equipment": items,
        }
