#!/usr/bin/env python3
"""
Update Application Stage Utility

Usage:
  python3 update_application.py list
  python3 update_application.py <job_id> <stage>
  python3 update_application.py search <company> <role> <stage>

Stages: applied | interviewing | rejected | offer

Every command operates on a single profile. Pass --profile <path/to.yml> to
target a profile other than the built-in default.
"""

import argparse
import sys

from track_jobs import (
    get_db_connection,
    load_applications,
    load_profile,
    update_application_stage,
)

VALID_STAGES = ("applied", "interviewing", "rejected", "offer")


def find_application_by_company_role(
    company: str, role: str, profile_name: str
) -> dict | None:
    """Find an application by partial company/role match within one profile."""
    conn = get_db_connection()
    if not conn:
        return None
    try:
        with conn, conn.cursor() as cursor:
            cursor.execute("""
                SELECT job_id, company, role_title, current_stage
                FROM applications
                WHERE profile = %s AND company ILIKE %s AND role_title ILIKE %s
                LIMIT 1
            """, (profile_name, f"%{company}%", f"%{role}%"))
            row = cursor.fetchone()
            if row:
                return {
                    "job_id": row[0],
                    "company": row[1],
                    "role_title": row[2],
                    "current_stage": row[3],
                }
    except Exception as e:
        print(f"Error searching: {e}")
    finally:
        conn.close()
    return None


def apply_stage(job_id: str, new_stage: str, profile_name: str) -> bool:
    """Validate the stage name, then hand off to the shared updater."""
    stage = new_stage.lower()
    if stage not in VALID_STAGES:
        print(f"ERROR: Invalid stage. Must be one of: {', '.join(VALID_STAGES)}")
        return False
    return update_application_stage(job_id, stage, profile_name)


def list_applications(profile_name: str):
    """Print this profile's applications, newest first."""
    apps = load_applications(profile_name)
    if not apps:
        print(f"No applications found for profile '{profile_name}'.")
        return

    print("\n" + "=" * 100)
    print(f"APPLICATIONS - {profile_name}".center(100))
    print("=" * 100)
    print(f"{'Job ID':<30} {'Company':<15} {'Role':<25} {'Stage':<15} {'Score':<6}")
    print("-" * 100)

    for app in apps:
        score = f"{app['quality_score']}/100" if app["quality_score"] else "N/A"
        print(
            f"{app['job_id'][:30]:<30} {app['company'][:15]:<15} "
            f"{app['role_title'][:25]:<25} {app['current_stage'][:15]:<15} {score:<6}"
        )

    print("=" * 100 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Update application stages",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--profile",
        help="Path to a YAML profile file. Omit to use the built-in defaults.",
    )
    parser.add_argument(
        "args",
        nargs="*",
        help="list | <job_id> <stage> | search <company> <role> <stage>",
    )
    opts = parser.parse_args()

    if not opts.args:
        parser.print_help()
        return 1

    profile_name = load_profile(opts.profile).name
    command = opts.args[0].lower()

    if command == "list":
        list_applications(profile_name)
        return 0

    if command == "search":
        if len(opts.args) < 4:
            print("Usage: update_application.py search <company> <role> <stage>")
            return 1
        company, role, new_stage = opts.args[1], opts.args[2], opts.args[3]
        app = find_application_by_company_role(company, role, profile_name)
        if not app:
            print(f"No application found for '{company}' + '{role}'")
            return 1
        print(f"Found: {app['role_title']} @ {app['company']}")
        print(f"Current stage: {app['current_stage']}")
        if apply_stage(app["job_id"], new_stage, profile_name):
            print(f"Updated to: {new_stage}")
            return 0
        return 1

    if len(opts.args) >= 2:
        job_id, new_stage = opts.args[0], opts.args[1]
        if apply_stage(job_id, new_stage, profile_name):
            print(f"Updated application {job_id} to {new_stage}")
            return 0
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
