#!/usr/bin/env python3
"""
Idempotent schema migration for the multi-profile tracker.

`init_db()` only ever runs CREATE TABLE IF NOT EXISTS, so it cannot upgrade a
database that already has the old single-profile tables. Run this once against
each environment:

    python3 migrate_db.py --dry-run     # show what would change
    python3 migrate_db.py               # apply

Changes made:
  1. seen_jobs            gains `profile`; primary key becomes (profile, job_id)
  2. applications         gains `profile`; unique key becomes (profile, job_id)
  3. applications_history switches from `job_id` to `application_id`, with an
     ON DELETE CASCADE foreign key to applications(id)

Existing rows are backfilled with --backfill-profile (default: "engineering"),
on the assumption that everything recorded before this migration came from the
original hardcoded config.

Safe to run repeatedly: every step checks the current schema first.

NOTE: this script issues ALTER TABLE, which in Postgres only a table's owner
may do. The tracker's day-to-day role only holds SELECT/INSERT/UPDATE/DELETE,
so run this with a DATABASE_URL for the role that owns the tables, then switch
back. A permission error here means you are connected as the wrong role.
"""

import argparse
import sys

from track_jobs import PROFILE_NAME_PATTERN, get_db_connection


def _column_exists(cursor, table: str, column: str) -> bool:
  cursor.execute("""
    SELECT 1 FROM information_schema.columns
    WHERE table_name = %s AND column_name = %s
  """, (table, column))
  return cursor.fetchone() is not None


def _table_exists(cursor, table: str) -> bool:
  cursor.execute("""
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = %s
  """, (table,))
  return cursor.fetchone() is not None


def _constraint_exists(cursor, name: str) -> bool:
  cursor.execute(
    "SELECT 1 FROM pg_constraint WHERE conname = %s", (name,)
  )
  return cursor.fetchone() is not None


def _log(steps: list[str], message: str):
  print(f"  {message}")
  steps.append(message)


def migrate_seen_jobs(cursor, backfill: str, steps: list[str]):
  """Add `profile` to seen_jobs and repoint the primary key."""
  if not _table_exists(cursor, "seen_jobs"):
    _log(steps, "seen_jobs does not exist yet - init_db() will create it")
    return

  if _column_exists(cursor, "seen_jobs", "profile"):
    _log(steps, "seen_jobs.profile already present - skipping")
    return

  _log(steps, f"seen_jobs: adding profile column (backfill '{backfill}')")
  cursor.execute(
    "ALTER TABLE seen_jobs ADD COLUMN profile TEXT NOT NULL DEFAULT %s",
    (backfill,),
  )
  # The default was only needed to backfill; new writes must be explicit.
  cursor.execute("ALTER TABLE seen_jobs ALTER COLUMN profile DROP DEFAULT")

  _log(steps, "seen_jobs: repointing primary key to (profile, job_id)")
  cursor.execute("ALTER TABLE seen_jobs DROP CONSTRAINT IF EXISTS seen_jobs_pkey")
  cursor.execute("ALTER TABLE seen_jobs ADD PRIMARY KEY (profile, job_id)")


def migrate_applications(cursor, backfill: str, steps: list[str]):
  """Add `profile` to applications and repoint the uniqueness constraint."""
  if not _table_exists(cursor, "applications"):
    _log(steps, "applications does not exist yet - init_db() will create it")
    return

  if _column_exists(cursor, "applications", "profile"):
    _log(steps, "applications.profile already present - skipping")
    return

  _log(steps, f"applications: adding profile column (backfill '{backfill}')")
  cursor.execute(
    "ALTER TABLE applications ADD COLUMN profile TEXT NOT NULL DEFAULT %s",
    (backfill,),
  )
  cursor.execute("ALTER TABLE applications ALTER COLUMN profile DROP DEFAULT")

  # The old UNIQUE(job_id) would stop two profiles ever tracking the same
  # posting, so it has to go before the composite one is added.
  _log(steps, "applications: replacing UNIQUE(job_id) with UNIQUE(profile, job_id)")
  cursor.execute(
    "ALTER TABLE applications DROP CONSTRAINT IF EXISTS applications_job_id_key"
  )
  if not _constraint_exists(cursor, "applications_profile_job_id_key"):
    cursor.execute("""
      ALTER TABLE applications
      ADD CONSTRAINT applications_profile_job_id_key UNIQUE (profile, job_id)
    """)


