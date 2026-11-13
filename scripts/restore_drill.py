"""Backup and restore drill (STP TC-NF-005, requirement LAB-NF-005).

Restores the newest scheduled backup into a clean, isolated database and checks it
the way the test case asks:

  * recovery point: the backup is no more than 24 hours older than the simulated failure
  * recovery time:  restore initiation to application validation takes no more than 60 minutes
  * the restored counts, relationships and sampled booking records match the backup snapshot

"Application validation" here means the application itself runs against the restored
database: ``/healthz`` answers, and the real utilization report service reads a lab through
the application's own connection helper.

    python scripts/restore_drill.py --source-url postgresql://lab:lab@localhost:5432/lab \\
        --backup-dir backups --log docs/test-execution/drill-logs/tc-nf-005-<date>.md

The source database is only read (and, with --simulate-writes, given a few audit rows) and is
never restored over. The restored copy is a new database that is dropped afterwards unless
--keep-restored is given. See docs/operations/backup-and-restore.md.
"""

from __future__ import annotations

import argparse
import json
import platform
import shlex
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
for path in (str(ROOT), str(SCRIPTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

import backup_db  # noqa: E402
from backup_db import BackupError  # noqa: E402


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class DrillResult:
    manifest: dict
    backup_age: timedelta
    failure_at: datetime
    failure_clock: str
    restore_started_at: datetime
    restore_finished_at: datetime
    restore_seconds: float
    restored_db: str
    max_age_hours: float
    rto_minutes: float
    checks: list[Check] = field(default_factory=list)
    source_counts: dict[str, int] | None = None
    source_latest_change: datetime | None = None
    restored_counts: dict[str, int] = field(default_factory=dict)
    environment: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


# --- steps ----------------------------------------------------------------------------------------


def _write_after_backup(source_url: str, count: int) -> None:
    """Add audit rows after the backup so the live data moves past the recovery point."""
    with psycopg.connect(source_url, autocommit=True) as conn:
        for n in range(count):
            conn.execute(
                "INSERT INTO audit_events (action, target_type, outcome) VALUES (%s, 'drill', 'success')",
                (f"drill.post_backup_write.{n + 1}",),
            )


def _observe_source(source_url: str) -> tuple[datetime, str, dict | None, datetime | None]:
    """Failure time, taken from the source database clock if it is still reachable."""
    try:
        with psycopg.connect(source_url, connect_timeout=5) as conn:
            conn.execute("SET TIME ZONE 'UTC'")
            now = conn.execute("SELECT now()").fetchone()[0]
            return now, "source database clock", backup_db.table_counts(conn), backup_db.latest_activity(conn)
    except psycopg.Error:
        return datetime.now(timezone.utc), "local clock (source database unreachable)", None, None


def _orphan_rows(conn, keys: list[dict]) -> list[tuple[str, int]]:
    """Child rows whose foreign key points at a parent that does not exist."""
    problems = []
    for key in keys:
        on = sql.SQL(" AND ").join(
            sql.SQL("p.{} = c.{}").format(sql.Identifier(parent), sql.Identifier(child))
            for parent, child in zip(key["parent_columns"], key["child_columns"], strict=True)
        )
        present = sql.SQL(" AND ").join(
            sql.SQL("c.{} IS NOT NULL").format(sql.Identifier(col)) for col in key["child_columns"]
        )
        query = sql.SQL(
            "SELECT count(*) FROM {child} c WHERE {present} "
            "AND NOT EXISTS (SELECT 1 FROM {parent} p WHERE {on})"
        ).format(
            child=sql.Identifier(key["child"]), parent=sql.Identifier(key["parent"]), present=present, on=on
        )
        missing = conn.execute(query).fetchone()[0]
        if missing:
            problems.append((key["name"], missing))
    return problems


def _compare_counts(expected: dict[str, int], actual: dict[str, int]) -> list[str]:
    diffs = []
    for table in sorted(set(expected) | set(actual)):
        if expected.get(table) != actual.get(table):
            diffs.append(
                f"{table}: backup {expected.get(table, 'absent')}, restored {actual.get(table, 'absent')}"
            )
    return diffs


def _application_validation(restored_dsn: str) -> Check:
    """Start the application against the restored database and read through its own code paths."""
    from app import create_app
    from app.db import connect
    from app.reporting.services import utilization_report

    try:
        app = create_app({"DATABASE_URL": restored_dsn, "TESTING": True, "SECRET_KEY": "drill-only"})
        health = app.test_client().get("/healthz")
        if health.status_code != 200:
            return Check("Application validation", False, f"/healthz returned {health.status_code}")
        with app.app_context(), connect() as conn:
            admin = conn.execute(
                "SELECT user_id, lab_id FROM lab_memberships WHERE role = 'Administrator' "
                "ORDER BY lab_id, user_id LIMIT 1"
            ).fetchone()
            if admin is None:
                return Check(
                    "Application validation",
                    False,
                    "No administrator in the restored data to run a report as.",
                )
            last_day = datetime.now(timezone.utc).date() - timedelta(days=1)
            first_day: date = last_day - timedelta(days=29)
            report = utilization_report(conn, admin["user_id"], admin["lab_id"], first_day, last_day)
            expected = conn.execute(
                "SELECT count(*) AS n FROM equipment WHERE lab_id = %s", (admin["lab_id"],)
            ).fetchone()["n"]
        if len(report["equipment"]) != expected:
            return Check(
                "Application validation",
                False,
                f"Report listed {len(report['equipment'])} items of equipment, database has {expected}.",
            )
        return Check(
            "Application validation",
            True,
            f"/healthz 200; utilization report for '{report['lab_name']}' "
            f"({first_day} to {last_day}) listed all {expected} items of equipment",
        )
    except Exception as exc:  # the drill must report any failure, not crash on it
        return Check("Application validation", False, f"{type(exc).__name__}: {exc}")


def run_drill(
    source_url: str,
    backup_dir: Path,
    *,
    admin_url: str | None = None,
    take_backup_first: bool = False,
    simulate_writes: int = 0,
    max_age_hours: float = 24,
    rto_minutes: float = 60,
    keep_restored: bool = False,
) -> DrillResult:
    notes: list[str] = []
    if take_backup_first:
        backup_db.take_backup(source_url, backup_dir)
    manifest_path = backup_db.latest_manifest(backup_dir)
    manifest = json.loads(manifest_path.read_text())
    dump = backup_dir / manifest["dump_file"]
    if simulate_writes:
        _write_after_backup(source_url, simulate_writes)
        notes.append(
            f"{simulate_writes} audit rows were written to the source after the backup (--simulate-writes)."
        )

    failure_at, failure_clock, source_counts, source_latest = _observe_source(source_url)
    backup_age = failure_at - datetime.fromisoformat(manifest["taken_at"])

    if backup_age < timedelta(hours=1):
        how = (
            "by this run (--take-backup)" if take_backup_first else f"{_human(backup_age)} before the failure"
        )
        notes.append(
            f"The backup was made {how}, so the recovery-point figure shows that the mechanism works; "
            "it does not show that the daily schedule has been running."
        )
    notes.append(
        f"The dataset holds {sum(manifest['table_counts'].values()):,} rows "
        f"({manifest['dump_bytes']:,} byte archive). Recovery time grows with data size, "
        "so a production-sized dataset needs its own run."
    )

    # Restore into the server named by --admin-url when given: if the source server is the thing
    # that failed, the restored copy has to go somewhere else.
    parts = backup_db.connection_parts(admin_url or source_url)
    parts.pop("options", None)
    admin_dsn = make_conninfo(
        "", **{**parts, "dbname": parts.get("dbname", "postgres") if admin_url else "postgres"}
    )
    restored_name = f"lab_restore_{datetime.now(timezone.utc):%Y%m%d%H%M%S}_{uuid4().hex[:6]}"
    restored_parts = {**parts, "dbname": restored_name}
    restored_dsn = make_conninfo("", **restored_parts)

    checks: list[Check] = []
    environment: dict[str, str] = {}
    restored_counts: dict[str, int] = {}

    # --- the clock starts at restore initiation -------------------------------------------------
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    created = False
    try:
        actual_sha = backup_db.sha256_of(dump)
        intact = actual_sha == manifest["dump_sha256"]
        checks.append(
            Check(
                "Backup file is intact",
                intact,
                f"sha256 {actual_sha[:16]}... {'matches' if intact else 'DOES NOT match'} the manifest",
            )
        )
        if not intact:
            raise BackupError("backup file does not match its manifest; not restoring a corrupted file")

        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restored_name)))
            created = True
        backup_db.run_pg(
            "pg_restore",
            restored_parts,
            "--exit-on-error",
            "--single-transaction",
            "--no-owner",
            "--no-privileges",
            f"--dbname={restored_name}",
            str(dump),
        )
        checks.append(
            Check(
                "Restore into a clean isolated database", True, f"database {restored_name}, pg_restore exit 0"
            )
        )

        with psycopg.connect(restored_dsn) as conn:
            conn.execute("SET TIME ZONE 'UTC'")
            environment["restored_server_version"] = conn.execute("SHOW server_version").fetchone()[0]
            restored_counts = backup_db.table_counts(conn)
            diffs = _compare_counts(manifest["table_counts"], restored_counts)
            checks.append(
                Check(
                    "Row counts match the backup snapshot",
                    not diffs,
                    "; ".join(diffs)
                    or f"{len(restored_counts)} tables, {sum(restored_counts.values())} rows, all equal",
                )
            )

            keys = backup_db.foreign_keys(conn)
            orphans = _orphan_rows(conn, keys)
            problems = []
            if len(keys) != manifest["foreign_key_count"]:
                problems.append(
                    f"{len(keys)} foreign keys restored, backup had {manifest['foreign_key_count']}"
                )
            problems += [f"{name}: {n} orphan rows" for name, n in orphans]
            checks.append(
                Check(
                    "Relationships intact",
                    not problems,
                    "; ".join(problems) or f"{len(keys)} foreign keys present, no orphan rows",
                )
            )

            expected = manifest["sample_reservation_digests"]
            actual = backup_db.sample_digests(conn, ids=list(expected))
            wrong = sorted(i for i in expected if actual.get(i) != expected[i])
            if not expected:
                checks.append(
                    Check(
                        "Sampled booking records match", False, "The backup holds no reservations to sample."
                    )
                )
            else:
                checks.append(
                    Check(
                        "Sampled booking records match",
                        not wrong,
                        f"{len(expected) - len(wrong)} of {len(expected)} sampled reservations "
                        "identical row for row"
                        + (f"; differing ids: {', '.join(wrong[:5])}" if wrong else ""),
                    )
                )
        checks.append(_application_validation(restored_dsn))
    except (BackupError, psycopg.Error) as exc:
        checks.append(Check("Restore and validation completed", False, f"{type(exc).__name__}: {exc}"))
    finished = time.perf_counter()
    finished_at = datetime.now(timezone.utc)
    # --- the clock stops at application validation ---------------------------------------------

    elapsed = finished - started
    checks.insert(
        0,
        Check(
            "Recovery point within limit",
            timedelta(0) <= backup_age <= timedelta(hours=max_age_hours),
            f"newest backup was {_human(backup_age)} old at the simulated failure; limit {max_age_hours:g} h",
        ),
    )
    checks.append(
        Check(
            "Recovery time within limit",
            elapsed <= rto_minutes * 60,
            f"{elapsed:.1f} s from restore initiation to application validation; limit {rto_minutes:g} min",
        )
    )

    if created and not keep_restored:
        try:
            with psycopg.connect(admin_dsn, autocommit=True) as admin:
                admin.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(restored_name))
                )
        except psycopg.Error as exc:
            notes.append(f"The restored database {restored_name} could not be dropped: {exc}")

    environment.update(
        python=platform.python_version(),
        platform=platform.platform(),
        pg_dump=backup_db.tool_version("pg_dump"),
        pg_restore=backup_db.tool_version("pg_restore"),
        source_server_version=manifest.get("server_version", "unknown"),
    )
    return DrillResult(
        manifest=manifest,
        backup_age=backup_age,
        failure_at=failure_at,
        failure_clock=failure_clock,
        restore_started_at=started_at,
        restore_finished_at=finished_at,
        restore_seconds=elapsed,
        restored_db=restored_name,
        max_age_hours=max_age_hours,
        rto_minutes=rto_minutes,
        checks=checks,
        source_counts=source_counts,
        source_latest_change=source_latest,
        restored_counts=restored_counts,
        environment=environment,
        notes=notes,
    )


