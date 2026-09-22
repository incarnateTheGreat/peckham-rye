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
    "staff", "principal", "architect",  # Removed "senior" and "lead" for stricter filtering
]

TITLE_ROLE_KEYWORDS = [
    "frontend", "fullstack", "full-stack", "backend",  # Only frontend, fullstack, backend
    "react", "vue", "typescript", "typescript", "golang", "rust", "python", "java",
]

TITLE_EXCLUDE_KEYWORDS = [
    "junior", "intern", "entry", "support", "sales", "marketing", "advocacy", "student",
    "customer", "account", "solutions architect", "devops", "infrastructure", "sre",
    "systems engineer", "platform engineer", "linux kernel", "hardware", "qa",
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
    """Send matched jobs to Discord webhook, grouped by company."""
    if not DISCORD_WEBHOOK_URL:
        logger.error("DISCORD_WEBHOOK_URL environment variable is missing.")
        sys.exit(1)
    
    if not matches:
        logger.info("No matching roles found today.")
        return
    
    try:
        # Group jobs by company
        from collections import defaultdict
        jobs_by_company = defaultdict(list)
        for job in matches:
            jobs_by_company[job['company']].append(job)
        
        # Create one embed per company
        embeds = []
        for company in sorted(jobs_by_company.keys()):
            company_jobs = jobs_by_company[company]
            
            # Build job list for this company
            job_lines = []
            for job in company_jobs:
                # Truncate long titles
                title = job['title'][:75] + "..." if len(job['title']) > 75 else job['title']
                line = f"• {title}\n  🔗 {job['url']}"
                job_lines.append(line)
            
            job_list = "\n".join(job_lines)
            
            # Create embed for this company
            embed = {
                "title": f"🔷 {company} ({len(company_jobs)} open)",
                "description": job_list,
                "color": 3066993,  # Green
                "footer": {
                    "text": f"{company} | {len(company_jobs)} matching role(s)"
                }
            }
            
            embeds.append(embed)
        
        # Create header embed
        header_embed = {
            "title": f"🚨 Remote Staff/Principal Engineer Roles ({len(matches)} Total)",
            "description": f"Found {len(matches)} matching position(s) across {len(embeds)} companies\n{datetime.now().strftime('%Y-%m-%d %H:%M UTC')}",
            "color": 16711680,  # Red
        }
        
        # Send header + company embeds
        batches_of_embeds = [[header_embed] + embeds[j:j+9] for j in range(0, len(embeds), 9)]
        
        for batch_embeds in batches_of_embeds:
            payload = {
                "username": "Remote Job Tracker",
                "avatar_url": "https://cdn-icons-png.flaticon.com/512/1087/1087815.png",
                "embeds": batch_embeds
            }
            
            res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
            if res.status_code not in [200, 204]:
                logger.error(f"Failed to post to Discord: {res.status_code} - {res.text}")
                return
        
        logger.info(f"✓ Successfully posted {len(matches)} jobs across {len(embeds)} companies")
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
