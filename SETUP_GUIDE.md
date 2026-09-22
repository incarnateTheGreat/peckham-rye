# Complete Setup Guide: Remote Tech Job Tracker

This guide walks through all the steps to get the Remote Tech Job Tracker running with GitHub Actions automation.

## Prerequisites

- macOS/Linux/Windows with Python 3.11+
- GitHub account (for hosting the repo and running GitHub Actions)
- Discord server or ability to create one
- ~15 minutes of setup time

---

## STEP 1: Discord Webhook Setup

### 1a. Create or Use Existing Discord Server

If you don't have a Discord server:

1. Open Discord (https://discord.com)
2. Click the "+" icon in the left sidebar
3. Select "Create My Own" → "For me and my friends"
4. Name it (e.g., "Job Tracking")
5. Click "Create"

### 1b. Create a New Channel

1. In your server, right-click the server name → "Create Channel"
2. Channel name: `#job-alerts`
3. Channel type: Text
4. Click "Create Channel"

### 1c. Create Webhook

1. Go to `#job-alerts` channel
2. Click the settings ⚙️ icon (top right)
3. Navigate to **"Integrations"** → **"Webhooks"**
4. Click **"New Webhook"**
5. Name: `Remote Job Tracker`
6. Click **"Create Webhook"**
7. You'll see the webhook URL - **COPY IT** (looks like: `https://discordapp.com/api/webhooks/XXXXXXXX/YYYYYYYYYY`)
8. Click **"Save Changes"** or close

**Keep this URL safe** - you'll need it in Step 5!

---

## STEP 2: Local Testing (Optional but Recommended)

### 2a. Clone Repository

```bash
cd /Users/gtsacona/projects/peckham-rye
# Repository already initialized, just verify files exist:
ls -la
```

You should see:

```
.github/
  └── workflows/
      └── daily_tracker.yml
.env.example
.gitignore
README.md
requirements.txt
track_jobs.py
```

### 2b. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2c. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2d. Create Local `.env` File (for testing)

```bash
cp .env.example .env
```

Then edit `.env` and paste your Discord webhook URL:

```
DISCORD_WEBHOOK_URL=https://discordapp.com/api/webhooks/YOUR_ID/YOUR_TOKEN
```

### 2e. Run Script Locally

```bash
python3 track_jobs.py
```

**Expected output:**

- Console logs showing job fetching from Greenhouse, Lever, Ashby
- Logs showing which roles matched your filters
- Your Discord #job-alerts channel receives an embedded message with matching jobs

If you see errors, check:

- Discord webhook URL is correct
- Network connection is stable
- No typos in the .env file

---

## STEP 3: Create GitHub Repository

### 3a. Create Private Repo on GitHub

1. Go to https://github.com/new
2. Repository name: `remote-job-tracker`
3. Description: "Automated remote tech job tracking via ATS APIs"
4. **Private** (important for security - don't expose your Discord webhook URL publicly)
5. **Uncheck** "Add a README file" (we already have one)
6. Click **"Create repository"**

### 3b. Add Remote and Push

```bash
cd /Users/gtsacona/projects/peckham-rye

# Add GitHub as remote
git remote add origin https://github.com/YOUR_USERNAME/remote-job-tracker.git

# Rename branch to main (if needed)
git branch -M main

# Stage all files
git add .

# Commit
git commit -m "Initial commit: Remote job tracker setup"

# Push to GitHub
git push -u origin main
```

**Note**: If prompted for authentication, use a GitHub Personal Access Token (PAT):

1. Go to GitHub Settings → Developer settings → Personal access tokens
2. Create token with `repo` scope
3. Use token as password when prompted

### 3c. Verify on GitHub

Go to https://github.com/YOUR_USERNAME/remote-job-tracker and verify all files are there.

---

## STEP 4: Configure GitHub Actions Secret

### 4a. Navigate to Settings

1. Go to your repo on GitHub
2. Click **Settings** (top menu)
3. Left sidebar: **Secrets and variables** → **Actions**

### 4b. Create Secret

1. Click **"New repository secret"** (green button)
2. **Name**: `DISCORD_WEBHOOK_URL` (must be exact)
3. **Value**: Paste your Discord webhook URL (from Step 1c)
4. Click **"Add secret"**

**✅ Do NOT commit your webhook URL to git** - GitHub Actions secrets are encrypted and safe.

---

## STEP 5: Verify Workflow Execution

### 5a. Manual Test

1. Go to your repo on GitHub
2. Click **Actions** tab (top menu)
3. Left sidebar: Select **"Daily Remote Job Tracker"**
4. Click **"Run workflow"** dropdown
5. Click **"Run workflow"** button
6. Wait ~30 seconds for execution

### 5b. Monitor Execution

1. You'll see the workflow run appear
2. Click on the run to see logs
3. Click on **"run-tracker"** job to see detailed output

**Logs should show:**

```
✓ Virtual environment created and dependencies installed
Fetching Greenhouse board: datadog
Found XXX total jobs on datadog
✓ Matched: [job titles]
...
Successfully posted XX jobs to Discord
```

### 5c. Check Discord

Look at your `#job-alerts` channel - you should see an embedded message like:

```
🚨 Remote Senior Engineering Roles (52 Found)
Found 52 matching job(s) as of 2026-09-21 23:37 UTC

Matching Jobs:
🔗 [Datadog] — Senior Software Engineer - Distributed Systems
   📍 Remote | Source: Greenhouse
   https://...

🔗 [GitLab] — Senior Backend Engineer (Ruby), AI Engineering
   📍 Remote | Source: Greenhouse
   https://...
```

---

## STEP 6: Schedule Automatic Runs

The workflow is now **automatically scheduled** to run twice daily:

- **09:00 UTC** (5 AM US Eastern, 10 AM UK)
- **21:00 UTC** (5 PM US Eastern, 10 PM UK)

### To Modify Schedule

1. Edit `.github/workflows/daily_tracker.yml`
2. Change the `cron` line:
   ```yaml
   schedule:
     - cron: "0 9,21 * * *" # Change these times
   ```

**Cron format:** `minute hour day month day_of_week`

Common examples:

- `'0 9 * * *'` → Daily at 9 AM UTC
- `'0 8,14,20 * * *'` → 3x daily: 8 AM, 2 PM, 8 PM UTC
- `'0 */6 * * *'` → Every 6 hours
- `'0 9 * * 1-5'` → Weekdays only at 9 AM UTC

Save and commit:

```bash
git add .github/workflows/daily_tracker.yml
git commit -m "Update workflow schedule"
git push
```

---

## STEP 7: Customize Filtering (Optional)

### 7a. Add More Companies

Edit `track_jobs.py`:

```python
GREENHOUSE_BOARDS = [
    "datadog",
    "cloudflare",
    # Add more:
    "notion",
    "figma",
    "stripe",  # if Stripe moved to Greenhouse
]
```

### 7b. Adjust Keywords

```python
TITLE_LEVEL_KEYWORDS = ["senior", "staff", "principal", "lead", "architect"]
TITLE_ROLE_KEYWORDS = ["backend", "frontend", "golang", "rust", "python", "react"]
LOCATION_KEYWORDS = ["remote", "spain", "emea", "europe"]
```

### 7c. Commit and Push

```bash
git add track_jobs.py
git commit -m "Add more companies and adjust filters"
git push
```

Changes will take effect on the next scheduled run.

---

## STEP 8: Monitoring & Troubleshooting

### View Workflow Runs

1. GitHub repo → **Actions** tab
2. Select **"Daily Remote Job Tracker"**
3. Click any run to see details

### Check Logs

1. Click on workflow run
2. Click **"run-tracker"** job
3. Expand each step to see output

### Common Issues

| Issue                                  | Solution                                             |
| -------------------------------------- | ---------------------------------------------------- |
| "DISCORD_WEBHOOK_URL missing"          | Verify secret was added in GitHub Settings → Secrets |
| No jobs in Discord                     | Check filtering keywords - maybe no matches today    |
| Workflow error                         | Check GitHub Actions logs for API errors or timeouts |
| Jobs appear in console but not Discord | Verify Discord webhook URL is correct and active     |

### Disable Notifications Temporarily

If you want to pause Discord notifications but keep job tracking:

1. Edit `.github/workflows/daily_tracker.yml`
2. Comment out the secret line:
   ```yaml
   # env:
   #   DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
   ```
3. Commit and push

Or just delete the GitHub secret - script will gracefully exit.

---

## STEP 9: Advanced Features

### Database Caching (Future Enhancement)

To track new vs. existing jobs, you could:

- Store job IDs in a CSV file
- Compare each run to detect new postings only
- Send notifications only for new jobs

### Email Fallback

Instead of Discord, send filtered jobs via email:

- Use AWS SNS or SendGrid API
- Requires API token as secret
- Fallback if Discord is down

### Slack Integration

Many teams prefer Slack - Slack incoming webhooks work similarly to Discord:

```python
# Replace DISCORD_WEBHOOK_URL with SLACK_WEBHOOK_URL
# Slack attachment format is JSON-compatible
```

---

## Success Checklist

- [ ] Discord server and `#job-alerts` channel created
- [ ] Discord webhook URL copied and saved securely
- [ ] Local test completed (jobs fetched and Discord notified)
- [ ] GitHub repository created (private)
- [ ] All files pushed to GitHub
- [ ] GitHub Actions secret `DISCORD_WEBHOOK_URL` configured
- [ ] Manual workflow run completed successfully
- [ ] Discord message received with matching jobs
- [ ] Workflow schedule verified (runs twice daily)
- [ ] Repository bookmarked for future customization

---

## Next Steps

1. **Customize keyword filters** based on your exact role preferences
2. **Monitor the first week** of automated runs
3. **Add more companies** as you discover relevant ATS boards
4. **Set up a Discord role** to auto-ping yourself when matches found
5. **Consider exporting matches** to a spreadsheet for tracking applications

---

## Support

- **Check GitHub Actions logs** for detailed error messages
- **Verify Discord webhook** is still active (webhooks can be deleted)
- **Test locally** before pushing changes
- **Check ATS API status** if getting connection errors

Happy job hunting! 🎯
