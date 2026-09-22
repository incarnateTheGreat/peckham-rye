# Remote Tech Job Tracker 🚀

Automated pipeline to track **senior-level software engineering roles** at remote-friendly tech companies across multiple ATS platforms (Greenhouse, Lever, Ashby).

## Overview

This project runs a **daily cron job** via GitHub Actions (twice daily at 9 AM and 9 PM UTC) that:

1. **Polls public ATS APIs** for job postings
2. **Filters for senior engineering roles** eligible for work in **EMEA/Spain/Remote**
3. **Notifies you via Discord Webhook** with matching opportunities
4. **Runs for free** on GitHub's hosted runners (no infrastructure cost)

### Target Companies

#### Greenhouse Boards
- Datadog, Cloudflare, GitLab, PostHog, Canonical, Elastic, Grafana, Figma, Notion

#### Lever Boards
- Stripe, Anthropic, Typeform

#### Ashby
- Ramp, Rippling, Gemini

## Quick Start

### Step 1: Clone & Setup Local Environment

```bash
# Clone the repo (or copy to your existing repo)
cd peckham-rye

# Create virtual environment (optional but recommended)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Create Discord Webhook

1. **Create or use an existing Discord server**
2. **Create a new channel** (e.g., `#job-alerts`)
3. **Go to**: Channel Settings → Integrations → Webhooks → New Webhook
4. **Name it**: "Remote Job Tracker"
5. **Copy the Webhook URL** (you'll need this)

### Step 3: Test Locally

```bash
# Set the Discord webhook URL in your shell
export DISCORD_WEBHOOK_URL="https://discordapp.com/api/webhooks/YOUR_ID/YOUR_TOKEN"

# Run the tracker script
python track_jobs.py
```

**Expected output:**
- Console logs showing fetched jobs, filtering criteria, and Discord posting result
- Discord embed in your #job-alerts channel with matching roles

### Step 4: Deploy to GitHub

```bash
# Initialize git (if not already done)
git init
git add .
git commit -m "Initial commit: Remote job tracker setup"

# Create new private repo on GitHub named 'remote-job-tracker'
# Then push:
git remote add origin https://github.com/YOUR_USERNAME/remote-job-tracker.git
git branch -M main
git push -u origin main
```

### Step 5: Configure GitHub Actions Secret

1. **Go to GitHub repo** → Settings → Secrets and variables → Actions
2. **Click** "New repository secret"
3. **Name**: `DISCORD_WEBHOOK_URL`
4. **Value**: Paste your Discord Webhook URL from Step 2
5. **Click** "Add secret"

### Step 6: Verify Workflow

1. **Go to repo** → Actions tab
2. **Select** "Daily Remote Job Tracker" from the left sidebar
3. **Click** "Run workflow" → "Run workflow" button
4. **Monitor** the execution (should complete in ~30 seconds)
5. **Check** your Discord channel for results

**Success indicator:** You'll see an embedded message with matching jobs in Discord!

## Customization

### Add / Remove Companies

Edit `track_jobs.py` and modify these constants:

```python
GREENHOUSE_BOARDS = ["datadog", "cloudflare", ...]  # Add more Greenhouse boards
LEVER_BOARDS = ["stripe", ...]                      # Add more Lever boards
ASHBY_COMPANIES = ["ramp", ...]                     # Add more Ashby companies
```

### Adjust Filtering Keywords

Customize what roles you're interested in:

```python
TITLE_LEVEL_KEYWORDS = ["senior", "staff", "principal", ...]
TITLE_ROLE_KEYWORDS = ["backend", "frontend", "golang", ...]
LOCATION_KEYWORDS = ["remote", "spain", "europe", ...]
```

### Change Execution Schedule

Edit `.github/workflows/daily_tracker.yml`:

```yaml
schedule:
  - cron: '0 9,21 * * *'  # Change these times (cron format, UTC)
```

**Common cron patterns:**
- `'0 9 * * *'` → Daily at 9 AM UTC
- `'0 */6 * * *'` → Every 6 hours
- `'0 8,14,20 * * *'` → 3 times daily (8 AM, 2 PM, 8 PM UTC)

## Supported ATS Platforms

| Platform | Status | Companies | API Type |
|----------|--------|-----------|----------|
| **Greenhouse** | ✅ Active | 9+ | Public JSON API |
| **Lever** | ✅ Active | 3+ | Public JSON API |
| **Ashby** | ✅ Active | 3+ | Public JSON API |
| **LinkedIn** | 🚧 Planned | N/A | Scraping (rate-limited) |
| **Direct APIs** | 🚧 Planned | TBD | Company-specific |

## Expanding to New Platforms

To add a new job board scraper:

1. **Create a new scraper function** following the existing pattern:
   ```python
   def check_[platform]() -> List[Dict[str, str]]:
       """Fetch jobs from [platform]."""
       matches = []
       for company in [COMPANIES]:
           url = f"https://api.[platform].com/jobs?..."
           try:
               res = requests.get(url, timeout=10)
               jobs = res.json()
               # Filter by keywords
               # Add to matches
           except Exception as e:
               logger.error(f"Error: {e}")
       return matches
   ```

2. **Add to main() orchestration**:
   ```python
   all_jobs.extend(check_[platform]())
   ```

3. **Test locally** before pushing to GitHub

## Directory Structure

```
peckham-rye/
├── .github/
│   └── workflows/
│       └── daily_tracker.yml       # GitHub Actions cron configuration
├── .gitignore
├── requirements.txt                 # Python dependencies
├── track_jobs.py                    # Main tracker script
└── README.md                        # This file
```

## Troubleshooting

### "DISCORD_WEBHOOK_URL environment variable is missing"
- ❌ You forgot to add the secret in GitHub Settings
- ✅ Solution: Go to Repo → Settings → Secrets → Add DISCORD_WEBHOOK_URL

### No jobs appear in Discord
- Check the GitHub Actions logs (Actions tab → workflow run → logs)
- Verify your keyword filters match your target roles
- Make sure at least one target company actually has open roles

### Workflow times seem wrong
- GitHub Actions cron is in **UTC timezone**
- Adjust the `cron` schedule in `.github/workflows/daily_tracker.yml`
- Test with `workflow_dispatch` (manual trigger) to verify

### API rate limiting
- Greenhouse & Lever allow generous rate limits (typically 100+ requests/min)
- Ashby is similar, but monitor logs for 429 responses
- If needed, add delays: `time.sleep(0.1)` between requests

## Monitoring & Logs

### View execution logs:
1. Go to repo → Actions tab
2. Click on workflow run
3. Click "run-tracker" job
4. View all step outputs

### Disable notifications temporarily:
- Comment out `send_discord_alert()` call in `main()`
- Or don't set `DISCORD_WEBHOOK_URL` secret (script will skip Discord)

## Future Enhancements

- [ ] Database caching to track new vs. existing jobs
- [ ] Deduplication across runs to reduce duplicate notifications
- [ ] Support for LinkedIn Recruiter / direct company APIs
- [ ] Salary range extraction
- [ ] Role-specific notifications (e.g., Rust roles only)
- [ ] Metrics dashboard (jobs tracked, sources, locations)
- [ ] Email fallback if Discord is unavailable

## License

MIT

## Contributing

Found an ATS platform we're missing? Want to improve filtering? Submit an issue or PR!

---

**Happy job hunting!** 🎯
