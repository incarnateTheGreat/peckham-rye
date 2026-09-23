import json
import os
import re
import zoneinfo
from datetime import datetime
import requests
import psycopg2
from psycopg2.extras import execute_values

# =============================================================================
# CONFIGURATION & THRESHOLDS
# =============================================================================
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
SEEN_JOBS_FILE = "seen_jobs.json"

# Salary Targets
MIN_SALARY_USD = 145_000
MIN_SALARY_CAD = 200_000  # Staff/Principal & Senior remote target for Canada
MIN_SALARY_EUR = 130_000

# Target Company Slugs (Add or modify companies here)
# FRONTEND-HEAVY + FULLSTACK COMPANIES
ASHBY_BOARDS = [
    "linear", "ramp", "vanta", "sentry",
    # React/Frontend focused
    "retool", "supabase", "clerk", "plane", "n8n",
    # Sports & Analytics
    "statsbomb", "sportradar",
    # Aviation & Aerospace
    "archer-aviation", "joby-aviation", "volocopter", "lilium",
    # Additional coverage
    "figma", "notion", "zapier", "github", "gitlab", "gitlab-dev",
]
GREENHOUSE_BOARDS = [
    "stripe", "figma", "cloudflare", "datadog",
    # React/Fullstack ecosystem
    "chakra-ui", "hasura", "prisma", "remix",
    # Aviation/Aerospace/Flight
    "bell-flight", "sikorsky", "garmin",
    # Sports Tech
    "genius-sports", "opta-sports", "eleven-sports",
    # Additional coverage
    "airbnb", "pinterest", "twitch", "notion",
]
LEVER_BOARDS = [
    "postman", "vercel",
    # Sports & Data
    "arcane", "statsbomb",
    # Aviation/Aerospace
    "archer", "joby",
    # React-native ecosystem
    "expo", "react-native",
    # Additional coverage
    "github", "gitlab", "zapier",
]
WORKABLE_BOARDS = []

# 1. Title & Role Keyword Rules
INCLUDE_ROLE_KEYWORDS = [
    "full stack",
    "fullstack",
    "frontend",
    "front end",
    "react",
    "product engineer",
    "ui engineer",
    "web engineer",
    "application engineer",
    "typescript",
    "vue.js",
    "next.js",
]
HIGH_LEVEL_KEYWORDS = ["staff", "principal", "lead"]
EXCLUDE_TITLE_EXACT = [
    "platform engineer",
    "devops engineer",
    "site reliability engineer",
    "infrastructure engineer",
    "data engineer",  # Too niche for your needs
    "machine learning",
    "data science",
]

# Description-level keywords: "Software Engineer" titles accepted ONLY if description contains these
REQUIRE_IN_DESCRIPTION = [
    "react",
    "typescript",
    "frontend",
    "full stack",
    "fullstack",
    "next.js",
    "remix",
    "graphql",
]

# 2. Remote & EOR Signal Keywords
REMOTE_POSITIVE = [
    "remote",
    "work from anywhere",
    "anywhere in north america",
    "distributed",
]
REMOTE_NEGATIVE = [
    "hybrid",
    "on-site",
    "onsite",
    "in-office",
    "in office",
    "hybrid remote",
]

EOR_SIGNALS = [
    "eor",
    "employer of record",
    "deel",
    "remote.com",
    "oyster",
    "workmotion",
    "global remote",
    "work from anywhere",
    "international",
    "canada remote",
    "contractor",
    "b2b contract",
    "canada",
]


# =============================================================================
# STATE MANAGEMENT
# =============================================================================
def get_db_connection():
  """Connect to NeonDB PostgreSQL"""
  db_url = os.environ.get("DATABASE_URL")
  if not db_url:
    print("ERROR: DATABASE_URL not set")
    return None
  return psycopg2.connect(db_url)

