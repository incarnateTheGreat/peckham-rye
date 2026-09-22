# Platform Expansion Guide

This document explains how to add support for new job board platforms (Ashby, LinkedIn, direct company APIs, etc.)

## Architecture Overview

The main script (`track_jobs.py`) follows a modular pattern:

1. **Scraper Functions** - Fetch jobs from each platform
   - `check_greenhouse()` → Greenhouse.io
   - `check_lever()` → Lever.co
   - `check_ashby()` → Ashby.com

2. **Shared Filtering** - Applied to all results
   - `TITLE_LEVEL_KEYWORDS` (senior, staff, principal, lead)
   - `TITLE_ROLE_KEYWORDS` (backend, frontend, golang, react, etc.)
   - `LOCATION_KEYWORDS` (remote, spain, emea, europe)

3. **Orchestration** - Combines results
   - `main()` calls all scrapers
   - `deduplicate_jobs()` removes duplicates
   - `send_discord_alert()` notifies

---

## Adding a New Platform: Step-by-Step

Let's add **LinkedIn Jobs API** as an example.

### 1. Research the API

```
Platform: LinkedIn
API Endpoint: https://www.linkedin.com/jobs/search/
Auth: None (public jobs), or API token (if rate limited)
Response Format: JSON
Rate Limit: ~100 reqs/min
Response Fields: title, location, company, url, description
```

### 2. Create Scraper Function

Add this to `track_jobs.py`:

```python
def check_linkedin() -> List[Dict[str, str]]:
    """Fetch jobs from LinkedIn Jobs API."""
    matches = []

    # LinkedIn doesn't have a direct public API, but we can use unofficial endpoints
    # or integrate with their partnership program

    linkedin_keywords = [
        "remote+senior+engineer+spain",
        "remote+staff+backend+europe",
        "remote+principal+frontend+emea",
    ]

    for keyword_combo in linkedin_keywords:
        url = f"https://api.linkedin.com/v2/jobs?keywords={keyword_combo}"
        headers = {
            "Authorization": f"Bearer {os.environ.get('LINKEDIN_API_TOKEN', '')}",
        }

        try:
            logger.info(f"Fetching LinkedIn jobs for: {keyword_combo}")
            res = requests.get(url, headers=headers, timeout=10)
            res.raise_for_status()

            jobs = res.json().get("elements", [])
            logger.info(f"Found {len(jobs)} total jobs for query: {keyword_combo}")

            for job in jobs:
                title = job.get("title", "").lower()
                location = job.get("location", {}).get("name", "").lower()
                company = job.get("company", {}).get("name", "")

                # Skip if excluded keywords present
                if any(k in title for k in TITLE_EXCLUDE_KEYWORDS):
                    continue

                # Check all three criteria
                is_senior = any(k in title for k in TITLE_LEVEL_KEYWORDS)
                is_role = any(k in title for k in TITLE_ROLE_KEYWORDS)
                is_location = any(k in location for k in LOCATION_KEYWORDS)

                if is_senior and is_role and is_location:
                    matches.append({
                        "company": company,
                        "title": job.get("title"),
                        "url": job.get("jobUrl"),
                        "location": location,
                        "source": "LinkedIn",
                        "id": f"linkedin_{job.get('id')}",
                    })
                    logger.info(f"  ✓ Matched: {job.get('title')} at {company}")

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching LinkedIn jobs for '{keyword_combo}': {e}")
        except Exception as e:
            logger.error(f"Unexpected error processing LinkedIn: {e}")

    return matches
```

### 3. Register in Orchestration

In the `main()` function, add:

