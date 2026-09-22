"""
Automated Remote Tech Job Tracker
Polls public ATS endpoints for senior engineering roles in EMEA/Spain/Remote
Sends notifications via Discord Webhook
"""

import os
import sys
import logging
import requests
from typing import List, Dict, Set
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

# Target Companies by ATS Platform
GREENHOUSE_BOARDS = [
    "datadog",
    "cloudflare",
    "gitlab",
    "posthog",
    "canonical",
    "elastic",
    "grafana",
    "figma",
    "notion",
]

LEVER_BOARDS = [
    "stripe",
    "anthropic",
    "typeform",
]

# Ashby companies (format: company-slug from ashby job boards)
ASHBY_COMPANIES = [
    "ramp",
    "rippling",
    "gemini",
]

# Keywords for Filtering
TITLE_LEVEL_KEYWORDS = [
    "senior", "staff", "lead", "principal", "architect", "expert",
    "iv", "v", "vi",  # leveling systems
]

TITLE_ROLE_KEYWORDS = [
    "software", "frontend", "backend", "fullstack", "full-stack",
    "platform", "systems", "infrastructure", "devops",
    "react", "typescript", "python", "golang", "rust", "java",
    "engineer", "developer",
]

TITLE_EXCLUDE_KEYWORDS = [
    "junior", "intern", "entry", "support", "sales", "marketing",
    "student",
]

LOCATION_KEYWORDS = [
    "remote", "spain", "emea", "europe", "everywhere", "worldwide",
    "distributed", "any location", "no office required",
]

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

# ============================================================================
# GREENHOUSE SCRAPER
# ============================================================================

def check_greenhouse() -> List[Dict[str, str]]:
    """Fetch jobs from Greenhouse job boards."""
    matches = []
    
    for board in GREENHOUSE_BOARDS:
        url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
        try:
            logger.info(f"Fetching Greenhouse board: {board}")
            res = requests.get(url, timeout=10)
            res.raise_for_status()
            
            jobs = res.json().get("jobs", [])
            logger.info(f"Found {len(jobs)} total jobs on {board}")
            
            for job in jobs:
                title = job.get("title", "").lower()
                location = job.get("location", {}).get("name", "").lower()
                
                # Skip if excluded keywords present
                if any(k in title for k in TITLE_EXCLUDE_KEYWORDS):
                    continue
                
                # Check all three criteria
                is_senior = any(k in title for k in TITLE_LEVEL_KEYWORDS)
                is_role = any(k in title for k in TITLE_ROLE_KEYWORDS)
                is_location = any(k in location for k in LOCATION_KEYWORDS)
                
                if is_senior and is_role and is_location:
                    matches.append({
                        "company": board.capitalize(),
                        "title": job.get("title"),
                        "url": job.get("absolute_url"),
                        "location": job.get("location", {}).get("name", "Remote"),
                        "source": "Greenhouse",
                        "id": f"greenhouse_{board}_{job.get('id')}",
                    })
                    logger.info(f"  ✓ Matched: {job.get('title')} at {board}")
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching Greenhouse board '{board}': {e}")
        except Exception as e:
            logger.error(f"Unexpected error processing Greenhouse board '{board}': {e}")
    
    return matches

# ============================================================================
# LEVER SCRAPER
# ============================================================================

def check_lever() -> List[Dict[str, str]]:
    """Fetch jobs from Lever job boards."""
    matches = []
    
    for board in LEVER_BOARDS:
        url = f"https://api.lever.co/v0/postings/{board}?mode=json"
        try:
            logger.info(f"Fetching Lever board: {board}")
            res = requests.get(url, timeout=10)
            res.raise_for_status()
            
            jobs = res.json()
            logger.info(f"Found {len(jobs)} total jobs on {board}")
            
            for job in jobs:
                title = job.get("text", "").lower()
                categories = job.get("categories", {})
                location = (categories.get("location", "") + " " + " ".join(categories.get("allLocations", []))).lower()
                workplace_type = job.get("workplaceType", "").lower()
                
                # Combine location signals
                full_location = f"{location} {workplace_type}"
                
                # Skip if excluded keywords present
                if any(k in title for k in TITLE_EXCLUDE_KEYWORDS):
                    continue
                
                # Check all three criteria
                is_senior = any(k in title for k in TITLE_LEVEL_KEYWORDS)
                is_role = any(k in title for k in TITLE_ROLE_KEYWORDS)
                is_location = any(k in full_location for k in LOCATION_KEYWORDS)
                
                if is_senior and is_role and is_location:
                    matches.append({
                        "company": board.capitalize(),
                        "title": job.get("text"),
                        "url": job.get("hostedUrl"),
                        "location": categories.get("location", "Remote"),
                        "source": "Lever",
                        "id": f"lever_{board}_{job.get('id')}",
                    })
                    logger.info(f"  ✓ Matched: {job.get('text')} at {board}")
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching Lever board '{board}': {e}")
        except Exception as e:
            logger.error(f"Unexpected error processing Lever board '{board}': {e}")
    
    return matches

# ============================================================================
# ASHBY SCRAPER
# ============================================================================

