# Troubleshooting Guide

Solutions for common issues when running the Remote Tech Job Tracker.

---

## Issue: "DISCORD_WEBHOOK_URL environment variable is missing"

**When it occurs**: Script exits immediately with this error.

**Causes**:

- GitHub secret not configured
- Secret name is incorrect (`DISCORD_WEBHOOK_URL`)
- Secret deleted accidentally

**Solutions**:

1. **Verify secret exists in GitHub**:
   - GitHub repo → Settings → Secrets and variables → Actions
   - Look for `DISCORD_WEBHOOK_URL` in the list
2. **If missing, add it**:
   - Click "New repository secret"
   - Name: `DISCORD_WEBHOOK_URL` (exact case)
   - Value: Your Discord webhook URL
   - Click "Add secret"

3. **Local testing without Discord**:
   - Comment out `send_discord_alert()` call in `main()`
   - Or don't export `DISCORD_WEBHOOK_URL` env var
   - Script will log "No matching roles found" and exit gracefully

---

## Issue: No Jobs Found / Matches Empty

**When it occurs**: Script runs successfully but finds 0 jobs.

**Causes**:

1. Job filters are too strict
2. No companies currently have matching open roles
3. Keywords don't match available positions
4. "Exclude" keywords matching everything

**Solutions**:

1. **Make filters less strict**:

   ```python
   # Add more variations of titles/levels
   TITLE_LEVEL_KEYWORDS = [
       "senior", "staff", "lead", "principal", "architect", "expert",
       "iv", "v", "vi",  # leveling systems
       "level",  # generic level indicators
   ]

   TITLE_ROLE_KEYWORDS = [
       "software", "engineer", "developer",  # broader terms
       "platform", "systems", "devops",
   ]
   ```

2. **Check current jobs on Greenhouse manually**:
   - Go to `https://boards.greenhouse.io/datadog`
   - Look at actual job titles
   - Adjust keywords to match what's posted

3. **Disable exclude keywords temporarily**:

   ```python
   TITLE_EXCLUDE_KEYWORDS = []  # Comment out temporarily
   ```

4. **Add debug logging**:

   ```python
   # In check_greenhouse(), add after line ~120:
   if is_senior or is_role or is_location:
       print(f"DEBUG: {title} - senior:{is_senior} role:{is_role} location:{is_location}")
   ```

5. **Re-commit with less strict filters**:
   ```bash
   git add track_jobs.py
   git commit -m "Loosen job filters to increase matches"
   git push
   ```

---

## Issue: Script Runs But Discord Gets No Message

**When it occurs**: Workflow completes successfully, but no Discord notification appears.

**Causes**:

1. Jobs matched but Discord webhook failed silently
2. Webhook URL is inactive/deleted
3. Bot doesn't have permission to post to channel
4. Network error sending to Discord

**Solutions**:

1. **Check GitHub Actions logs**:
   - GitHub repo → Actions tab
   - Click latest run
   - Click "run-tracker" job
   - Look for "Successfully posted X jobs" or error messages

2. **Test Discord webhook manually**:

   ```bash
   # Replace with your webhook URL
   curl -X POST https://discordapp.com/api/webhooks/YOUR_ID/YOUR_TOKEN \
     -H "Content-Type: application/json" \
     -d '{"content":"Test message"}'
   ```

   - Should see "Test message" in your Discord channel
   - If not, webhook is dead - recreate it in Step 1

3. **Verify bot permissions**:
   - Discord server → Settings → Roles
   - Find the webhook's role (usually same name)
   - Ensure "Send Messages" and "View Channel" are enabled

4. **Check webhook is still active**:
   - Discord channel → Settings → Integrations → Webhooks
   - Webhook should show "Created by you" or similar
   - If missing, create a new one and update GitHub secret

5. **Re-test locally with new webhook**:
   ```bash
   export DISCORD_WEBHOOK_URL="https://discordapp.com/api/webhooks/NEW_ID/NEW_TOKEN"
   python3 track_jobs.py
   ```

---

## Issue: GitHub Actions Workflow Takes Too Long (> 1 minute)

**When it occurs**: Workflow execution time creeps up to 2-3 minutes.

**Causes**:

1. API responses are slow
2. Many companies added to tracking
3. GitHub runner experiencing high load
4. Network latency

**Solutions**:

1. **Check individual API timing**:
   - Look at GitHub Actions logs
   - Each "Fetching X board" line shows timing
   - If one is notably slow, consider removing it

2. **Reduce companies being tracked**:

   ```python
   GREENHOUSE_BOARDS = [
       "datadog",
       "cloudflare",
       # Remove less critical ones
   ]
   ```

3. **Set request timeouts**:
   - Already set to 10 seconds
   - Reduce to 5 seconds if needed (trade-off: might miss slow APIs)

   ```python
   res = requests.get(url, timeout=5)  # was 10
   ```