def migrate_history(cursor, steps: list[str]):
  """Move applications_history from job_id onto application_id."""
  if not _table_exists(cursor, "applications_history"):
    _log(steps, "applications_history does not exist yet - init_db() will create it")
    return

  if _column_exists(cursor, "applications_history", "application_id"):
    _log(steps, "applications_history.application_id already present - skipping")
    return

  _log(steps, "applications_history: adding application_id column")
  cursor.execute("ALTER TABLE applications_history ADD COLUMN application_id INTEGER")

  if _column_exists(cursor, "applications_history", "job_id"):
    _log(steps, "applications_history: backfilling application_id from job_id")
    cursor.execute("""
      UPDATE applications_history h
      SET application_id = a.id
      FROM applications a
      WHERE h.job_id = a.job_id
    """)

    # Rows whose application was deleted can't be repointed; the old FK meant
    # they shouldn't exist, but check rather than assume.
    cursor.execute(
      "SELECT COUNT(*) FROM applications_history WHERE application_id IS NULL"
    )
    orphans = cursor.fetchone()[0]
    if orphans:
      _log(steps, f"applications_history: deleting {orphans} orphaned row(s)")
      cursor.execute(
        "DELETE FROM applications_history WHERE application_id IS NULL"
      )

    _log(steps, "applications_history: dropping job_id column")
    cursor.execute(
      "ALTER TABLE applications_history DROP CONSTRAINT IF EXISTS "
      "applications_history_job_id_fkey"
    )
    cursor.execute("ALTER TABLE applications_history DROP COLUMN job_id")

  _log(steps, "applications_history: adding NOT NULL + cascading foreign key")
  cursor.execute(
    "ALTER TABLE applications_history ALTER COLUMN application_id SET NOT NULL"
  )
  cursor.execute("""
    ALTER TABLE applications_history
    ADD CONSTRAINT applications_history_application_id_fkey
    FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
  """)


def run_migration(backfill: str, dry_run: bool) -> int:
  conn = get_db_connection()
  if not conn:
    return 1

  steps: list[str] = []
  try:
    with conn.cursor() as cursor:
      print("Migrating schema...")
      migrate_seen_jobs(cursor, backfill, steps)
      # History must migrate before applications: its old foreign key depends
      # on the UNIQUE(job_id) index that migrate_applications drops, and
      # Postgres refuses to drop a constraint another object depends on.
      migrate_history(cursor, steps)
      migrate_applications(cursor, backfill, steps)

      if dry_run:
        conn.rollback()
        print(f"\nDry run: rolled back {len(steps)} step(s). Nothing was changed.")
      else:
        conn.commit()
        print(f"\nMigration complete ({len(steps)} step(s)).")
    return 0
  except Exception as e:
    conn.rollback()
    print(f"\nMigration failed and was rolled back: {e}")
    return 1
  finally:
    conn.close()


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument(
    "--backfill-profile",
    default="engineering",
    help="Profile name to assign to pre-existing rows (default: engineering)",
  )
  parser.add_argument(
    "--dry-run",
    action="store_true",
    help="Run the migration in a transaction and roll it back",
  )
  args = parser.parse_args()

  if not PROFILE_NAME_PATTERN.match(args.backfill_profile):
    print(
      f"ERROR: invalid profile name {args.backfill_profile!r}"
      " (expected lowercase letters, digits and hyphens)"
    )
    return 1

  return run_migration(args.backfill_profile, args.dry_run)


if __name__ == "__main__":
  sys.exit(main())