```python
def main():
    """Orchestrate job tracking across all platforms."""
    logger.info("=" * 70)
    logger.info("Starting Remote Tech Job Tracker")
    logger.info("=" * 70)

    all_jobs = []

    # Existing platforms
    logger.info("\n[1/5] Checking Greenhouse boards...")
    all_jobs.extend(check_greenhouse())

    logger.info("\n[2/5] Checking Lever boards...")
    all_jobs.extend(check_lever())

    logger.info("\n[3/5] Checking Ashby companies...")
    all_jobs.extend(check_ashby())

    # NEW: LinkedIn
    logger.info("\n[4/5] Checking LinkedIn...")
    all_jobs.extend(check_linkedin())

    # Rest of function remains the same
    logger.info("\n[5/5] Deduplicating results...")
    unique_jobs = deduplicate_jobs(all_jobs)
    ...
```

### 4. Add Environment Variable (if needed)

If the new platform requires authentication, add to `.github/workflows/daily_tracker.yml`:

```yaml
steps:
  - name: Execute Tracker Script
    env:
      DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
      LINKEDIN_API_TOKEN: ${{ secrets.LINKEDIN_API_TOKEN }} # NEW
    run: python track_jobs.py
```

Then add the secret to GitHub:

- GitHub repo → Settings → Secrets → New secret
- Name: `LINKEDIN_API_TOKEN`
- Value: Your LinkedIn API token

### 5. Test Locally

```bash
# Set environment variables
export LINKEDIN_API_TOKEN="your_token"
export DISCORD_WEBHOOK_URL="your_webhook"

# Test the script
python3 track_jobs.py
```

### 6. Commit and Push

```bash
git add track_jobs.py .github/workflows/daily_tracker.yml
git commit -m "Add LinkedIn job board support"
git push
```

---

## Template: Scraper Function

Use this template when adding new platforms:

```python
def check_[platform_name]() -> List[Dict[str, str]]:
    """Fetch jobs from [Platform Name]."""
    matches = []

    companies_or_queries = [
        "company1",
        "company2",
    ]

    for company in companies_or_queries:
        url = f"https://api.[platform].com/jobs?q={company}"
        try:
            logger.info(f"Fetching [Platform] jobs for: {company}")
            res = requests.get(url, timeout=10)
            res.raise_for_status()

            jobs = res.json().get("jobs", [])  # Adjust based on API response
            logger.info(f"Found {len(jobs)} total jobs for {company}")

            for job in jobs:
                title = job.get("title", "").lower()
                location = job.get("location", "").lower()  # Adjust key

                # Skip excluded keywords
                if any(k in title for k in TITLE_EXCLUDE_KEYWORDS):
                    continue

                # Filter by criteria
                is_senior = any(k in title for k in TITLE_LEVEL_KEYWORDS)
                is_role = any(k in title for k in TITLE_ROLE_KEYWORDS)
                is_location = any(k in location for k in LOCATION_KEYWORDS)

                if is_senior and is_role and is_location:
                    matches.append({
                        "company": company.capitalize(),
                        "title": job.get("title"),
                        "url": job.get("url"),  # Adjust key
                        "location": location,
                        "source": "[Platform Name]",  # e.g., "LinkedIn", "Indeed"
                        "id": f"[platform]_{company}_{job.get('id')}",
                    })
                    logger.info(f"  ✓ Matched: {job.get('title')} at {company}")

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching [Platform] for '{company}': {e}")
        except Exception as e:
            logger.error(f"Unexpected error processing [Platform]: {e}")

    return matches
```

---

## Platform Integration Options

### 1. **Ashby** (Already Implemented) ✅

- **API**: Public JSON API
- **Auth**: None
- **Endpoint**: `https://api.ashby.com/posting-api/job-postings?organizationHandle={company}`
- **Rate Limit**: Generous
- **Companies**: Ramp, Rippling, Gemini, etc.

### 2. **LinkedIn** (Recommended Next)

- **API**: Partnership program (requires approval)
- **Auth**: API token
- **Endpoint**: `https://api.linkedin.com/v2/jobs`
- **Rate Limit**: Depends on plan
- **Notes**: Public jobs are also accessible via scraping, but not recommended

### 3. **Indeed** (Consider Later)

- **API**: Requires commercial license
- **Auth**: API key
- **Endpoint**: `https://secure.indeed.com/api/...`
- **Rate Limit**: Medium
- **Challenge**: Requires partnership agreement

