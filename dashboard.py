#!/usr/bin/env python3
"""
Job Application Dashboard & Retrospective Analysis
Provides insights into application quality over time and tech stack patterns.

Reports on a single profile. Pass --profile <path/to.yml> to target a profile
other than the built-in default.
"""

import argparse
from collections import defaultdict

from track_jobs import STAGE_ALERTED, load_applications, load_profile


def split_by_engagement(apps: list[dict]) -> tuple[list[dict], list[dict]]:
    """Separate what the tracker found from what you acted on.

    Everything the tracker cards is stored at stage 'alerted'. Only a human
    action moves a row past that, so this split is the difference between
    "jobs surfaced" and "jobs applied to" -- previously conflated, which made
    every rate computed from this table meaningless.
    """
    alerted = [a for a in apps if a["current_stage"] == STAGE_ALERTED]
    engaged = [a for a in apps if a["current_stage"] != STAGE_ALERTED]
    return alerted, engaged


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


def print_dashboard(apps: list[dict], profile_name: str):
    """Pretty-print the dashboard"""
    if not apps:
        print(f"\n📊 No applications tracked yet for profile '{profile_name}'.\n")
        return

    quality = analyze_quality_distribution(apps)
    stages = analyze_stage_distribution(apps)
    tech = analyze_tech_patterns(apps)
    alerted, engaged = split_by_engagement(apps)

    print("\n" + "=" * 70)
    print(f"📊 JOB APPLICATION DASHBOARD - {profile_name}".center(70))
    print("=" * 70)

    # Conversion Summary
    print("\n🔍 PIPELINE")
    print("-" * 70)
    print(f"   Roles Alerted: {len(apps)}")
    print(f"   Applications Submitted: {len(engaged)}")
    if apps:
        rate = round(100 * len(engaged) / len(apps), 1)
        print(f"   Apply Rate: {rate}%")
    print(f"   Awaiting Action: {len(alerted)}")

    # Quality Score Summary
    print("\n📈 QUALITY SCORE ANALYSIS (all alerted roles)")
    print("-" * 70)
    print(f"   Total Scored: {quality.get('total_applications', 0)}")
    print(f"   Average Quality Score: {quality.get('average_quality', 'N/A')}/100")
    print(f"   ⭐ Excellent (≥85): {quality.get('high_quality_count', 0)} roles")
    print(f"   ✅ Strong (70-84): {quality.get('medium_quality_count', 0)} roles")
    print(f"   🔶 Moderate (<70): {quality.get('low_quality_count', 0)} roles")

    # Application Stage Summary
    print("\n📋 APPLICATION STAGES")
    print("-" * 70)
    for stage, count in sorted(stages.items(), key=lambda x: x[1], reverse=True):
        status_icon = {
            "alerted": "🔔",
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
    print("\n📅 RECENT ALERTS (Last 10)")
    print("-" * 70)
    for app in apps[:10]:
        score = app["quality_score"] or 0
        if score >= 85:
            score_badge = "⭐"
        elif score >= 70:
            score_badge = "✅"
        else:
            score_badge = "🔶"
        date_str = app["applied_date"].strftime("%Y-%m-%d") if app["applied_date"] else "N/A"
        print(
            f"   {score_badge} [{date_str}] {app['role_title']} @ {app['company']}"
        )
        print(f"      Score: {score}/100 | Stage: {app['current_stage']}")

    print("\n" + "=" * 70 + "\n")


def main():
    """Main dashboard display"""
    parser = argparse.ArgumentParser(description="Job application dashboard")
    parser.add_argument(
        "--profile",
        help="Path to a YAML profile file. Omit to use the built-in defaults.",
    )
    args = parser.parse_args()
    profile_name = load_profile(args.profile).name

    print(f"Loading application data for profile '{profile_name}'...")
    apps = load_applications(profile_name)
    print_dashboard(apps, profile_name)

    # Summary for strategic insights
    if apps:
        quality = analyze_quality_distribution(apps)
        if quality.get("average_quality"):
            print("💡 STRATEGIC INSIGHT:")
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