def init_db():
  """Create seen_jobs and applications tables if they don't exist"""
  conn = get_db_connection()
  if not conn:
    return
  try:
    cursor = conn.cursor()
    cursor.execute("""
      CREATE TABLE IF NOT EXISTS seen_jobs (
        job_id TEXT PRIMARY KEY,
        created_at TIMESTAMP DEFAULT NOW()
      )
    """)
    cursor.execute("""
      CREATE TABLE IF NOT EXISTS applications (
        id SERIAL PRIMARY KEY,
        job_id TEXT UNIQUE NOT NULL,
        company TEXT NOT NULL,
        role_title TEXT NOT NULL,
        job_url TEXT,
        applied_date TIMESTAMP DEFAULT NOW(),
        current_stage TEXT DEFAULT 'applied',
        quality_score INTEGER,
        notes TEXT,
        created_at TIMESTAMP DEFAULT NOW()
      )
    """)
    cursor.execute("""
      CREATE TABLE IF NOT EXISTS applications_history (
        id SERIAL PRIMARY KEY,
        job_id TEXT NOT NULL,
        stage TEXT NOT NULL,
        updated_at TIMESTAMP DEFAULT NOW(),
        FOREIGN KEY (job_id) REFERENCES applications(job_id)
      )
    """)
    conn.commit()
    cursor.close()
  except Exception as e:
    print(f"Error creating table: {e}")
  finally:
    conn.close()

def load_seen_jobs() -> set:
  """Load seen job IDs from NeonDB"""
  conn = get_db_connection()
  if not conn:
    return set()
  try:
    cursor = conn.cursor()
    cursor.execute("SELECT job_id FROM seen_jobs")
    return set(row[0] for row in cursor.fetchall())
  except Exception as e:
    print(f"Error loading from DB: {e}")
    return set()
  finally:
    cursor.close()
    conn.close()

def save_seen_jobs(seen_jobs: set):
  """Save seen job IDs to NeonDB"""
  conn = get_db_connection()
  if not conn:
    return
  try:
    cursor = conn.cursor()
    if seen_jobs:
      # Insert only new job IDs (ignore duplicates)
      values = [(job_id,) for job_id in seen_jobs]
      execute_values(
        cursor,
        "INSERT INTO seen_jobs (job_id) VALUES %s ON CONFLICT DO NOTHING",
        values
      )
    conn.commit()
  except Exception as e:
    print(f"Error saving to DB: {e}")
  finally:
    cursor.close()
    conn.close()


def save_application(job_id: str, company: str, role_title: str, job_url: str, quality_score: int):
  """Save application to tracking database"""
  conn = get_db_connection()
  if not conn:
    return
  try:
    cursor = conn.cursor()
    cursor.execute("""
      INSERT INTO applications (job_id, company, role_title, job_url, quality_score)
      VALUES (%s, %s, %s, %s, %s)
      ON CONFLICT (job_id) DO NOTHING
    """, (job_id, company, role_title, job_url, quality_score))
    conn.commit()
    cursor.close()
  except Exception as e:
    print(f"Error saving application: {e}")
  finally:
    conn.close()


def update_application_stage(job_id: str, new_stage: str):
  """Update application stage and record history"""
  conn = get_db_connection()
  if not conn:
    return
  try:
    cursor = conn.cursor()
    cursor.execute("""
      UPDATE applications SET current_stage = %s WHERE job_id = %s
    """, (new_stage, job_id))
    cursor.execute("""
      INSERT INTO applications_history (job_id, stage) VALUES (%s, %s)
    """, (job_id, new_stage))
    conn.commit()
    cursor.close()
  except Exception as e:
    print(f"Error updating application stage: {e}")
  finally:
    conn.close()


def load_applications() -> list[dict]:
  """Load all applications for dashboard/analysis"""
  conn = get_db_connection()
  if not conn:
    return []
  try:
    cursor = conn.cursor()
    cursor.execute("""
      SELECT id, job_id, company, role_title, job_url, applied_date, 
             current_stage, quality_score FROM applications
      ORDER BY applied_date DESC
    """)
    results = cursor.fetchall()
    return [
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
        for row in results
    ]
  except Exception as e:
    print(f"Error loading applications: {e}")
    return []
  finally:
    cursor.close()
    conn.close()


