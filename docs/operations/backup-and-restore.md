# Backup and restore (LAB-NF-005, TC-NF-005)

**Requirement.** The system takes a daily database backup. After a failure, data is recovered to a point no more than 24 hours old (RPO 24 h) and service is restored within 60 minutes (RTO 60 min). Design reference: SAD DS-Recovery. Test case: STP TC-NF-005. Owner: Sreekar Bandi.

## What is in the repo

| File | Purpose |
|---|---|
| `scripts/backup_db.py` | The daily backup job. Writes a `pg_dump` archive and a manifest (counts, foreign-key count, row digests of a fixed sample of reservations) from one consistent snapshot. Keeps the newest 14 backups. |
| `scripts/restore_drill.py` | The TC-NF-005 drill. Restores the newest backup into a new, clean database, runs the checks, times the whole thing, and writes a log. |
| `scripts/synthetic_data.py` | Synthetic dataset for the drill and for the load test (TC-NF-001). Never real data. |
| `tests/integration/test_backup_restore.py` | Automated checks that the drill passes on a good backup and fails on a stale, corrupted or mismatching one. |

The backups and manifests are git-ignored. Never commit them.

## Prerequisites

PostgreSQL client tools at version 16 or newer on the machine that runs the scripts (`pg_dump`, `pg_restore`): `apt install postgresql-client-16`, or `brew install libpq` and add it to `PATH`. The database role needs `CREATE DATABASE` for the drill (the local `lab` role from `docker-compose.yml` has it).

## The daily job

```bash
export BACKUP_DATABASE_URL=postgresql://lab:<password>@<host>:5432/lab
python scripts/backup_db.py --backup-dir /srv/lab-backups
```

Run it once a day from the host scheduler, for example cron at 02:17:

```cron
17 2 * * *  cd /srv/lab && .venv/bin/python scripts/backup_db.py --backup-dir /srv/lab-backups >> /var/log/lab-backup.log 2>&1
```

Put the backup directory on storage separate from the live database, readable only by the service account (`chmod 700`). A non-zero exit means the backup failed and must be looked at; the newest manifest's age is the real recovery point.

## Running the drill

1. Seed a scratch database if you do not have one: `python scripts/synthetic_data.py --init-schema --database-url <scratch-url>`.
2. Make sure at least one scheduled backup exists in the backup directory.
3. Run:

   ```bash
   python scripts/restore_drill.py --source-url <live-or-scratch-url> --backup-dir /srv/lab-backups \
       --run-type "Formal execution" --where "<host and PostgreSQL version>" \
       --log docs/test-execution/drill-logs/tc-nf-005-<date>.md
   ```

4. The exit code is 0 only if every check passes. The log records the times, the checks and the counts.
5. Link the log in the `evidence_link` column of the TC-NF-005 row in `docs/test-execution/execution-register.csv` and set the status from what the log says.

What the drill checks: recovery point (backup age at the simulated failure is at most 24 h), backup file checksum, restore into a clean database, row counts equal the manifest, foreign keys present with no orphan rows, the sampled reservations are identical row for row, the application starts against the restored database (`/healthz` and the utilization report), and recovery time (restore initiation to application validation) is at most 60 minutes.

To simulate a real failure, stop the source database and restore onto another server: `--source-url <dead-url> --admin-url <recovery-server-url>`. The failure time then comes from the local clock.

`--take-backup` and `--simulate-writes N` are for development drills on a scratch database only. A backup taken by the drill itself says nothing about the daily schedule.

## What still has to happen on the test deployment

- The daily job has to be scheduled there and seen to run on consecutive days; the drill then uses a backup the job made, not one the drill made.
- Time the drill on a dataset of realistic size. The development dry run used a few thousand rows.
- Use a separate server for the restore (`--admin-url`) if the deployment has one.
- Encryption of backups at rest is not handled by these scripts.
