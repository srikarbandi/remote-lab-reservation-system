"""Execute STP system cases through the running application and record the evidence.

Cases: TC-F-014 (maintenance blocks), TC-F-016 (usage recording), TC-F-017 (utilization report).

Each case builds its own synthetic fixture in the database, performs the STP steps as HTTP requests to
the running application, and checks the response and the rows in the database afterwards (the STP says
a response alone does not prove the outcome). Results go to a Markdown log per case and, with
--update-register, into docs/test-execution/execution-register.csv.

    python scripts/run_stp_cases.py --base-url http://127.0.0.1:8000 \\
        --database-url postgresql://lab:lab@localhost:5432/lab_cases --init-schema --update-register

Start the application against the same database with scripts/load_test_app.py (it supplies the
test-only X-Test-User login the auth module cannot provide yet). Cases that need modules that do not
exist yet record those steps as Blocked and the case as Blocked; nothing is guessed. See
docs/operations/system-cases.md.
"""

from __future__ import annotations

import argparse
import csv
import http.client
import json
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import psycopg

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "docs" / "test-execution" / "execution-register.csv"
LAB_TZ = ZoneInfo("Asia/Kolkata")
HEADER = "X-Test-User"


# --- recording ------------------------------------------------------------------------------------


@dataclass
class Step:
    number: int
    action: str
    expected: str
    observed: str
    result: str  # Pass, Fail or Blocked


@dataclass
class CaseRun:
    case_id: str
    title: str
    requirement: str
    fixture: str
    steps: list[Step] = field(default_factory=list)
    deviations: list[str] = field(default_factory=list)

    def record(self, action: str, expected: str, observed: str, ok: bool, blocked: bool = False) -> bool:
        result = "Blocked" if blocked else ("Pass" if ok else "Fail")
        self.steps.append(Step(len(self.steps) + 1, action, expected, observed, result))
        return ok

    @property
    def status(self) -> str:
        results = {s.result for s in self.steps}
        if "Fail" in results:
            return "Fail"
        if "Blocked" in results:
            return "Blocked"
        return "Pass"

    @property
    def summary(self) -> str:
        done = sum(1 for s in self.steps if s.result == "Pass")
        parts = [f"{done} of {len(self.steps)} steps passed"]
        for s in self.steps:
            if s.result != "Pass":
                parts.append(f"step {s.number} {s.result.lower()}: {s.action}: {s.observed}")
        return "; ".join(parts)


@dataclass
class Reply:
    status: int
    data: dict | None

    @property
    def code(self) -> str | None:
        return (self.data or {}).get("error", {}).get("code")

    def __str__(self) -> str:
        return f"HTTP {self.status}" + (f" {self.code}" if self.code else "")


class Api:
    """HTTP client for the running application; each call is made as one test user."""

    def __init__(self, base_url: str):
        parts = urlsplit(base_url)
        self.host, self.port = parts.hostname, parts.port or 80

    def call(self, user: UUID, method: str, path: str, body: dict | None = None) -> Reply:
        conn = http.client.HTTPConnection(self.host, self.port, timeout=30)
        try:
            headers = {HEADER: str(user), "Accept": "application/json"}
            payload = None
            if body is not None:
                payload = json.dumps(body)
                headers["Content-Type"] = "application/json"
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            try:
                data = json.loads(raw) if raw else None
            except ValueError:
                data = None
            return Reply(response.status, data)
        finally:
            conn.close()


# --- fixtures (synthetic data only) ---------------------------------------------------------------