# =============================================================================
# FILTERING HELPER FUNCTIONS
# =============================================================================
def is_target_role(title: str, description: str = "") -> bool:
  """Filters role titles against target keywords while dropping unwanted domains."""
  t = title.lower().strip()
  d = (description or "").lower()

  # Exclude exact unwanted engineering domains (DevOps, Platform, Infrastructure)
  if any(bad in t for bad in EXCLUDE_TITLE_EXACT):
    return False

  # Require at least one target role keyword
  # Automatically handles "Staff Software Engineer", "Product Engineer", "Full Stack Engineer", etc.
  if any(k in t for k in INCLUDE_ROLE_KEYWORDS):
    return True
  
  # Fallback: Generic "Software Engineer" accepted ONLY if description has specific tech
  if "software engineer" in t:
    return any(keyword in d for keyword in REQUIRE_IN_DESCRIPTION)
  
  return False


def is_fully_remote(location: str, workplace_type: str, description: str) -> bool:
  """Ensures position is strictly remote and not hybrid/onsite."""
  loc_str = (location or "").lower()
  wp_type = (workplace_type or "").lower()
  text = (description or "").lower()

  if wp_type in ["hybrid", "onsite"] or any(
      neg in loc_str for neg in REMOTE_NEGATIVE
  ):
    return False

  return wp_type == "remote" or any(
      p in loc_str or p in text[:500] for p in REMOTE_POSITIVE
  )


def is_eor_supported(location: str, description: str) -> bool:
  """Checks for explicit Employer of Record (EOR) flags or global remote terms."""
  loc_str = (location or "").lower()
  text = (description or "").lower()

  return any(sig in text or sig in loc_str for sig in EOR_SIGNALS)


def parse_salary_info(text: str, comp_data: dict = None) -> tuple[bool, str, str]:
  """Extracts compensation info and returns:

  (meets_threshold: bool, display_text: str, status_tag: str)
  status_tag options: "VERIFIED", "BELOW_THRESHOLD", "UNLISTED"
  """
  # 1. Structured ATS compensation payload
  if comp_data and isinstance(comp_data, dict):
    min_comp = comp_data.get("targetCompensationMin")
    max_comp = comp_data.get("targetCompensationMax")
    currency = (comp_data.get("currency") or "USD").upper()

    if isinstance(min_comp, (int, float)):
      max_str = f" - {int(max_comp):,}" if max_comp else "+"
      display = f"{currency} {int(min_comp):,}{max_str}"

      if (
          (currency == "USD" and min_comp >= MIN_SALARY_USD)
          or (currency == "CAD" and min_comp >= MIN_SALARY_CAD)
          or (currency == "EUR" and min_comp >= MIN_SALARY_EUR)
      ):
        return True, display, "VERIFIED"
      else:
        return False, display, "BELOW_THRESHOLD"

  # 2. Regex fallback scanning description text
  salary_range_pattern = r"(\$|€|USD|CAD|EUR)\s?(\d{2,3}(?:,\d{3})?|\d{2,3}k)\s*(?:-|to)\s*(\$|€|USD|CAD|EUR)?\s?(\d{2,3}(?:,\d{3})?|\d{2,3}k)"
  match = re.search(salary_range_pattern, text, re.IGNORECASE)

  if match:
    raw_match = match.group(0).strip()
    digits = re.findall(r"\d+", raw_match.replace(",", ""))
    if digits:
      low_val = int(digits[0])
      low_val = low_val * 1000 if low_val < 1000 else low_val

      if low_val >= min(MIN_SALARY_USD, MIN_SALARY_CAD, MIN_SALARY_EUR):
        return True, raw_match, "VERIFIED"
      else:
        return False, raw_match, "BELOW_THRESHOLD"

  # 3. Compensation unlisted
  return True, "Unlisted in posting", "UNLISTED"


def extract_key_signals(content: str) -> str:
  """Scans text for primary tech keywords."""
  tech_stack = [
      "React",
      "TypeScript",
      "Python",
      "FastAPI",
      "Node.js",
      "GraphQL",
      "Next.js",
      "PostgreSQL",
      "Redis",
      "AWS",
  ]
  found = [
      tech
      for tech in tech_stack
      if re.search(r"\b" + re.escape(tech) + r"\b", content, re.I)
  ]
  return ", ".join(found) if found else "Full Stack / Frontend Architecture"