4. **Run checks in parallel** (advanced):

   ```python
   from concurrent.futures import ThreadPoolExecutor

   with ThreadPoolExecutor(max_workers=5) as executor:
       futures = [
           executor.submit(check_greenhouse),
           executor.submit(check_lever),
       ]
       for future in futures:
           all_jobs.extend(future.result())
   ```

5. **Increase workflow timeout**:
   - Edit `.github/workflows/daily_tracker.yml`
   - Change `timeout-minutes: 10` to `timeout-minutes: 20`

---

## Issue: Workflow Fails with "No module named 'requests'"

**When it occurs**: GitHub Actions workflow shows import error.

**Causes**:

- `requirements.txt` modified or deleted
- Dependencies not installed in workflow
- Wrong Python version

**Solutions**:

1. **Verify requirements.txt exists**:

   ```bash
   cat requirements.txt
   ```

   Should show:

   ```
   requests>=2.31.0
   python-dotenv>=1.0.0
   ```

2. **Verify workflow installs dependencies**:
   - Check `.github/workflows/daily_tracker.yml`
   - Should have:

   ```yaml
   - name: Install Dependencies
     run: pip install -r requirements.txt
   ```

3. **Verify Python version** (in workflow):

   ```yaml
   - name: Set up Python
     uses: actions/setup-python@v5
     with:
       python-version: "3.11" # Should be 3.11+
   ```

4. **Test locally with fresh Python**:

   ```bash
   python3 -m venv test_venv
   source test_venv/bin/activate
   pip install -r requirements.txt
   python3 track_jobs.py
   ```

5. **If still failing, commit fix**:
   ```bash
   git add requirements.txt .github/workflows/daily_tracker.yml
   git commit -m "Fix dependencies"
   git push
   ```

---

## Issue: Duplicate Jobs Appearing in Discord

**When it occurs**: Same job posted multiple times in multiple notifications.

**Causes**:

1. Deduplication logic not working
2. Job IDs are not unique across runs
3. Multiple runs triggered accidentally

**Solutions**:

1. **Check deduplication in script**:
   - `deduplicate_jobs()` function should remove duplicates
   - Verify job IDs are unique format

2. **Inspect job IDs in logs**:

   ```python
   # Temporarily add to track_jobs.py:
   unique_jobs = deduplicate_jobs(all_jobs)
   for job in unique_jobs[:3]:
       print(f"Job ID: {job.get('id')}")
   ```

3. **If using database caching** (future feature):
   - Track job IDs across runs
   - Only notify on new jobs

4. **For now, accept duplicate notifications**:
   - They indicate jobs are still open
   - Filter manually in Discord if needed

---

## Issue: Workflow Failed: API Returned 429 (Too Many Requests)

**When it occurs**: GitHub Actions logs show rate limiting error.

**Causes**:

- Too many requests to same API
- Automated tools hammering the API
- Shared IP address hitting limits

**Solutions**:

1. **Add delays between requests**:

   ```python
   import time

   for board in GREENHOUSE_BOARDS:
       # ... make request ...
       time.sleep(0.5)  # 500ms delay between companies
   ```

2. **Implement exponential backoff**:

   ```python
   import time

   max_retries = 3
   for attempt in range(max_retries):
       try:
           res = requests.get(url, timeout=10)
           res.raise_for_status()
           break
       except requests.exceptions.HTTPError as e:
           if e.response.status_code == 429:
               wait_time = 2 ** attempt  # 1s, 2s, 4s
               logger.warning(f"Rate limited, waiting {wait_time}s...")
               time.sleep(wait_time)
           else:
               raise
   ```

3. **Reduce number of requests**:
   - Remove less important companies
   - Run less frequently (edit cron schedule)

4. **Contact API provider**:
   - Ask for rate limit increase
   - Most public APIs are generous for this use case

---

## Issue: Local Testing Works but GitHub Actions Fails

**When it occurs**: Script passes locally but fails in GitHub Actions.

**Causes**:

1. Different Python version
2. GitHub secret not set
3. Network difference (GitHub IP sometimes blocked)
4. Environment variable not exported to Action

**Solutions**:

1. **Verify Python version matches**:

   ```bash
   # Locally:
   python3 --version  # e.g., 3.11.6

   # In workflow (.github/workflows/daily_tracker.yml):
   python-version: '3.11'  # Should match
   ```

2. **Test with exact dependencies**:

   ```bash
   pip install -r requirements.txt --force-reinstall
   python3 track_jobs.py
   ```

3. **Check secret is properly passed**:
   - Verify this in workflow:

   ```yaml
   - name: Execute Tracker Script
     env:
       DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
     run: python track_jobs.py
   ```

4. **Test API connectivity from GitHub**:
   - Some company networks block GitHub's IP ranges
   - Add this to workflow temporarily:

   ```yaml
   - name: Test Connectivity
     run: |
       curl -I https://boards-api.greenhouse.io
       curl -I https://api.lever.co
   ```

