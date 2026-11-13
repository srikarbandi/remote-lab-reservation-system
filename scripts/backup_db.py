"""Daily database backup job (LAB-NF-005, SAD DS-Recovery).

Takes a consistent PostgreSQL backup and writes two files to the backup directory:

    lab-<UTC timestamp>.dump           pg_dump custom-format archive
    lab-<UTC timestamp>.manifest.json  what the database held at that moment

The manifest is what the restore drill (scripts/restore_drill.py, STP TC-NF-005)
compares a restored copy against: the time the snapshot was taken, row counts per
table, the number of foreign keys, and a digest of a fixed sample of reservations.
It holds counts and digests only, never row contents.

The dump and the manifest come from the same database snapshot
(``pg_export_snapshot``), so they agree even while the application is writing.
The manifest is written last, so a half-finished backup is never picked up as
"the latest".

Run it once a day from the scheduler of the host (see docs/operations/backup-and-restore.md):

    python scripts/backup_db.py --database-url "$BACKUP_DATABASE_URL" --backup-dir /srv/lab-backups

Keep the backup directory on storage separate from the live database. Backups
and manifests are git-ignored; never commit them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

SAMPLE_SIZE = 25
DEFAULT_KEEP = 14
MANIFEST_VERSION = 1

# Columns that move forward whenever the application changes data; the newest of them is the
# "current dataset timestamp" the drill reports next to the backup time.
ACTIVITY_COLUMNS = (
    ("reservations", "updated_at"),
    ("maintenance_blocks", "created_at"),
    ("usage_records", "recorded_at"),
    ("notifications", "created_at"),
    ("audit_events", "created_at"),
)


class BackupError(RuntimeError):
    """A backup or restore step failed in a way the operator must see."""


# --- connection helpers (shared with restore_drill.py) -------------------------------------------


def connection_parts(url: str) -> dict:
    """Split a connection string into host, port, user, password and dbname."""
    return {k: v for k, v in conninfo_to_dict(url).items() if v not in (None, "")}


def pg_command(tool: str, parts: dict, *args: str) -> tuple[list[str], dict]:
    """Build a PostgreSQL client command line and environment.

    The password goes in PGPASSWORD, not on the command line, so it is not visible in `ps`.
    """
    path = shutil.which(tool)
    if path is None:
        raise BackupError(f"{tool} was not found on PATH. Install the PostgreSQL client tools (version 16).")
    command = [path]
    for flag, key in (("--host", "host"), ("--port", "port"), ("--username", "user")):
        if key in parts:
            command += [flag, str(parts[key])]
    env = dict(os.environ)
    if "password" in parts:
        env["PGPASSWORD"] = parts["password"]
    return command + list(args), env


def run_pg(tool: str, parts: dict, *args: str) -> str:
    command, env = pg_command(tool, parts, *args)
    done = subprocess.run(command, env=env, capture_output=True, text=True)
    if done.returncode != 0:
        raise BackupError(f"{tool} failed (exit {done.returncode}): {done.stderr.strip()[:2000]}")
    return done.stdout


def tool_version(tool: str) -> str:
    path = shutil.which(tool)
    if path is None:
        return "not found"
    return subprocess.run([path, "--version"], capture_output=True, text=True).stdout.strip()


# --- what the database holds ----------------------------------------------------------------------


def table_counts(conn) -> dict[str, int]:
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema() ORDER BY tablename"
        )
    ]
    return {
        name: conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(name))).fetchone()[0]
        for name in tables
    }


def foreign_keys(conn) -> list[dict]:
    """Every foreign key in the current schema, with its columns, for relationship checks."""
    rows = conn.execute(
        """
        SELECT c.conname AS name,
               (SELECT relname FROM pg_class WHERE oid = c.conrelid) AS child,
               (SELECT relname FROM pg_class WHERE oid = c.confrelid) AS parent,
               (SELECT array_agg(a.attname ORDER BY k.ord)
                  FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
                  JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum) AS child_columns,
               (SELECT array_agg(a.attname ORDER BY k.ord)
                  FROM unnest(c.confkey) WITH ORDINALITY AS k(attnum, ord)
                  JOIN pg_attribute a ON a.attrelid = c.confrelid AND a.attnum = k.attnum) AS parent_columns
        FROM pg_constraint c
        WHERE c.contype = 'f' AND c.connamespace = current_schema()::regnamespace
        ORDER BY c.conname
        """
    ).fetchall()
    return [
        dict(zip(("name", "child", "parent", "child_columns", "parent_columns"), r, strict=True))
        for r in rows
    ]


def sample_digests(conn, ids: list[str] | None = None, limit: int = SAMPLE_SIZE) -> dict[str, str]:
    """Digest of whole reservation rows for a fixed sample (or for the given ids).

    The sample is the reservations with the smallest md5(id), so the same database always yields
    the same sample. Run with the session time zone set to UTC or the text of timestamps differs.
    """
    if ids is None:
        rows = conn.execute(
            "SELECT r.id::text, md5(r::text) FROM reservations r ORDER BY md5(r.id::text) LIMIT %s",
            (limit,),
        )
    else:
        rows = conn.execute(
            "SELECT r.id::text, md5(r::text) FROM reservations r WHERE r.id::text = ANY(%s)", (ids,)
        )
    return {row[0]: row[1] for row in rows}


def latest_activity(conn) -> datetime | None:
    """The newest change timestamp across the tables the application writes to."""
    present = {
        r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")
    }
    parts = [
        sql.SQL("SELECT max({}) AS ts FROM {}").format(sql.Identifier(col), sql.Identifier(table))
        for table, col in ACTIVITY_COLUMNS
        if table in present
    ]
    if not parts:
        return None
    query = sql.SQL("SELECT max(ts) FROM ({}) AS t").format(sql.SQL(" UNION ALL ").join(parts))
    return conn.execute(query).fetchone()[0]


def snapshot_manifest(conn) -> dict:
    """Describe the database as seen by the current (repeatable-read) transaction."""
    taken_at = conn.execute("SELECT now()").fetchone()[0]
    newest = latest_activity(conn)
    return {
        "manifest_version": MANIFEST_VERSION,
        "taken_at": taken_at.astimezone(timezone.utc).isoformat(),
        "database": conn.execute("SELECT current_database()").fetchone()[0],
        "server_version": conn.execute("SHOW server_version").fetchone()[0],
        "latest_dataset_change_at": newest.astimezone(timezone.utc).isoformat() if newest else None,
        "table_counts": table_counts(conn),
        "foreign_key_count": len(foreign_keys(conn)),
        "sample_reservation_digests": sample_digests(conn),
    }


# --- the backup itself ----------------------------------------------------------------------------


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def take_backup(database_url: str, backup_dir: Path, keep: int = DEFAULT_KEEP) -> Path:
    """Write one backup and its manifest; return the manifest path."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    parts = connection_parts(database_url)
    dbname = parts.get("dbname")
    if not dbname:
        raise BackupError("The database URL must name a database.")

    with psycopg.connect(database_url) as conn:
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        conn.execute("SET TIME ZONE 'UTC'")
        snapshot_id = conn.execute("SELECT pg_export_snapshot()").fetchone()[0]
        manifest = snapshot_manifest(conn)
        stamp = datetime.fromisoformat(manifest["taken_at"]).strftime("%Y%m%dT%H%M%SZ")
        dump = backup_dir / f"lab-{stamp}.dump"
        partial = dump.with_name(dump.name + ".partial")
        # The snapshot stays valid only while this transaction is open, so dump inside the block.
        run_pg(
            "pg_dump",
            parts,
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            f"--snapshot={snapshot_id}",
            f"--file={partial}",
            f"--dbname={dbname}",
        )
        conn.rollback()

    partial.replace(dump)
    run_pg("pg_restore", parts, "--list", str(dump))  # the archive must be readable
    manifest["dump_file"] = dump.name
    manifest["dump_bytes"] = dump.stat().st_size
    manifest["dump_sha256"] = sha256_of(dump)
    manifest["pg_dump_version"] = tool_version("pg_dump")

    manifest_path = dump.with_suffix(".manifest.json")
    temp = manifest_path.with_name(manifest_path.name + ".partial")
    temp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    temp.replace(manifest_path)
    prune(backup_dir, keep)
    return manifest_path