def calculate_job_quality_score(
    title: str,
    content: str,
    salary_text: str,
    salary_status: str,
) -> int:
  """
  Calculate comprehensive job quality score (0-100).
  
  Factors:
  - Tech stack match (35%): React, TypeScript, Next.js, GraphQL, etc.
  - Level match (30%): Staff/Principal presence
  - Salary fit (20%): Verified salary above target
  - Role focus (15%): Fullstack/Frontend emphasis
  """
  score = 0
  
  # 1. Tech Stack Match (35 points max)
  premium_techs = ["React", "TypeScript", "Next.js", "GraphQL", "FastAPI"]
  good_techs = ["Node.js", "Python", "PostgreSQL", "Redis", "Vue.js"]
  content_lower = content.lower()
  title_lower = title.lower()
  combined_text = f"{title_lower} {content_lower[:2000]}"
  
  premium_matches = sum(
      1 for tech in premium_techs
      if re.search(r"\b" + tech.lower() + r"\b", combined_text)
  )
  good_matches = sum(
      1 for tech in good_techs
      if re.search(r"\b" + tech.lower() + r"\b", combined_text)
  )
  
  tech_score = min(35, (premium_matches * 7) + (good_matches * 3))
  score += tech_score
  
  # 2. Level Match (30 points max)
  if any(level in title_lower for level in ["staff", "principal", "lead"]):
    score += 30
  
  # 3. Salary Fit (20 points max)
  if salary_status == "VERIFIED":
    score += 20
  elif salary_status == "UNLISTED":
    score += 5
  
  # 4. Role Focus (15 points max)
  role_emphases = ["fullstack", "full stack", "frontend", "front end"]
  if any(role in title_lower for role in role_emphases):
    score += 15
  elif "react" in title_lower or "typescript" in title_lower:
    score += 12
  
  return min(100, score)


# =============================================================================
# UTILITIES & DISPATCHER
# =============================================================================
def get_formatted_timestamp(tz_name: str = "America/Toronto") -> str:
  """Outputs timestamp format: 'Tue Sep 22nd, 2026 @ 11:41 AM EDT'"""
  now = datetime.now(zoneinfo.ZoneInfo(tz_name))

  day = now.day
  if 11 <= day <= 13:
    suffix = "th"
  else:
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")

  time_str = now.strftime("%I:%M %p").lstrip("0")

  return (
      f"{now.strftime('%a %b')} {day}{suffix},"
      f" {now.year} @ {time_str} {now.strftime('%Z')}"
  )


def send_discord_alerts(matches: list[dict]):
  """Dispatches enriched embeds to Discord webhook."""
  if not DISCORD_WEBHOOK_URL or not matches:
    return

  run_time_str = get_formatted_timestamp("America/Toronto")

  for m in matches:
    if m["salary_status"] == "VERIFIED":
      salary_badge = f"🟢 **{m['salary_text']}** (Verified)"
      color = 0x2ECC71
    elif m["salary_status"] == "UNLISTED":
      salary_badge = "⚠️ **Unlisted** (Check description)"
      color = 0xF1C40F
    else:
      salary_badge = f"🔴 **{m['salary_text']}** (Below target)"
      color = 0xE74C3C

    # Quality score display
    score = m.get("quality_score", 0)
    if score >= 85:
      score_badge = f"⭐ {score}/100 (Excellent match)"
    elif score >= 70:
      score_badge = f"✅ {score}/100 (Strong match)"
    elif score >= 50:
      score_badge = f"🔶 {score}/100 (Moderate match)"
    else:
      score_badge = f"🔹 {score}/100 (Low match)"

    embed = {
        "title": f"{m['title']} @ {m['company']}",
        "url": m["url"],
        "color": color,
        "fields": [
            {
                "name": "📊 Quality Score",
                "value": score_badge,
                "inline": True,
            },
            {"name": "💰 Compensation", "value": salary_badge, "inline": True},
            {
                "name": "📍 Location & Work Type",
                "value": f"{m['location']} (EOR Supported)",
                "inline": True,
            },
            {
                "name": "🛠️ Key Tech Signals",
                "value": m.get("key_tech") or "Not specified",
                "inline": True,
            },
            {
                "name": "👔 Recruiter Outreach",
                "value": f"[Find Hiring Team on LinkedIn]({m['recruiter_url']})",
                "inline": False,
            },
            {
                "name": "📝 Quick Outreach Note",
                "value": f"```\n{m['outreach_note']}\n```",
                "inline": False,
            },
        ],
        "footer": {
            "text": (
                f"Source: {m['id'].split('_')[0].upper()} ATS • Found"
                f" {run_time_str}"
            )
        },
    }

    try:
      requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]}, timeout=20)
    except Exception as e:
      print(f"Failed to post alert for {m['id']}: {e}")


