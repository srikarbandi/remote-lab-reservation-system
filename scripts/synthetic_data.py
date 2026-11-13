"""Synthetic data for recovery drills and load tests (STP 6.1). Never real data.

Builds a small, repeatable laboratory dataset directly in PostgreSQL so the
backup and restore drill (TC-NF-005) and the load test (TC-NF-001) have
something realistic to work on before every module exists. The same seed always
produces the same ids and rows.

    python scripts/synthetic_data.py --init-schema \
        --database-url postgresql://lab:lab@localhost:5432/lab_drill

Passwords are a fixed placeholder, not a hash of anything, so nobody can log in
with these users.
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from uuid import UUID

import psycopg

SCHEMA_SQL = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
PLACEHOLDER_HASH = "!synthetic-placeholder-not-a-real-hash"


@dataclass
class SeedSummary:
    labs: list[UUID] = field(default_factory=list)
    administrators: dict[UUID, UUID] = field(default_factory=dict)  # lab id -> administrator user id
    technicians: dict[UUID, UUID] = field(default_factory=dict)  # lab id -> technician user id
    students: list[UUID] = field(default_factory=list)
    equipment: list[UUID] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)


def load_schema(conn) -> None:
    conn.execute(SCHEMA_SQL.read_text())


def seed(
    conn,
    *,
    labs: int = 2,
    equipment_per_lab: int = 5,
    students: int = 40,
    reservations: int = 1000,
    seed_value: int = 16,
    now: datetime | None = None,
) -> SeedSummary:
    """Insert a synthetic dataset into an empty schema and return what was created.

    Reservations are hourly slots laid out back to back on each item of equipment,
    so no two overlap. Slots that ended before ``now`` are Completed with a usage
    record (some are no-shows); the rest are a mix of Pending, Approved, Rejected
    and Cancelled.
    """
    if conn.execute("SELECT count(*) FROM users").fetchone()[0]:
        raise RuntimeError("Refusing to seed: the users table is not empty. Use an empty database.")
    if labs < 1 or equipment_per_lab < 1 or students < labs or reservations < 0:
        raise ValueError("Need at least one lab, one item of equipment per lab and one student per lab.")

    rng = random.Random(seed_value)
    now = (now or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)
    out = SeedSummary()

    def new_id() -> UUID:
        return UUID(int=rng.getrandbits(128), version=4)

    users, lab_rows, members, intervals, equipment_rows = [], [], [], [], []
    for n in range(1, labs + 1):
        lab_id = new_id()
        out.labs.append(lab_id)
        lab_rows.append((lab_id, f"Synthetic Lab {n}", "Asia/Kolkata"))
        for weekday in range(5):
            intervals.append((new_id(), lab_id, weekday, time(9), time(17)))
        for role, bucket, label in (
            ("Administrator", out.administrators, "admin"),
            ("Technician", out.technicians, "tech"),
        ):
            user_id = new_id()
            bucket[lab_id] = user_id
            users.append((user_id, f"{label}{n:02d}@lab.test"))
            members.append((user_id, lab_id, role))
        for e in range(1, equipment_per_lab + 1):
            equipment_id = new_id()
            out.equipment.append(equipment_id)
            equipment_rows.append(
                (equipment_id, lab_id, f"SYN-L{n:02d}-E{e:02d}", f"Synthetic equipment {n}.{e}")
            )

    student_lab: dict[UUID, UUID] = {}
    for s in range(students):
        user_id = new_id()
        out.students.append(user_id)
        lab_id = out.labs[s % labs]
        student_lab[user_id] = lab_id
        users.append((user_id, f"student{s + 1:03d}@lab.test"))
        members.append((user_id, lab_id, "Student"))

    lab_of_equipment = {eq[0]: eq[1] for eq in equipment_rows}
    students_by_lab = {lab: [s for s, lab_id in student_lab.items() if lab_id == lab] for lab in out.labs}

    reservation_rows, usage_rows, notification_rows, audit_rows, maintenance_rows = [], [], [], [], []
    per_equipment, extra = divmod(reservations, len(out.equipment))
    # Slots are 3 hours apart on each item of equipment; the history starts far enough back that
    # about 70% of them are already over and the rest are still to come.
    history_start = now - timedelta(hours=3 * (per_equipment * 7 // 10))
    statuses_future = ["Pending", "Approved", "Approved", "Rejected", "Cancelled"]
    for index, equipment_id in enumerate(out.equipment):
        lab_id = lab_of_equipment[equipment_id]
        pool = students_by_lab[lab_id]
        technician = out.technicians[lab_id]
        slots = per_equipment + (1 if index < extra else 0)
        for slot in range(slots):
            starts = history_start + timedelta(hours=3 * slot)
            ends = starts + timedelta(hours=1)
            student = rng.choice(pool)
            # Requested 1-5 days ahead of the slot, but never in the future.
            created = min(starts - timedelta(days=rng.randint(1, 5)), now - timedelta(hours=1))
            if ends <= now:
                status = "Completed" if rng.random() < 0.9 else "Cancelled"
            else:
                status = rng.choice(statuses_future)
            reservation_id = new_id()
            reservation_rows.append(
                (
                    reservation_id,
                    student,
                    equipment_id,
                    starts,
                    ends,
                    status,
                    f"Synthetic experiment {len(reservation_rows) + 1}",
                    technician if status in ("Approved", "Rejected", "Completed") else None,
                    created,
                    min(ends, now) if status == "Completed" else created,
                )
            )
            if status == "Completed":
                if rng.random() < 0.1:  # no-show: both timestamps NULL, zero minutes
                    usage_rows.append((reservation_id, None, None, 0, technician, ends))
                else:
                    used_start = starts + timedelta(minutes=rng.randint(0, 10))
                    used_end = ends - timedelta(minutes=rng.randint(0, 10))
                    minutes = int((used_end - used_start).total_seconds() // 60)
                    usage_rows.append((reservation_id, used_start, used_end, minutes, technician, ends))
            notification_rows.append(
                (
                    new_id(),
                    student,
                    reservation_id,
                    f"RESERVATION_{status.upper()}",
                    f"Your reservation is {status}.",
                    created,
                )
            )
            audit_rows.append(
                (new_id(), student, "reservation.create", "reservation", reservation_id, "success", created)
            )
        for _ in range(3):  # a few maintenance blocks per item, in the next two weeks
            block_start = now + timedelta(days=rng.randint(1, 14), hours=rng.randint(0, 6))
            maintenance_rows.append(
                (
                    new_id(),
                    equipment_id,
                    technician,
                    block_start,
                    block_start + timedelta(hours=2),
                    "Synthetic calibration",
                )
            )

    with conn.transaction():
        cur = conn.cursor()
        cur.executemany(
            "INSERT INTO users (id, identifier, password_hash) VALUES (%s, %s, %s)",
            [(u[0], u[1], PLACEHOLDER_HASH) for u in users],
        )
        cur.executemany("INSERT INTO labs (id, name, timezone) VALUES (%s, %s, %s)", lab_rows)
        cur.executemany("INSERT INTO lab_memberships (user_id, lab_id, role) VALUES (%s, %s, %s)", members)
        cur.executemany(
            "INSERT INTO lab_opening_intervals (id, lab_id, weekday, open_time, close_time) "
            "VALUES (%s, %s, %s, %s, %s)",
            intervals,
        )
        cur.executemany(
            "INSERT INTO equipment (id, lab_id, code, name) VALUES (%s, %s, %s, %s)", equipment_rows
        )
        cur.executemany(
            "INSERT INTO reservations (id, student_id, equipment_id, starts_at, ends_at, status, purpose, "
            "decided_by, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            reservation_rows,
        )
        cur.executemany(
            "INSERT INTO usage_records "
            "(reservation_id, used_start, used_end, used_minutes, recorded_by, recorded_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            usage_rows,
        )
        cur.executemany(
            "INSERT INTO maintenance_blocks (id, equipment_id, created_by, starts_at, ends_at, reason) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            maintenance_rows,
        )
        cur.executemany(
            "INSERT INTO notifications (id, user_id, reservation_id, event_type, message, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            notification_rows,
        )
        cur.executemany(
            "INSERT INTO audit_events (id, actor_id, action, target_type, target_id, outcome, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            audit_rows,
        )

    out.counts = {
        "users": len(users),
        "labs": len(lab_rows),
        "equipment": len(equipment_rows),
        "reservations": len(reservation_rows),
        "usage_records": len(usage_rows),
        "maintenance_blocks": len(maintenance_rows),
        "notifications": len(notification_rows),
        "audit_events": len(audit_rows),
    }
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--database-url", required=True, help="An EMPTY scratch database.")
    parser.add_argument(
        "--init-schema", action="store_true", help="Create the tables from db/schema.sql first."
    )
    parser.add_argument("--labs", type=int, default=2)
    parser.add_argument("--equipment-per-lab", type=int, default=5)
    parser.add_argument("--students", type=int, default=40)
    parser.add_argument("--reservations", type=int, default=1000)
    args = parser.parse_args(argv)

    with psycopg.connect(args.database_url, autocommit=True) as conn:
        if args.init_schema:
            load_schema(conn)
        summary = seed(
            conn,
            labs=args.labs,
            equipment_per_lab=args.equipment_per_lab,
            students=args.students,
            reservations=args.reservations,
        )
    print("Seeded synthetic data:", ", ".join(f"{k}={v}" for k, v in summary.counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