def check_ashby() -> List[Dict[str, str]]:
    """Fetch jobs from Ashby job boards."""
    matches = []
    
    for company in ASHBY_COMPANIES:
        url = f"https://api.ashby.com/posting-api/job-postings?organizationHandle={company}"
        try:
            logger.info(f"Fetching Ashby jobs for: {company}")
            res = requests.get(url, timeout=10)
            res.raise_for_status()
            
            data = res.json()
            jobs = data.get("results", [])
            logger.info(f"Found {len(jobs)} total jobs for {company}")
            
            for job in jobs:
                title = job.get("title", "").lower()
                location = job.get("location", {}).get("name", "").lower()
                is_remote = job.get("isRemote", False)
                
                # Skip if excluded keywords present
                if any(k in title for k in TITLE_EXCLUDE_KEYWORDS):
                    continue
                
                # Check all three criteria
                is_senior = any(k in title for k in TITLE_LEVEL_KEYWORDS)
                is_role = any(k in title for k in TITLE_ROLE_KEYWORDS)
                is_location = is_remote or any(k in location for k in LOCATION_KEYWORDS)
                
                if is_senior and is_role and is_location:
                    matches.append({
                        "company": company.capitalize(),
                        "title": job.get("title"),
                        "url": job.get("jobUrl"),
                        "location": "Remote" if is_remote else location,
                        "source": "Ashby",
                        "id": f"ashby_{company}_{job.get('id')}",
                    })
                    logger.info(f"  ✓ Matched: {job.get('title')} at {company}")
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching Ashby jobs for '{company}': {e}")
        except Exception as e:
            logger.error(f"Unexpected error processing Ashby company '{company}': {e}")
    
    return matches

# ============================================================================
# DEDUPLICATION & NOTIFICATION
# ============================================================================

def deduplicate_jobs(all_jobs: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Remove duplicate jobs based on ID."""
    seen: Set[str] = set()
    unique_jobs = []
    
    for job in all_jobs:
        job_id = job.get("id", "")
        if job_id and job_id not in seen:
            seen.add(job_id)
            unique_jobs.append(job)
    
    return unique_jobs

def send_discord_alert(matches: List[Dict[str, str]]) -> None:
    """Send matched jobs to Discord webhook."""
    if not DISCORD_WEBHOOK_URL:
        logger.error("DISCORD_WEBHOOK_URL environment variable is missing.")
        sys.exit(1)
    
    if not matches:
        logger.info("No matching roles found today.")
        return
    
    try:
        # Build embeds - split jobs across multiple embeds if needed (Discord limit: 10 embeds per message)
        embeds = []
        jobs_per_embed = 5  # 5 jobs per embed to stay under Discord's 1024 char field limit
        
        for i in range(0, len(matches), jobs_per_embed):
            batch = matches[i:i + jobs_per_embed]
            
            # Build job list for this batch
            job_list = "\n".join([
                f"**[{m['company']}]** {m['title']}\n{m['location']} | {m['source']}\n{m['url']}"
                for m in batch
            ])
            
            # Ensure field value doesn't exceed 1024 chars
            if len(job_list) > 1000:
                job_list = job_list[:997] + "..."
            
            embed = {
                "title": f"🚨 Remote Senior Engineering Roles ({len(matches)} Total)" if i == 0 else f"Jobs ({i//jobs_per_embed + 1})",
                "description": f"Batch {i//jobs_per_embed + 1} of {(len(matches) + jobs_per_embed - 1)//jobs_per_embed}" if i > 0 else f"Found {len(matches)} matching job(s) as of {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}",
                "color": 3066993,  # Green
                "fields": [
                    {
                        "name": "Matching Jobs",
                        "value": job_list,
                        "inline": False
                    }
                ]
            }
            
            # Add footer only to last embed
            if i + jobs_per_embed >= len(matches):
                embed["footer"] = {
                    "text": f"Total: {len(matches)} matching roles found"
                }
            
            embeds.append(embed)
        
        # Send message with embeds
        payload = {
            "username": "Remote Job Tracker",
            "avatar_url": "https://cdn-icons-png.flaticon.com/512/1087/1087815.png",
            "embeds": embeds[:10]  # Discord limit: 10 embeds per message
        }
        
        res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        if res.status_code in [200, 204]:
            logger.info(f"✓ Successfully posted {len(matches)} jobs to Discord ({len(embeds)} embed(s))")
        else:
            logger.error(f"Failed to post to Discord: {res.status_code} - {res.text}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending Discord webhook: {e}")
    except Exception as e:
        logger.error(f"Unexpected error formatting Discord message: {e}")

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Orchestrate job tracking across all platforms."""
    logger.info("=" * 70)
    logger.info("Starting Remote Tech Job Tracker")
    logger.info("=" * 70)
    
    all_jobs = []
    
    # Fetch from all sources
    logger.info("\n[1/4] Checking Greenhouse boards...")
    all_jobs.extend(check_greenhouse())
    
    logger.info("\n[2/4] Checking Lever boards...")
    all_jobs.extend(check_lever())
    
    logger.info("\n[3/4] Checking Ashby companies...")
    all_jobs.extend(check_ashby())
    
    # Deduplicate
    logger.info("\n[4/4] Deduplicating results...")
    unique_jobs = deduplicate_jobs(all_jobs)
    logger.info(f"Total unique matches: {len(unique_jobs)} jobs")
    
    # Send notification
    logger.info("\nSending Discord notification...")
    send_discord_alert(unique_jobs)
    
    logger.info("=" * 70)
    logger.info("Job Tracker execution complete")
    logger.info("=" * 70)

if __name__ == "__main__":
    main()