def send_summary_alert(matches_count: int, run_time_str: str):
  """Send a silent summary card (no @mention) with tracker status."""
  if not DISCORD_WEBHOOK_URL:
    return

  # Get application status
  apps = load_applications()
  stage_counts = {"applied": 0, "interviewing": 0, "rejected": 0, "offer": 0}
  for app in apps:
    if app["current_stage"] in stage_counts:
      stage_counts[app["current_stage"]] += 1

  # Determine color based on results
  if matches_count > 0:
    color = 0x3498DB  # Blue for results
    summary_title = f"📊 Job Tracker Summary - {matches_count} New Match{'es' if matches_count != 1 else ''}"
  else:
    color = 0x95A5A6  # Gray for no results
    summary_title = "📊 Job Tracker Summary - No New Matches"

  embed = {
      "title": summary_title,
      "color": color,
      "fields": [
          {
              "name": "🆕 Jobs Found This Run",
              "value": f"{matches_count}",
              "inline": True,
          },
          {
              "name": "📋 Application Pipeline",
              "value": (
                  f"🔂 Applied: {stage_counts['applied']}\n"
                  f"🗣️ Interviewing: {stage_counts['interviewing']}\n"
                  f"❌ Rejected: {stage_counts['rejected']}\n"
                  f"🎉 Offers: {stage_counts['offer']}"
              ),
              "inline": True,
          },
          {
              "name": "📈 Total Applications Tracked",
              "value": f"{len(apps)}",
              "inline": True,
          },
      ],
      "footer": {
          "text": f"Last run: {run_time_str}"
      },
  }

  try:
    # Post as silent message (no @mention, no ping)
    payload = {
        "embeds": [embed],
        "allowed_mentions": {"parse": []},  # No mentions at all
    }
    requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=20)
  except Exception as e:
    print(f"Failed to post summary alert: {e}")


def process_job_posting(
    job_id: str,
    company: str,
    title: str,
    location: str,
    workplace_type: str,
    content: str,
    url: str,
    comp_data: dict = None,
) -> dict | None:
  """Central evaluation pipeline for every detected role."""
  if not is_target_role(title, content):
    return None

  if not is_fully_remote(location, workplace_type, content):
    return None

  if not is_eor_supported(location, content):
    return None

  meets_target, salary_text, salary_status = parse_salary_info(
      content, comp_data
  )

  if salary_status == "BELOW_THRESHOLD":
    return None

  key_tech = extract_key_signals(content)
  quality_score = calculate_job_quality_score(title, content, salary_text, salary_status)
  recruiter_url = f"https://www.linkedin.com/search/results/people/?keywords={company}%20recruiter"
  outreach_note = f"Hi [Name], saw the {title} opening at {company} and wanted to connect regarding frontend/fullstack architectural impact."

  return {
      "id": job_id,
      "company": company,
      "title": title,
      "url": url,
      "location": location or "Remote",
      "salary_text": salary_text,
      "salary_status": salary_status,
      "key_tech": key_tech,
      "quality_score": quality_score,
      "recruiter_url": recruiter_url,
      "outreach_note": outreach_note,
  }