5. **Enable workflow debug logging** (last resort):
   - Push commit with debugging enabled
   - GitHub Actions → re-run with debug logs enabled
   - This will show all environment details

---

## Issue: "ModuleNotFoundError: No module named 'dotenv'"

**When it occurs**: Script fails looking for python-dotenv.

**Causes**:

- `python-dotenv` not in requirements.txt
- Local venv missing the package

**Solutions**:

1. **Add to requirements.txt**:

   ```
   requests>=2.31.0
   python-dotenv>=1.0.0
   ```

2. **Reinstall locally**:

   ```bash
   source venv/bin/activate
   pip install -r requirements.txt --force-reinstall
   ```

3. **Commit and push**:
   ```bash
   git add requirements.txt
   git commit -m "Add python-dotenv dependency"
   git push
   ```

Note: The template already includes this, but check if it was accidentally removed.

---

## Issue: Discord Message Formatting Looks Wrong

**When it occurs**: Discord embed displays incorrectly (truncated, misaligned, etc.).

**Causes**:

1. Payload exceeds Discord 2000 character limit
2. Job titles contain special Discord characters
3. URLs not properly formatted

**Solutions**:

1. **Limit jobs displayed**:

   ```python
   # In send_discord_alert():
   display_matches = matches[:10]  # Show only first 10, was 15
   ```

2. **Escape special characters**:

   ```python
   title = job.get("title").replace("_", "\\_").replace("*", "\\*")
   ```

3. **Shorten long URLs**:

   ```python
   from urllib.parse import urlparse
   url_short = urlparse(job.get("url")).netloc  # Just domain
   ```

4. **Test Discord payload size**:
   ```python
   import json
   payload = {...}  # Your payload
   print(f"Payload size: {len(json.dumps(payload))} chars")
   # Should be < 2000 for embeds
   ```

---

## Issue: KeyError or Missing Fields in Job Data

**When it occurs**: Script crashes when accessing job fields.

**Causes**:

- API response structure changed
- Field name is different than expected
- Job entry is missing a required field

**Solutions**:

1. **Use .get() with defaults**:

   ```python
   # Bad:
   title = job["title"]  # Crashes if missing

   # Good:
   title = job.get("title", "No title")  # Safe fallback
   ```

2. **Inspect raw API response**:

   ```python
   # Add debugging to scraper:
   res = requests.get(url)
   print(f"Response keys: {res.json()[0].keys()}")  # See available fields
   ```

3. **Update field names if API changed**:
   - Companies sometimes change API responses
   - Check API documentation
   - Update script accordingly
   - Commit and push

4. **Add error handling**:
   ```python
   try:
       title = job.get("title", "").lower()
   except Exception as e:
       logger.warning(f"Error processing job: {e}")
       continue  # Skip this job, continue to next
   ```

---

## Issue: Workflow Never Triggers (Scheduled Cron Not Running)

**When it occurs**: Workflow doesn't run at scheduled times.

**Causes**:

1. Schedule is wrong (cron syntax error)
2. Repository is dormant (GitHub pauses workflows)
3. Default branch not set to `main`
4. Actions not enabled

**Solutions**:

1. **Verify cron syntax**:
   - `cron: '0 9,21 * * *'`
   - Format: `minute hour day month day_of_week`
   - Test at https://crontab.guru

2. **Keep repository active**:
   - Make a commit at least once every 60 days
   - Or GitHub disables workflows
   - Add dummy commit if needed:

   ```bash
   git add .
   git commit --allow-empty -m "Keep workflow active"
   git push
   ```

3. **Verify Actions are enabled**:
   - GitHub repo → Settings → Actions → General
   - "Actions permissions" should allow workflows

4. **Check default branch**:
   - Settings → General
   - "Default branch" should be `main` or where you pushed

5. **Manual test to verify**:
   - Actions tab → Select workflow
   - Click "Run workflow" button
   - If manual run fails, scheduled will too

---

## Issue: Want to Disable Workflow Temporarily

**When it occurs**: You want to stop notifications without deleting the repo.

**Solutions**:

1. **Disable via GitHub UI**:
   - Actions tab → Select "Daily Remote Job Tracker"
   - Click "..." menu → "Disable workflow"
   - To re-enable: click "Enable workflow"

2. **Delete GitHub secret** (safest):
   - Settings → Secrets → Delete `DISCORD_WEBHOOK_URL`
   - Script will gracefully exit
   - Workflow still runs but doesn't send Discord

3. **Comment out the schedule**:
   ```yaml
   # on:
   #   schedule:
   #     - cron: '0 9,21 * * *'
   ```

   - Only manual runs via "workflow_dispatch" work
   - More work to re-enable

---

## Need More Help?

1. **Check GitHub Actions logs** - most detailed info
2. **Test locally** with exact same Python version
3. **Review API documentations** if adding new platforms
4. **Search GitHub Issues** for similar problems
5. **Create an Issue** in your repository with logs

---

Happy debugging! 🐛
