#!/usr/bin/env python3
"""
Update Application Stage Utility
Usage: python3 update_application.py <job_id> <new_stage>
Stages: applied | interviewing | rejected | offer
"""

import sys
import os
import psycopg2


def get_db_connection():
    """Connect to NeonDB PostgreSQL"""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        return None
    return psycopg2.connect(db_url)


def find_application_by_company_role(company: str, role: str) -> dict | None:
    """Find application by partial company/role match"""
    conn = get_db_connection()
    if not conn:
        return None

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT job_id, company, role_title, current_stage FROM applications
            WHERE company ILIKE %s AND role_title ILIKE %s
            LIMIT 1
        """, (f"%{company}%", f"%{role}%"))
        row = cursor.fetchone()
        cursor.close()
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


def update_application_stage(job_id: str, new_stage: str):
    """Update application stage and record history"""
    conn = get_db_connection()
    if not conn:
        return False

    valid_stages = ["applied", "interviewing", "rejected", "offer"]
    if new_stage.lower() not in valid_stages:
        print(f"ERROR: Invalid stage. Must be one of: {', '.join(valid_stages)}")
        return False

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE applications SET current_stage = %s WHERE job_id = %s
        """,
            (new_stage.lower(), job_id),
        )
        cursor.execute(
            """
            INSERT INTO applications_history (job_id, stage) VALUES (%s, %s)
        """,
            (job_id, new_stage.lower()),
        )
        conn.commit()
        cursor.close()
        return True
    except Exception as e:
        print(f"Error updating: {e}")
        return False
    finally:
        conn.close()


def list_applications():
    """List all applications"""
    conn = get_db_connection()
    if not conn:
        return

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT job_id, company, role_title, applied_date, current_stage, quality_score
            FROM applications
            ORDER BY applied_date DESC
        """)
        results = cursor.fetchall()
        cursor.close()

        if not results:
            print("No applications found.")
            return

        print("\n" + "=" * 100)
        print("APPLICATIONS".center(100))
        print("=" * 100)
        print(
            f"{'Job ID':<30} {'Company':<15} {'Role':<25} {'Stage':<15} {'Score':<6}"
        )
        print("-" * 100)

        for row in results:
            job_id = row[0][:30]
            company = row[1][:15]
            role = row[2][:25]
            stage = row[4][:15]
            score = f"{row[5]}/100" if row[5] else "N/A"
            print(f"{job_id:<30} {company:<15} {role:<25} {stage:<15} {score:<6}")

        print("=" * 100 + "\n")
    except Exception as e:
        print(f"Error listing: {e}")
    finally:
        conn.close()


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 update_application.py list                                 # List all applications")
        print("  python3 update_application.py <job_id> <stage>                     # Update by job_id")
        print("  python3 update_application.py search <company> <role> <stage>      # Search and update")
        print("\nValid stages: applied, interviewing, rejected, offer")
        return

    command = sys.argv[1].lower()

    if command == "list":
        list_applications()
    elif command == "search" and len(sys.argv) >= 5:
        company = sys.argv[2]
        role = sys.argv[3]
        new_stage = sys.argv[4]

        app = find_application_by_company_role(company, role)
        if app:
            print(f"Found: {app['role_title']} @ {app['company']}")
            print(f"Current stage: {app['current_stage']}")
            if update_application_stage(app["job_id"], new_stage):
                print(f"✅ Updated to: {new_stage}")
            else:
                print("❌ Failed to update")
        else:
            print(f"No application found for '{company}' + '{role}'")
    elif len(sys.argv) >= 3:
        job_id = sys.argv[1]
        new_stage = sys.argv[2]
        if update_application_stage(job_id, new_stage):
            print(f"✅ Updated application {job_id} to {new_stage}")
        else:
            print(f"❌ Failed to update {job_id}")
    else:
        print("Invalid arguments. Use 'python3 update_application.py' for usage.")


if __name__ == "__main__":
    main()