# =============================================================================
# ATS POLLING ENGINES
# =============================================================================
def check_ashby(seen_jobs: set) -> list[dict]:
  matches = []
  for board in ASHBY_BOARDS:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true"
    try:
      resp = requests.get(url, timeout=20)
      if resp.status_code != 200:
        continue
      data = resp.json()
      for job in data.get("jobs", []):
        raw_id = job.get("id") or job.get("jobUrl")
        job_id = f"ashby_{board}_{raw_id}"
        if job_id in seen_jobs:
          continue

        content = job.get("descriptionPlain") or job.get("descriptionHtml") or ""
        if not is_target_role(job.get("title", ""), content):
          continue

        match = process_job_posting(
            job_id=job_id,
            company=board.capitalize(),
            title=job.get("title", ""),
            location=job.get("location", ""),
            workplace_type=job.get("workplaceType", ""),
            content=content,
            url=job.get("jobUrl") or job.get("applyUrl"),
            comp_data=job.get("compensation"),
        )
        if match:
          matches.append(match)
    except Exception as e:
      print(f"Error fetching Ashby board {board}: {e}")
  return matches


def check_greenhouse(seen_jobs: set) -> list[dict]:
  matches = []
  for board in GREENHOUSE_BOARDS:
    url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
    try:
      resp = requests.get(url, timeout=20)
      if resp.status_code != 200:
        continue
      data = resp.json()
      for job in data.get("jobs", []):
        raw_id = job.get("id")
        job_id = f"greenhouse_{board}_{raw_id}"
        if job_id in seen_jobs:
          continue

        location_obj = job.get("location", {})
        loc_name = (
            location_obj.get("name", "")
            if isinstance(location_obj, dict)
            else str(location_obj)
        )
        content = job.get("content", "")
        if not is_target_role(job.get("title", ""), content):
          continue

        match = process_job_posting(
            job_id=job_id,
            company=board.capitalize(),
            title=job.get("title", ""),
            location=loc_name,
            workplace_type="remote" if "remote" in loc_name.lower() else "",
            content=content,
            url=job.get("absolute_url"),
        )
        if match:
          matches.append(match)
    except Exception as e:
      print(f"Error fetching Greenhouse board {board}: {e}")
  return matches


def check_lever(seen_jobs: set) -> list[dict]:
  matches = []
  for board in LEVER_BOARDS:
    url = f"https://api.lever.co/v0/postings/{board}?mode=json"
    try:
      resp = requests.get(url, timeout=20)
      if resp.status_code != 200:
        continue
      jobs = resp.json()
      for job in jobs:
        raw_id = job.get("id")
        job_id = f"lever_{board}_{raw_id}"
        if job_id in seen_jobs:
          continue

        categories = job.get("categories", {})
        location = categories.get("location", "")
        workplace_type = job.get("workplaceType", "")
        content = job.get("descriptionPlain") or job.get("description") or ""
        if not is_target_role(job.get("text", ""), content):
          continue

        match = process_job_posting(
            job_id=job_id,
            company=board.capitalize(),
            title=job.get("text", ""),
            location=location,
            workplace_type=workplace_type,
            content=content,
            url=job.get("hostedUrl"),
        )
        if match:
          matches.append(match)
    except Exception as e:
      print(f"Error fetching Lever board {board}: {e}")
  return matches


# =============================================================================
# MAIN EXECUTION
# =============================================================================
if __name__ == "__main__":
    init_db()  # Initialize database on startup
    seen_jobs = load_seen_jobs()
    
    run_time_str = get_formatted_timestamp("America/Toronto")

    all_matches = []
    all_matches.extend(check_ashby(seen_jobs))
    all_matches.extend(check_greenhouse(seen_jobs))
    all_matches.extend(check_lever(seen_jobs))

    if all_matches:
        print(f"Found {len(all_matches)} new matching roles. Dispatching alerts...")
        send_discord_alerts(all_matches)
        for m in all_matches:
            seen_jobs.add(m["id"])
            # Save to application tracking database
            save_application(
                job_id=m["id"],
                company=m["company"],
                role_title=m["title"],
                job_url=m["url"],
                quality_score=m.get("quality_score", 0)
            )
        save_seen_jobs(seen_jobs)
    else:
        print("Execution complete. No new matching roles found.")
    
    # Always send summary (regardless of results) for visibility
    send_summary_alert(len(all_matches), run_time_str)


