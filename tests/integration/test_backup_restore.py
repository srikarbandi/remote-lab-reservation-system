"""Backup and restore drill (TC-NF-005, LAB-NF-005).

The drill scripts live in scripts/. These tests run them against a throw-away database on the
TEST_DATABASE_URL server and check both directions: a good backup restores and passes every check,
and the drill really fails when the backup is stale, corrupted, or does not match its manifest.

They need the PostgreSQL client tools (pg_dump, pg_restore) and a role that may CREATE DATABASE;
without those they are skipped. A passing run here supports TC-NF-005 but is not the drill on the
isolated test deployment, which is what marks the case executed.
"""

import json
import os
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import backup_db  # noqa: E402
import restore_drill  # noqa: E402
import synthetic_data  # noqa: E402


def _check(result, name):
    return next(c for c in result.checks if c.name == name)


def _database_exists(admin_dsn, name):
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        return conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone() is not None


@pytest.fixture(scope="module")
def server():
    """Admin connection string for the test server, or skip when the drill cannot run here."""
    base = os.environ.get("TEST_DATABASE_URL")
    if not base:
        pytest.skip("TEST_DATABASE_URL is not set; skipping database integration tests")
    if shutil.which("pg_dump") is None or shutil.which("pg_restore") is None:
        pytest.skip("PostgreSQL client tools (pg_dump, pg_restore) are not installed")
    return make_conninfo(base, dbname="postgres", options="")