# --- the log --------------------------------------------------------------------------------------


def _human(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return f"{-seconds} s in the future (clock problem?)"
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return " ".join(
        p for p in (f"{hours} h" if hours else "", f"{minutes} min" if minutes else "", f"{secs} s") if p
    )


def _parse(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _stamp(value: datetime | None) -> str:
    return "n/a" if value is None else value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def render_log(
    result: DrillResult, command: str, run_type: str = "Development drill", where: str = ""
) -> str:
    m = result.manifest
    verdict = "PASS" if result.passed else "FAIL"
    lines = [
        f"# TC-NF-005 Backup and restore drill: {verdict}",
        "",
        "Team 16, Remote Laboratory Equipment Reservation System. Generated by "
        "`scripts/restore_drill.py` from a real run; do not edit by hand.",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| Result | **{verdict}** |",
        f"| Run type | {run_type} |",
        f"| Backup restored | `{m['dump_file']}` ({m['dump_bytes']:,} bytes, "
        f"sha256 `{m['dump_sha256'][:16]}...`) |",
        f"| Backup snapshot taken | {m['taken_at'][:19].replace('T', ' ')} UTC |",
        f"| Newest change in the data at backup | {_stamp(_parse(m['latest_dataset_change_at']))} |",
        f"| Simulated failure at | {_stamp(result.failure_at)} ({result.failure_clock}) |",
        f"| Newest change in the live data at failure | {_stamp(result.source_latest_change)} |",
        f"| Recovery point (backup age at failure) | {_human(result.backup_age)} "
        f"(limit {result.max_age_hours:g} h) |",
        f"| Restore initiated | {_stamp(result.restore_started_at)} |",
        f"| Application validation finished | {_stamp(result.restore_finished_at)} |",
        f"| Recovery time | {result.restore_seconds:.1f} s (limit {result.rto_minutes:g} min) |",
        f"| Command | `{command}` |",
        "",
        "Recovery time runs from restore initiation (checksum verification, creating the clean database, "
        "`pg_restore`) to the end of application validation. Creating the backup and dropping the restored "
        "copy are outside the timed window.",
        "",
        "## Checks",
        "",
        "| # | Check | Result | Detail |",
        "|---|---|---|---|",
    ]
    for number, check in enumerate(result.checks, 1):
        lines.append(
            f"| {number} | {check.name} | {'Pass' if check.passed else '**Fail**'} | {check.detail} |"
        )

    lines += ["", "## Data", "", "| Table | In backup | Restored | Live at failure |", "|---|---|---|---|"]
    for table in sorted(set(m["table_counts"]) | set(result.restored_counts)):
        live = "n/a" if result.source_counts is None else result.source_counts.get(table, "absent")
        lines.append(
            f"| `{table}` | {m['table_counts'].get(table, 'absent')} "
            f"| {result.restored_counts.get(table, 'absent')} | {live} |"
        )
    lines += [
        "",
        f"Sampled reservations compared: {len(m['sample_reservation_digests'])} (the reservations with the "
        "smallest md5 of their id, compared as whole rows).",
        "",
        "## Environment",
        "",
        "| Item | Value |",
        "|---|---|",
    ]
    if where:
        lines.append(f"| where it ran | {where} |")
    for key, value in result.environment.items():
        lines.append(f"| {key.replace('_', ' ')} | {value} |")

    lines += ["", "## What this run does and does not show", ""]
    lines += [f"- {note}" for note in result.notes]
    lines += [
        "- The data is synthetic (`scripts/synthetic_data.py`); no real student records are involved.",
        "- The recovery point is the age of the newest backup at the simulated failure. It evidences the "
        "24 hour limit only when that backup came from the scheduled daily job.",
        "- Application validation covers `/healthz` and the utilization report. Modules that are still stubs "
        "(authentication, equipment, reservations, approvals) are not exercised.",
        "- The case is complete only when it is run on the isolated test deployment with the scheduled "
        "backup job, and the register row is updated with a link to that log.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Restore the newest backup into a clean database and verify it (TC-NF-005)."
    )
    parser.add_argument(
        "--source-url", required=True, help="The live (or scratch) database that was backed up."
    )
    parser.add_argument("--backup-dir", default="backups", type=Path)
    parser.add_argument(
        "--admin-url",
        help="Connection that may CREATE DATABASE (default: the source server, database 'postgres').",
    )
    parser.add_argument(
        "--take-backup", action="store_true", help="Take a backup first (development drills only)."
    )
    parser.add_argument(
        "--simulate-writes",
        type=int,
        default=0,
        help="Write N audit rows to the source after the backup (scratch databases only).",
    )
    parser.add_argument("--max-age-hours", type=float, default=24)
    parser.add_argument("--rto-minutes", type=float, default=60)
    parser.add_argument("--keep-restored", action="store_true")
    parser.add_argument("--log", type=Path, help="Write the drill log (Markdown) here.")
    parser.add_argument(
        "--run-type", default="Development drill", help="Stated in the log, e.g. 'Formal execution'."
    )
    parser.add_argument(
        "--where", default="", help="Where the drill ran, stated in the log's environment table."
    )
    args = parser.parse_args(argv)

    try:
        result = run_drill(
            args.source_url,
            args.backup_dir,
            admin_url=args.admin_url,
            take_backup_first=args.take_backup,
            simulate_writes=args.simulate_writes,
            max_age_hours=args.max_age_hours,
            rto_minutes=args.rto_minutes,
            keep_restored=args.keep_restored,
        )
    except (BackupError, psycopg.Error) as exc:
        print(f"DRILL COULD NOT RUN: {exc}", file=sys.stderr)
        return 2

    for check in result.checks:
        print(f"[{'PASS' if check.passed else 'FAIL'}] {check.name}: {check.detail}")
    print(f"TC-NF-005 drill: {'PASS' if result.passed else 'FAIL'}")
    if args.log:
        given = list(argv if argv is not None else sys.argv[1:])
        shown = [
            "<url>" if i and given[i - 1] in ("--source-url", "--admin-url") else a
            for i, a in enumerate(given)
        ]
        args.log.parent.mkdir(parents=True, exist_ok=True)
        args.log.write_text(
            render_log(
                result, shlex.join(["python", "scripts/restore_drill.py", *shown]), args.run_type, args.where
            )
        )
        print(f"Log written to {args.log}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