### 4. **AngelList** (Early Stage Focus)

- **API**: Public JSON API
- **Auth**: None
- **Endpoint**: `https://api.angel.co/v1/jobs`
- **Rate Limit**: Generous
- **Companies**: Startups and scaleups
- **Good for**: Finding remote-friendly early-stage companies

### 5. **Direct Company APIs**

Some companies publish job feeds:

**Example: Stripe**

```python
# Stripe's careers API
url = "https://stripe.com/careers-api/jobs"
```

**Example: GitHub**

```python
url = "https://api.github.com/repos/github/careers/contents/jobs.json"
```

**Recommended approach:**

- Add 5-10 direct company APIs
- Each company that publishes jobs should have a dedicated scraper
- Combine with ATS platforms for comprehensive coverage

---

## Testing New Platforms

### Unit Test Template

```python
def test_check_linkedin():
    """Test LinkedIn scraper function."""
    jobs = check_linkedin()

    # Verify return type
    assert isinstance(jobs, list)

    # Verify structure of returned jobs
    if jobs:
        job = jobs[0]
        assert "company" in job
        assert "title" in job
        assert "url" in job
        assert "location" in job
        assert "source" in job
        assert "id" in job

    print(f"✓ LinkedIn scraper returned {len(jobs)} jobs")

# Run test
if __name__ == "__main__":
    test_check_linkedin()
```

Run with:

```bash
python3 track_jobs.py tests  # or just call test_check_linkedin()
```

---

## Debugging Tips

### Check API Response Format

```python
# Temporarily add debugging to see raw response
res = requests.get(url, timeout=10)
print("Response:", res.json())  # Print raw response
```

### Validate Keyword Matching

```python
# Test if your filters are working
title = "Senior Backend Engineer (Python), Remote"
is_senior = any(k in title.lower() for k in TITLE_LEVEL_KEYWORDS)
is_role = any(k in title.lower() for k in TITLE_ROLE_KEYWORDS)
print(f"Title: {title}")
print(f"  Senior: {is_senior}")
print(f"  Role: {is_role}")
```

### Monitor Rate Limits

If you get `429 Conflict` errors, add delays:

```python
import time

for company in companies:
    url = f"https://api.../{company}"
    res = requests.get(url)
    time.sleep(0.5)  # Wait 500ms between requests
```

---

## Performance Considerations

As you add more platforms, execution time may increase. Current targets:

- **Ideal**: < 30 seconds per run
- **Acceptable**: < 60 seconds per run
- **Problematic**: > 2 minutes per run

If you exceed 60 seconds:

1. Add request timeouts (already done: `timeout=10`)
2. Implement parallel requests using `concurrent.futures`
3. Cache results for 1-2 hours

Example parallel fetching:

```python
from concurrent.futures import ThreadPoolExecutor

def main():
    with ThreadPoolExecutor(max_workers=5) as executor:
        greenhouse_future = executor.submit(check_greenhouse)
        lever_future = executor.submit(check_lever)
        ashby_future = executor.submit(check_ashby)
        linkedin_future = executor.submit(check_linkedin)

        all_jobs = []
        all_jobs.extend(greenhouse_future.result())
        all_jobs.extend(lever_future.result())
        all_jobs.extend(ashby_future.result())
        all_jobs.extend(linkedin_future.result())
```

---

## Recommended Platform Priority

1. **Phase 1** (Current): Greenhouse, Lever, Ashby
2. **Phase 2** (Next): LinkedIn Jobs API (if partnership available)
3. **Phase 3**: AngelList (early-stage focus)
4. **Phase 4**: Direct company APIs (Stripe, GitHub, etc.)
5. **Phase 5**: Indeed (if commercial partnership available)

---

## Questions?

If an API doesn't have public documentation:

1. Check if there's an unofficial API (use at your own risk)
2. Look for open-source libraries (e.g., `linkedin-api`, `indeed-scraper`)
3. Consider web scraping as last resort (respect `robots.txt`)

---

Happy extending! 🚀