@pytest.fixture(scope="module")
def source_url(server):
    """A scratch database with the schema and a small synthetic dataset."""
    name = f"lab_nf5_{uuid4().hex[:8]}"
    try:
        with psycopg.connect(server, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    except psycopg.errors.InsufficientPrivilege:
        pytest.skip("The test role may not CREATE DATABASE")
    url = make_conninfo(server, dbname=name)
    with psycopg.connect(url, autocommit=True) as conn:
        synthetic_data.load_schema(conn)
        synthetic_data.seed(conn, labs=2, equipment_per_lab=3, students=10, reservations=90)
    yield url
    with psycopg.connect(server, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture()
def backups(tmp_path):
    return tmp_path / "backups"


def _rewrite_manifest(backups, change):
    path = backup_db.latest_manifest(backups)
    manifest = json.loads(path.read_text())
    change(manifest)
    path.write_text(json.dumps(manifest))


# --- the drill passes on a good backup ------------------------------------------------------------


def test_tc_nf_005_latest_backup_restores_and_passes_every_check(server, source_url, backups):
    backup_db.take_backup(source_url, backups)

    result = restore_drill.run_drill(source_url, backups, simulate_writes=3)

    failed = [c for c in result.checks if not c.passed]
    assert not failed, [f"{c.name}: {c.detail}" for c in failed]
    assert result.restored_counts == result.manifest["table_counts"]
    assert result.restore_seconds < 60 * 60
    assert result.backup_age < timedelta(hours=24)
    # The copy is a new database, removed after the drill.
    assert not _database_exists(server, result.restored_db)


def test_tc_nf_005_restore_matches_the_backup_not_the_live_data(server, source_url, backups):
    backup_db.take_backup(source_url, backups)
    live_before = restore_drill._observe_source(source_url)[2]["audit_events"]

    result = restore_drill.run_drill(source_url, backups, simulate_writes=5)

    assert result.passed
    assert result.restored_counts["audit_events"] == live_before
    assert result.source_counts["audit_events"] == live_before + 5  # written after the recovery point


def test_tc_nf_005_restores_the_newest_of_several_backups(source_url, backups):
    backup_db.take_backup(source_url, backups)
    time.sleep(1.1)  # backup file names have one-second resolution
    restore_drill._write_after_backup(source_url, 2)
    newest = backup_db.take_backup(source_url, backups)

    result = restore_drill.run_drill(source_url, backups)

    assert result.manifest["dump_file"] == json.loads(newest.read_text())["dump_file"]
    assert result.passed


def test_tc_nf_005_restores_from_another_server_when_the_source_is_down(server, source_url, backups):
    backup_db.take_backup(source_url, backups)
    dead_source = make_conninfo(source_url, host="127.0.0.1", port="1")  # nothing listens on port 1

    result = restore_drill.run_drill(dead_source, backups, admin_url=server)

    assert result.passed, [c.detail for c in result.checks if not c.passed]
    assert result.failure_clock.startswith("local clock")
    assert result.source_counts is None


# --- the drill fails when it should ---------------------------------------------------------------


def test_tc_nf_005_fails_when_the_newest_backup_is_older_than_24_hours(source_url, backups):
    backup_db.take_backup(source_url, backups)

    def make_old(manifest):
        old = datetime.fromisoformat(manifest["taken_at"]) - timedelta(hours=25)
        manifest["taken_at"] = old.astimezone(timezone.utc).isoformat()

    _rewrite_manifest(backups, make_old)

    result = restore_drill.run_drill(source_url, backups)

    assert not result.passed
    assert not _check(result, "Recovery point within limit").passed


def test_tc_nf_005_fails_when_restore_takes_longer_than_the_limit(source_url, backups):
    backup_db.take_backup(source_url, backups)

    result = restore_drill.run_drill(source_url, backups, rto_minutes=0)

    assert not _check(result, "Recovery time within limit").passed
    assert not result.passed


def test_tc_nf_005_does_not_restore_a_corrupted_backup(server, source_url, backups):
    manifest_path = backup_db.take_backup(source_url, backups)
    dump = backups / json.loads(manifest_path.read_text())["dump_file"]
    data = bytearray(dump.read_bytes())
    data[len(data) // 2] ^= 0xFF
    dump.write_bytes(bytes(data))

    result = restore_drill.run_drill(source_url, backups)

    assert not result.passed
    assert not _check(result, "Backup file is intact").passed
    assert all(c.name != "Restore into a clean isolated database" for c in result.checks)
    assert not _database_exists(server, result.restored_db)


def test_tc_nf_005_fails_when_restored_counts_differ_from_the_backup_snapshot(source_url, backups):
    backup_db.take_backup(source_url, backups)

    def inflate(manifest):
        manifest["table_counts"]["reservations"] += 1

    _rewrite_manifest(backups, inflate)

    result = restore_drill.run_drill(source_url, backups)

    count_check = _check(result, "Row counts match the backup snapshot")
    assert not count_check.passed
    assert "reservations" in count_check.detail


def test_tc_nf_005_fails_when_a_sampled_booking_differs(source_url, backups):
    backup_db.take_backup(source_url, backups)

    def change_one_digest(manifest):
        digests = manifest["sample_reservation_digests"]
        digests[next(iter(digests))] = "0" * 32

    _rewrite_manifest(backups, change_one_digest)

    result = restore_drill.run_drill(source_url, backups)

    sample_check = _check(result, "Sampled booking records match")
    assert not sample_check.passed
    assert "24 of 25" in sample_check.detail


def test_tc_nf_005_fails_without_any_backup(source_url, backups):
    with pytest.raises(backup_db.BackupError, match="No backup found"):
        restore_drill.run_drill(source_url, backups)


# --- backup job housekeeping (no database needed) ------------------------------------------------


def test_tc_nf_005_retention_keeps_only_the_newest_backups(tmp_path):
    for day in range(1, 6):
        stem = f"lab-2026110{day}T020000Z"
        (tmp_path / f"{stem}.dump").write_bytes(b"x")
        (tmp_path / f"{stem}.manifest.json").write_text("{}")

    removed = backup_db.prune(tmp_path, keep=2)

    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == [
        "lab-20261104T020000Z.dump",
        "lab-20261104T020000Z.manifest.json",
        "lab-20261105T020000Z.dump",
        "lab-20261105T020000Z.manifest.json",
    ]
    assert len(removed) == 6


def test_tc_nf_005_backup_and_manifest_describe_the_same_snapshot(source_url, backups):
    manifest = json.loads(backup_db.take_backup(source_url, backups).read_text())

    assert manifest["table_counts"]["reservations"] == 90
    assert len(manifest["sample_reservation_digests"]) == backup_db.SAMPLE_SIZE
    assert manifest["foreign_key_count"] > 0
    assert (backups / manifest["dump_file"]).stat().st_size == manifest["dump_bytes"]
    assert backup_db.sha256_of(backups / manifest["dump_file"]) == manifest["dump_sha256"]