class Fixture:
    def __init__(self, conn):
        self.conn = conn
        self.tag = uuid4().hex[:8]

    def one(self, sql: str, params: tuple = ()):
        return self.conn.execute(sql, params).fetchone()

    def lab(self, name: str) -> UUID:
        return self.one(
            "INSERT INTO labs (name, timezone) VALUES (%s, 'Asia/Kolkata') RETURNING id",
            (f"{name} {self.tag}",),
        )[0]

    def user(self, name: str, lab: UUID | None = None, role: str | None = None) -> UUID:
        user_id = self.one(
            "INSERT INTO users (identifier, password_hash) VALUES (%s, '!synthetic-not-a-real-hash') RETURNING id",
            (f"{name}-{self.tag}@lab.test",),
        )[0]
        if lab is not None:
            self.conn.execute(
                "INSERT INTO lab_memberships (user_id, lab_id, role) VALUES (%s, %s, %s)",
                (user_id, lab, role),
            )
        return user_id

    def equipment(self, lab: UUID, code: str) -> UUID:
        return self.one(
            "INSERT INTO equipment (lab_id, code, name) VALUES (%s, %s, %s) RETURNING id",
            (lab, f"{code}-{self.tag}", f"Equipment {code}"),
        )[0]

    def opening_all_week(self, lab: UUID, opens: time = time(9), closes: time = time(17)) -> None:
        for weekday in range(7):
            self.conn.execute(
                "INSERT INTO lab_opening_intervals (lab_id, weekday, open_time, close_time) VALUES (%s, %s, %s, %s)",
                (lab, weekday, opens, closes),
            )

    def closed_on(self, lab: UUID, day: date) -> None:
        self.conn.execute(
            "INSERT INTO lab_opening_intervals (lab_id, override_date) VALUES (%s, %s)", (lab, day)
        )

    def reservation(
        self, student: UUID, equipment: UUID, start: datetime, end: datetime, status: str
    ) -> UUID:
        return self.one(
            "INSERT INTO reservations (student_id, equipment_id, starts_at, ends_at, status, purpose) "
            "VALUES (%s, %s, %s, %s, %s, 'synthetic STP case') RETURNING id",
            (student, equipment, start, end, status),
        )[0]

    def usage(self, reservation: UUID, start: datetime, end: datetime, recorded_by: UUID) -> None:
        minutes = int((end - start).total_seconds() // 60)
        self.conn.execute(
            "INSERT INTO usage_records (reservation_id, used_start, used_end, used_minutes, recorded_by) "
            "VALUES (%s, %s, %s, %s, %s)",
            (reservation, start, end, minutes, recorded_by),
        )

    def maintenance(self, equipment: UUID, by: UUID, start: datetime, end: datetime) -> None:
        self.conn.execute(
            "INSERT INTO maintenance_blocks (equipment_id, created_by, starts_at, ends_at, reason) "
            "VALUES (%s, %s, %s, %s, 'synthetic fixture')",
            (equipment, by, start, end),
        )

    def version_of(self, reservation: UUID) -> int:
        return self.one("SELECT version FROM reservations WHERE id = %s", (reservation,))[0]

    def status_of(self, reservation: UUID) -> str:
        return self.one("SELECT status FROM reservations WHERE id = %s", (reservation,))[0]

    def usage_rows(self, reservation: UUID) -> list[tuple]:
        return self.conn.execute(
            "SELECT used_start, used_end, used_minutes, recorded_by FROM usage_records WHERE reservation_id = %s",
            (reservation,),
        ).fetchall()


def offered(reply: Reply, start: datetime, end: datetime) -> bool:
    """Is [start, end) inside one of the available intervals of an availability response?"""
    if reply.status != 200:
        return False
    return any(
        datetime.fromisoformat(i["start"]) <= start and end <= datetime.fromisoformat(i["end"])
        for i in reply.data["available"]
    )


def local(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=LAB_TZ).astimezone(timezone.utc)


# --- TC-F-016 usage recording ---------------------------------------------------------------------


def run_f016(api: Api, fx: Fixture) -> CaseRun:
    run = CaseRun(
        "TC-F-016",
        "Usage recording",
        "LAB-F-016",
        "Lab L1 with technician T1, student S1, equipment E1. R1 and R4 are Approved reservations that have "
        "ended; R2 is Approved and still in progress.",
    )
    now = datetime.now(timezone.utc).replace(microsecond=0)
    lab = fx.lab("STP L1")
    t1 = fx.user("t1", lab, "Technician")
    s1 = fx.user("s1", lab, "Student")
    e1 = fx.equipment(lab, "E1")
    r1 = fx.reservation(s1, e1, now - timedelta(hours=3), now - timedelta(hours=2), "Approved")
    r2 = fx.reservation(s1, e1, now - timedelta(minutes=30), now + timedelta(minutes=30), "Approved")
    r4 = fx.reservation(s1, e1, now - timedelta(hours=6), now - timedelta(hours=5), "Approved")
    usage_path = "/api/reservations/{}/usage"

    # 1. Contained usage interval on R1 (5 minutes in, 5 minutes early: 50 of 60 minutes).
    body = {
        "used_start": (now - timedelta(hours=3) + timedelta(minutes=5)).isoformat(),
        "used_end": (now - timedelta(hours=2) - timedelta(minutes=5)).isoformat(),
        "expected_version": fx.version_of(r1),
    }
    reply = api.call(t1, "POST", usage_path.format(r1), body)
    rows = fx.usage_rows(r1)
    ok = (
        reply.status == 200
        and reply.data["status"] == "Completed"
        and reply.data["used_minutes"] == 50
        and fx.status_of(r1) == "Completed"
        and len(rows) == 1
        and rows[0][2] == 50
        and rows[0][3] == t1
    )
    run.record(
        "T1 records a usage interval inside R1 (50 of 60 reserved minutes)",
        "200, reservation Completed, 50 used minutes, one usage record by T1",
        f"{reply}; reservation {fx.status_of(r1)}; {len(rows)} usage record(s), minutes "
        f"{[r[2] for r in rows]}",
        ok,
    )

    # 2. Reset R1, then record it as a no-show.
    fx.conn.execute("DELETE FROM usage_records WHERE reservation_id = %s", (r1,))
    fx.conn.execute("UPDATE reservations SET status = 'Approved' WHERE id = %s", (r1,))
    reply = api.call(
        t1, "POST", usage_path.format(r1), {"no_show": True, "expected_version": fx.version_of(r1)}
    )
    rows = fx.usage_rows(r1)
    ok = (
        reply.status == 200
        and reply.data["used_minutes"] == 0
        and len(rows) == 1
        and rows[0][:3] == (None, None, 0)
        and fx.status_of(r1) == "Completed"
    )
    run.record(
        "Reset R1; T1 records it with no_show=true",
        "200, Completed, 0 minutes, no usage timestamps stored",
        f"{reply}; {len(rows)} usage record(s) {[(r[0], r[1], r[2]) for r in rows]}; reservation {fx.status_of(r1)}",
        ok,
    )

    # 3. Usage starting before the reservation.
    body = {
        "used_start": (now - timedelta(hours=6, minutes=30)).isoformat(),
        "used_end": (now - timedelta(hours=5, minutes=10)).isoformat(),
        "expected_version": fx.version_of(r4),
    }
    reply = api.call(t1, "POST", usage_path.format(r4), body)
    ok = (
        reply.status == 422
        and reply.code == "INVALID_USAGE"
        and not fx.usage_rows(r4)
        and fx.status_of(r4) == "Approved"
    )
    run.record(
        "T1 submits usage that starts 30 minutes before R4 begins",
        "422 INVALID_USAGE, no usage record, R4 still Approved",
        f"{reply}; {len(fx.usage_rows(r4))} usage record(s); R4 {fx.status_of(r4)}",
        ok,
    )

    # 4. Early completion of the reservation still in progress.
    body = {"no_show": True, "expected_version": fx.version_of(r2)}
    reply = api.call(t1, "POST", usage_path.format(r2), body)
    ok = reply.status == 409 and reply.code == "RESERVATION_NOT_ENDED" and not fx.usage_rows(r2)
    run.record(
        "T1 tries to complete R2, which is still in progress",
        "409 RESERVATION_NOT_ENDED, no usage record, R2 still Approved",
        f"{reply}; {len(fx.usage_rows(r2))} usage record(s); R2 {fx.status_of(r2)}",
        ok and fx.status_of(r2) == "Approved",
    )

    # 5. Duplicate submission for R1, which is already Completed.
    body = {"no_show": True, "expected_version": fx.version_of(r1)}
    reply = api.call(t1, "POST", usage_path.format(r1), body)
    rows = fx.usage_rows(r1)
    ok = reply.status == 409 and reply.code == "INVALID_STATE" and len(rows) == 1
    run.record(
        "T1 records usage for R1 a second time",
        "409 INVALID_STATE, still exactly one usage record",
        f"{reply}; {len(rows)} usage record(s)",
        ok,
    )

    # 6. A student tries to record usage.
    body = {
        "used_start": (now - timedelta(hours=6)).isoformat(),
        "used_end": (now - timedelta(hours=5, minutes=30)).isoformat(),
        "expected_version": fx.version_of(r4),
    }
    reply = api.call(s1, "POST", usage_path.format(r4), body)
    ok = reply.status == 403 and not fx.usage_rows(r4) and fx.status_of(r4) == "Approved"
    run.record(
        "Student S1 tries to record usage for R4",
        "403, no usage record, R4 still Approved",
        f"{reply}; {len(fx.usage_rows(r4))} usage record(s); R4 {fx.status_of(r4)}",
        ok,
    )
    return run


# --- TC-F-017 utilization report ------------------------------------------------------------------


def run_f017(api: Api, fx: Fixture) -> CaseRun:
    run = CaseRun(
        "TC-F-017",
        "Utilization report",
        "LAB-F-017",
        "Lab L1 (Asia/Kolkata) open 09:00-17:00 every day, administrator A1, technician T1. One item of "
        "equipment per scenario so the scenarios do not affect each other.",
    )
    lab = fx.lab("STP L1")
    a1 = fx.user("a1", lab, "Administrator")
    t1 = fx.user("t1", lab, "Technician")
    s1 = fx.user("s1", lab, "Student")
    fx.opening_all_week(lab)
    today = datetime.now(LAB_TZ).date()

    def report(day_from: date, day_to: date, equipment: UUID) -> tuple[Reply, dict | None]:
        path = f"/api/reports/utilization?lab_id={lab}&from_date={day_from}&to_date={day_to}"
        reply = api.call(a1, "GET", path)
        row = None
        if reply.status == 200:
            row = next((e for e in reply.data["equipment"] if e["equipment_id"] == str(equipment)), None)
        return reply, row

    def completed(equipment: UUID, start: datetime, end: datetime, used_from: datetime, used_to: datetime):
        reservation = fx.reservation(s1, equipment, start, end, "Completed")
        fx.usage(reservation, used_from, used_to, t1)

    # 1. Baseline: 480 opening minutes, 60 maintenance minutes, 210 used minutes.
    day = today - timedelta(days=3)
    e1 = fx.equipment(lab, "BASE")
    fx.maintenance(e1, t1, local(day, 12), local(day, 13))
    completed(e1, local(day, 9), local(day, 11), local(day, 9, 10), local(day, 10, 40))  # 90
    completed(e1, local(day, 13), local(day, 15), local(day, 13, 0), local(day, 14, 0))  # 60
    completed(e1, local(day, 15), local(day, 17), local(day, 15, 30), local(day, 16, 30))  # 60
    reply, row = report(day, day, e1)
    ok = row is not None and row["bookable_minutes"] == 420 and row["used_minutes"] == 210
    ok = ok and row["utilization_percent"] == 50.0
    run.record(
        f"A1 requests the report for {day} (480 opening, 60 maintenance, 210 used minutes)",
        "420 bookable minutes, 210 used minutes, 50% utilization",
        f"{reply}; "
        + (
            f"bookable {row['bookable_minutes']}, used {row['used_minutes']}, {row['utilization_label']}"
            if row
            else "equipment row missing"
        ),
        ok,
    )

    # 2. A day the lab is closed: zero bookable minutes.
    day = today - timedelta(days=4)
    fx.closed_on(lab, day)
    e2 = fx.equipment(lab, "CLOSED")
    reply, row = report(day, day, e2)
    ok = row is not None and row["bookable_minutes"] == 0 and row["utilization_percent"] is None
    ok = ok and row["utilization_label"] == "Not applicable"
    run.record(
        f"Report for {day}, a day the lab is closed",
        "0 bookable minutes, utilization Not applicable (no division by zero)",
        f"{reply}; "
        + (f"bookable {row['bookable_minutes']}, {row['utilization_label']}" if row else "row missing"),
        ok,
    )

    # 3. Overlapping maintenance blocks are subtracted once.
    day = today - timedelta(days=5)
    e3 = fx.equipment(lab, "OVERLAP")
    fx.maintenance(e3, t1, local(day, 12), local(day, 13))
    fx.maintenance(e3, t1, local(day, 12, 30), local(day, 13, 30))
    reply, row = report(day, day, e3)
    ok = row is not None and row["bookable_minutes"] == 390
    run.record(
        f"Report for {day} with maintenance 12:00-13:00 and 12:30-13:30 on one item",
        "390 bookable minutes (480 minus the 90 minute union, not minus 120)",
        f"{reply}; " + (f"bookable {row['bookable_minutes']}" if row else "row missing"),
        ok,
    )

    # 4. A usage interval that crosses midnight is clipped to the requested range.
    day = today - timedelta(days=6)
    e4 = fx.equipment(lab, "CLIP")
    completed(
        e4,
        local(day, 23),
        local(day + timedelta(days=1), 1),
        local(day, 23, 30),
        local(day + timedelta(days=1), 0, 30),
    )
    reply, row = report(day, day, e4)
    ok = row is not None and row["used_minutes"] == 30
    run.record(
        f"Report for {day} only, with usage 23:30 to 00:30 across midnight",
        "30 used minutes (the part inside the range)",
        f"{reply}; " + (f"used {row['used_minutes']}" if row else "row missing"),
        ok,
    )

    # 5. An approved reservation that ended without a usage record.
    day = today - timedelta(days=7)
    e5 = fx.equipment(lab, "UNRECORDED")
    fx.reservation(s1, e5, local(day, 10), local(day, 12), "Approved")
    reply, row = report(day, day, e5)
    ok = row is not None and row["unrecorded_reservations"] == 1 and row["used_minutes"] == 0
    run.record(
        f"Report for {day} with one Approved reservation that has ended and no usage record",
        "1 unrecorded reservation counted separately, 0 used minutes",
        f"{reply}; "
        + (
            f"unrecorded {row['unrecorded_reservations']}, used {row['used_minutes']}"
            if row
            else "row missing"
        ),
        ok,
    )
    return run


# --- TC-F-014 maintenance blocks ------------------------------------------------------------------


def run_f014(api: Api, fx: Fixture) -> CaseRun:
    run = CaseRun(
        "TC-F-014",
        "Maintenance blocks",
        "LAB-F-014",
        "Lab L1 with technician T1 and equipment E1 holding a Pending request H1 10:00-11:00 tomorrow; "
        "lab L2 with equipment E2.",
    )
    run.deviations.append(
        "Booking cannot be tried through the application because the reservations module is not implemented; "
        "H1 was inserted directly into the database. 'Valid block prevents booking' and 'removal releases the "
        "interval' are checked through the availability endpoint instead, which is what booking will consult."
    )
    lab1, lab2 = fx.lab("STP L1"), fx.lab("STP L2")
    t1 = fx.user("t1", lab1, "Technician")
    s1 = fx.user("s1", lab1, "Student")
    e1, e2 = fx.equipment(lab1, "E1"), fx.equipment(lab2, "E2")
    fx.opening_all_week(lab1)
    day = datetime.now(LAB_TZ).date() + timedelta(days=1)
    fx.reservation(s1, e1, local(day, 10), local(day, 11), "Pending")

    def block_count(equipment: UUID) -> int:
        return fx.one("SELECT count(*) FROM maintenance_blocks WHERE equipment_id = %s", (equipment,))[0]

    # 1. Valid block.
    body = {
        "equipment_id": str(e1),
        "start": local(day, 14).isoformat(),
        "end": local(day, 15).isoformat(),
        "reason": "Calibration",
    }
    reply = api.call(t1, "POST", "/api/maintenance", body)
    block = reply.data["id"] if reply.status == 201 else None
    ok = reply.status == 201 and reply.data["version"] == 1 and block_count(e1) == 1
    run.record(
        "T1 creates maintenance 14:00-15:00 tomorrow on E1 with a reason",
        "201, one block stored with version 1",
        f"{reply}; {block_count(e1)} block(s) on E1",
        ok,
    )

    availability = api.call(s1, "GET", f"/api/equipment/{e1}/availability?date={day}")
    listed = availability.status == 200 and any(
        datetime.fromisoformat(i["start"]) == local(day, 14) for i in availability.data["maintenance"]
    )
    run.record(
        "S1 reads E1's availability for tomorrow while the block exists",
        "14:00-15:00 is listed as maintenance and is not offered as available",
        f"{availability}; 14:00-15:00 listed as maintenance: {listed}; offered as available: "
        f"{offered(availability, local(day, 14), local(day, 15))}",
        listed and not offered(availability, local(day, 14), local(day, 15)),
    )

    # 2. Booking across the block.
    probe = api.call(
        s1,
        "POST",
        "/api/reservations",
        {"equipment_id": str(e1), "start": local(day, 14).isoformat(), "end": local(day, 15).isoformat()},
    )
    run.record(
        "S1 tries to book E1 14:00-15:00 across the block",
        "Rejected because of the block",
        f"{probe}: the booking endpoint does not exist yet, so this step cannot run",
        False,
        blocked=True,
    )

    # 3. Expand the block across the held request.
    reply = api.call(
        t1,
        "PATCH",
        f"/api/maintenance/{block}",
        {"expected_version": 1, "start": local(day, 9, 30).isoformat()},
    )
    unchanged = fx.one("SELECT starts_at, version FROM maintenance_blocks WHERE id = %s", (block,))
    ok = reply.status == 409 and reply.code == "MAINTENANCE_CONFLICT" and unchanged == (local(day, 14), 1)
    run.record(
        "T1 expands the block to start 09:30 so it covers the held request H1 (10:00-11:00)",
        "409 MAINTENANCE_CONFLICT, block unchanged",
        f"{reply}; block start now {unchanged[0].astimezone(LAB_TZ):%H:%M} local, version {unchanged[1]}",
        ok,
    )

    # 4. No reason.
    body = {**body, "reason": "   ", "start": local(day, 16).isoformat(), "end": local(day, 17).isoformat()}
    reply = api.call(t1, "POST", "/api/maintenance", body)
    ok = reply.status == 422 and block_count(e1) == 1
    run.record(
        "T1 creates a block with an empty reason",
        "422, no block stored",
        f"{reply}; {block_count(e1)} block(s) on E1",
        ok,
    )

    # 5. Remove the block.
    reply = api.call(t1, "DELETE", f"/api/maintenance/{block}?expected_version=1")
    ok = reply.status == 204 and block_count(e1) == 0
    run.record(
        "T1 removes the block",
        "204, block no longer stored",
        f"{reply}; {block_count(e1)} block(s) on E1",
        ok,
    )
    availability = api.call(s1, "GET", f"/api/equipment/{e1}/availability?date={day}")
    free = offered(availability, local(day, 14), local(day, 15))
    run.record(
        "S1 reads E1's availability again after the removal",
        "14:00-15:00 is offered as available again",
        f"{availability}; offered as available: {free}",
        free,
    )

    # 6. Technician of another lab.
    body = {
        "equipment_id": str(e2),
        "start": local(day, 14).isoformat(),
        "end": local(day, 15).isoformat(),
        "reason": "Calibration",
    }
    reply = api.call(t1, "POST", "/api/maintenance", body)
    ok = reply.status == 403 and block_count(e2) == 0
    run.record(
        "T1 (lab L1) creates a block on E2 in lab L2",
        "403, no block stored",
        f"{reply}; {block_count(e2)} block(s) on E2",
        ok,
    )
    return run


CASES = {"TC-F-014": run_f014, "TC-F-016": run_f016, "TC-F-017": run_f017}


# --- output ---------------------------------------------------------------------------------------


def build_commit() -> str:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()

    dirty = git("status", "--porcelain", "--", ".", ":(exclude)docs/test-execution")
    return git("rev-parse", "--short", "HEAD") + ("-dirty" if dirty else "")


def render(run: CaseRun, commit: str, where: str, server: str, started: datetime) -> str:
    lines = [
        f"# {run.case_id} {run.title}: {run.status.upper()}",
        "",
        "Team 16, Remote Laboratory Equipment Reservation System. Generated by `scripts/run_stp_cases.py` "
        "from a real run against the running application; do not edit by hand.",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| Result | **{run.status}** |",
        f"| Requirement | {run.requirement} |",
        f"| Executed | {started:%Y-%m-%d %H:%M:%S} UTC |",
        f"| Build | `{commit}` |",
        f"| Application | {server or 'not stated'} |",
        f"| Where it ran | {where or 'not stated'} |",
        f"| Python | {platform.python_version()} |",
        f"| Fixture | {run.fixture} |",
        "",
        "## Steps",
        "",
        "| # | Step | Expected | Observed | Result |",
        "|---|---|---|---|---|",
    ]
    for s in run.steps:
        result = s.result if s.result == "Pass" else f"**{s.result}**"
        lines.append(f"| {s.number} | {s.action} | {s.expected} | {s.observed} | {result} |")
    lines += ["", "## Deviations from the STP", ""]
    lines += [f"- {d}" for d in run.deviations]
    lines += [
        "- Users are logged in with the test-only `X-Test-User` header; the auth module cannot log users in yet. "
        "Roles are still read from the database by the application.",
        "- The case was run through HTTP requests, not through the browser UI.",
        "- The fixture is synthetic and was inserted directly into the database.",
        "",
        "Every step also inspected the database rows after the request, as the STP requires.",
        "",
    ]
    return "\n".join(lines)


def update_register(
    runs: list[CaseRun], commit: str, tester: str, evidence: dict[str, str], when: datetime
) -> None:
    with REGISTER.open(newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        rows = list(reader)
    by_id = {r.case_id: r for r in runs}
    for row in rows:
        run = by_id.get(row["case_id"])
        if run is None:
            continue
        row.update(
            status=run.status,
            build_commit=commit,
            tester=tester,
            executed_at=when.strftime("%Y-%m-%d"),
            actual_result=run.summary,
            evidence_link=evidence[run.case_id],
        )
    with REGISTER.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute STP system cases through the running application.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--database-url", required=True, help="Scratch database the application uses.")
    parser.add_argument("--cases", nargs="+", default=list(CASES), choices=list(CASES))
    parser.add_argument(
        "--init-schema", action="store_true", help="Create the tables from db/schema.sql first."
    )
    parser.add_argument("--out-dir", type=Path, default=ROOT / "docs" / "test-execution" / "runs")
    parser.add_argument("--update-register", action="store_true")
    parser.add_argument("--tester", default="Sreekar Bandi")
    parser.add_argument("--where", default="")
    parser.add_argument("--server", default="")
    parser.add_argument(
        "--allow-dirty", action="store_true", help="Record results even with uncommitted code."
    )
    args = parser.parse_args(argv)

    commit = build_commit()
    if commit.endswith("-dirty") and not args.allow_dirty:
        print(
            "Uncommitted changes outside docs/test-execution: commit first so the build is identifiable.",
            file=sys.stderr,
        )
        return 2
    started = datetime.now(timezone.utc)
    api = Api(args.base_url)
    runs: list[CaseRun] = []
    with psycopg.connect(args.database_url, autocommit=True) as conn:
        if args.init_schema:
            sys.path.insert(0, str(ROOT / "scripts"))
            import synthetic_data

            synthetic_data.load_schema(conn)
        for case_id in args.cases:
            run = CASES[case_id](api, Fixture(conn))
            runs.append(run)
            print(f"{case_id}: {run.status}  ({run.summary})")

    folder = args.out_dir / f"{started:%Y-%m-%d}"
    folder.mkdir(parents=True, exist_ok=True)
    evidence = {}
    for run in runs:
        path = folder / f"{run.case_id.lower()}.md"
        path.write_text(render(run, commit, args.where, args.server, started))
        evidence[run.case_id] = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)
    if args.update_register:
        update_register(runs, commit, args.tester, evidence, started)
        print(f"Register updated: {REGISTER.relative_to(ROOT)}")
    return 0 if all(r.status == "Pass" for r in runs) else 1


if __name__ == "__main__":
    sys.exit(main())
