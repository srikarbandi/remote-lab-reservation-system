"""Synthetic fixtures for integration tests (STP 6.1). No real credentials or student data."""

from datetime import time
from types import SimpleNamespace


def _id(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()["id"]


def add_user(conn, identifier, active=True):
    return _id(
        conn,
        "INSERT INTO users (identifier, password_hash, active) VALUES (%s, 'not-a-real-hash', %s) RETURNING id",
        (identifier, active),
    )


def add_lab(conn, name, tz="Asia/Kolkata"):
    return _id(conn, "INSERT INTO labs (name, timezone) VALUES (%s, %s) RETURNING id", (name, tz))


def add_member(conn, user_id, lab_id, role):
    conn.execute(
        "INSERT INTO lab_memberships (user_id, lab_id, role) VALUES (%s, %s, %s)", (user_id, lab_id, role)
    )


def add_equipment(conn, lab_id, code, active=True):
    return _id(
        conn,
        "INSERT INTO equipment (lab_id, code, name, active) VALUES (%s, %s, %s, %s) RETURNING id",
        (lab_id, code, f"Equipment {code}", active),
    )


def add_reservation(conn, student_id, equipment_id, start, end, status="Pending", version=1):
    return _id(
        conn,
        """
        INSERT INTO reservations (student_id, equipment_id, starts_at, ends_at, status, version, purpose)
        VALUES (%s, %s, %s, %s, %s, %s, 'synthetic test purpose') RETURNING id
        """,
        (student_id, equipment_id, start, end, status, version),
    )


def add_weekly_opening(conn, lab_id, weekday, opens=time(9), closes=time(17)):
    conn.execute(
        "INSERT INTO lab_opening_intervals (lab_id, weekday, open_time, close_time) VALUES (%s, %s, %s, %s)",
        (lab_id, weekday, opens, closes),
    )


def add_usage(conn, reservation_id, used_start, used_end, minutes, recorded_by):
    conn.execute(
        "INSERT INTO usage_records (reservation_id, used_start, used_end, used_minutes, recorded_by) "
        "VALUES (%s, %s, %s, %s, %s)",
        (reservation_id, used_start, used_end, minutes, recorded_by),
    )


def count(conn, table, where="true", params=()):
    return conn.execute(f"SELECT count(*) AS n FROM {table} WHERE {where}", params).fetchone()["n"]  # noqa: S608


def seed_world(conn) -> SimpleNamespace:
    """Lab L1 (admin A1, technician T1, students S1/S2, equipment E1/E2) and lab L2 (admin A2, equipment E3)."""
    w = SimpleNamespace()
    w.l1 = add_lab(conn, "L1")
    w.l2 = add_lab(conn, "L2")
    w.admin1 = add_user(conn, "a1")
    w.tech1 = add_user(conn, "t1")
    w.student1 = add_user(conn, "s1")
    w.student2 = add_user(conn, "s2")
    w.admin2 = add_user(conn, "a2")
    w.disabled_admin = add_user(conn, "a1-disabled", active=False)
    add_member(conn, w.admin1, w.l1, "Administrator")
    add_member(conn, w.tech1, w.l1, "Technician")
    add_member(conn, w.student1, w.l1, "Student")
    add_member(conn, w.student2, w.l1, "Student")
    add_member(conn, w.disabled_admin, w.l1, "Administrator")
    add_member(conn, w.admin2, w.l2, "Administrator")
    w.e1 = add_equipment(conn, w.l1, "E1")
    w.e2 = add_equipment(conn, w.l1, "E2")
    w.e3 = add_equipment(conn, w.l2, "E3")
    return w