def prune(backup_dir: Path, keep: int) -> list[Path]:
    """Delete everything but the newest ``keep`` backups; return what was removed."""
    manifests = sorted(backup_dir.glob("lab-*.manifest.json"))
    removed = []
    for old in manifests[: max(len(manifests) - keep, 0)]:
        dump = old.with_name(old.name.removesuffix(".manifest.json") + ".dump")
        for path in (dump, old):
            if path.exists():
                path.unlink()
                removed.append(path)
    return removed


def latest_manifest(backup_dir: Path) -> Path:
    manifests = sorted(backup_dir.glob("lab-*.manifest.json"))
    if not manifests:
        raise BackupError(f"No backup found in {backup_dir}. Run scripts/backup_db.py first.")
    return manifests[-1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Take a database backup and its manifest (LAB-NF-005).")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("BACKUP_DATABASE_URL") or os.environ.get("FLASK_DATABASE_URL"),
        help="Database to back up (default: $BACKUP_DATABASE_URL, then $FLASK_DATABASE_URL).",
    )
    parser.add_argument("--backup-dir", default="backups", type=Path, help="Where to write backups.")
    parser.add_argument("--keep", default=DEFAULT_KEEP, type=int, help="Backups to keep (default 14).")
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error("give --database-url or set BACKUP_DATABASE_URL")
    try:
        manifest_path = take_backup(args.database_url, args.backup_dir, args.keep)
    except (BackupError, psycopg.Error) as exc:
        print(f"BACKUP FAILED: {exc}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text())
    rows = sum(manifest["table_counts"].values())
    print(
        f"Backup OK: {manifest['dump_file']} ({manifest['dump_bytes']} bytes, {rows} rows in "
        f"{len(manifest['table_counts'])} tables), snapshot taken {manifest['taken_at']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
