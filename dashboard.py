#!/usr/bin/env python3
"""
Job Application Dashboard & Retrospective Analysis
Provides insights into application quality over time and tech stack patterns.
"""

import os
import re
from collections import defaultdict
from datetime import datetime
import psycopg2


def get_db_connection():
    """Connect to NeonDB PostgreSQL"""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        return None
    return psycopg2.connect(db_url)


def load_applications_data():
    """Load application data with history"""
    conn = get_db_connection()
    if not conn:
        return [], []

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, job_id, company, role_title, job_url, applied_date, 
                   current_stage, quality_score FROM applications
            ORDER BY applied_date DESC
        """)
        apps = [
            {
                "id": row[0],
                "job_id": row[1],
                "company": row[2],
                "role_title": row[3],
                "job_url": row[4],
                "applied_date": row[5],
                "current_stage": row[6],
                "quality_score": row[7],
            }
            for row in cursor.fetchall()
        ]

        cursor.execute("""
            SELECT a.job_id, a.company, a.role_title, h.stage, h.updated_at
            FROM applications_history h
            JOIN applications a ON h.job_id = a.job_id
            ORDER BY h.updated_at DESC
        """)
        history = [
            {
                "job_id": row[0],
                "company": row[1],
                "role_title": row[2],
                "stage": row[3],
                "updated_at": row[4],
            }
            for row in cursor.fetchall()
        ]
        cursor.close()
        return apps, history
    except Exception as e:
        print(f"Error loading data: {e}")
        return [], []
    finally:
        conn.close()


def analyze_quality_distribution(apps: list[dict]) -> dict:
    """Analyze quality score distribution"""
    if not apps:
        return {}

    scores = [a["quality_score"] for a in apps if a["quality_score"]]
    if not scores:
        return {}

    return {
        "total_applications": len(apps),
        "average_quality": round(sum(scores) / len(scores), 1),
        "high_quality_count": sum(1 for s in scores if s >= 85),
        "medium_quality_count": sum(1 for s in scores if 70 <= s < 85),
        "low_quality_count": sum(1 for s in scores if s < 70),
        "min_score": min(scores),
        "max_score": max(scores),
    }


def analyze_stage_distribution(apps: list[dict]) -> dict:
    """Analyze applications by stage"""
    stages = defaultdict(int)
    for app in apps:
        stages[app["current_stage"]] += 1
    return dict(stages)


def analyze_tech_patterns(apps: list[dict]) -> dict:
    """Extract tech patterns from high-quality applications"""
    # This would require fetching job descriptions again
    # For now, we track which companies appear in high-quality matches
    high_quality_companies = defaultdict(int)
    high_quality_count = 0

    for app in apps:
        if app["quality_score"] and app["quality_score"] >= 85:
            high_quality_companies[app["company"]] += 1
            high_quality_count += 1

    return {
        "high_quality_count": high_quality_count,
        "top_companies": sorted(
            high_quality_companies.items(), key=lambda x: x[1], reverse=True
        )[:5],
    }


def print_dashboard(apps: list[dict], history: list[dict]):
    """Pretty-print the dashboard"""
    if not apps:
        print("\n📊 No applications tracked yet.\n")
        return

    quality = analyze_quality_distribution(apps)
    stages = analyze_stage_distribution(apps)
    tech = analyze_tech_patterns(apps)

    print("\n" + "=" * 70)
    print("📊 JOB APPLICATION DASHBOARD".center(70))
    print("=" * 70)

    # Quality Score Summary
    print("\n📈 QUALITY SCORE ANALYSIS")
    print("-" * 70)
    print(f"   Total Applications: {quality.get('total_applications', 0)}")
    print(f"   Average Quality Score: {quality.get('average_quality', 'N/A')}/100")
    print(f"   ⭐ Excellent (≥85): {quality.get('high_quality_count', 0)} apps")
    print(f"   ✅ Strong (70-84): {quality.get('medium_quality_count', 0)} apps")
    print(f"   🔶 Moderate (<70): {quality.get('low_quality_count', 0)} apps")

    # Application Stage Summary
    print("\n📋 APPLICATION STAGES")
    print("-" * 70)
    for stage, count in sorted(stages.items(), key=lambda x: x[1], reverse=True):
        status_icon = {
            "applied": "📤",
            "interviewing": "🗣️",
            "rejected": "❌",
            "offer": "🎉",
        }.get(stage, "📌")
        print(f"   {status_icon} {stage.capitalize()}: {count}")

    # Top Companies for Quality Matches
    print("\n🏆 TOP COMPANIES (High-Quality Matches)")
    print("-" * 70)
    if tech.get("top_companies"):
        for idx, (company, count) in enumerate(tech["top_companies"], 1):
            print(f"   {idx}. {company}: {count} high-quality matches")
    else:
        print("   No high-quality matches yet")

    # Recent Applications
    print("\n📅 RECENT APPLICATIONS (Last 10)")
    print("-" * 70)
    for app in apps[:10]:
        score_badge = "⭐" if app["quality_score"] >= 85 else "✅" if app["quality_score"] >= 70 else "🔶"
        date_str = app["applied_date"].strftime("%Y-%m-%d") if app["applied_date"] else "N/A"
        print(
            f"   {score_badge} [{date_str}] {app['role_title']} @ {app['company']}"
        )
        print(f"      Score: {app['quality_score']}/100 | Stage: {app['current_stage']}")

    print("\n" + "=" * 70 + "\n")


def main():
    """Main dashboard display"""
    print("Loading application data...")
    apps, history = load_applications_data()
    print_dashboard(apps, history)

    # Summary for strategic insights
    if apps:
        quality = analyze_quality_distribution(apps)
        if quality.get("average_quality"):
            print(f"💡 STRATEGIC INSIGHT:")
            print(f"   Your average application quality is {quality.get('average_quality')}/100")

            if quality.get("average_quality") >= 80:
                print(
                    "   This indicates strong alignment with job market targeting."
                )
            elif quality.get("average_quality") >= 65:
                print(
                    "   Consider refining search filters for better quality matches."
                )
            else:
                print(
                    "   Current filters may need adjustment for better fit."
                )


if __name__ == "__main__":
    main()
