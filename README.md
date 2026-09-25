# Remote Tech Job Tracker 🚀

Automated pipeline that tracks **senior-level roles** across multiple ATS
platforms (Greenhouse, Lever, Ashby) and two aggregators, scores them against a
profile you define, and cards the matches to Discord.

## Overview

A **GitHub Actions cron job** runs four times daily (03:00, 09:00, 15:00 and
21:00 UTC) and:

1. **Polls public ATS APIs and aggregators** for job postings
2. **Filters** by role title, work mode, region and salary floor — all driven
   by a YAML profile, not hardcoded constants
3. **Scores** each match 0–100 on signals, seniority, compensation and role fit
4. **Cards the matches to Discord**
5. **Runs for free** on GitHub's hosted runners

The only paid dependency is a Postgres database (Neon's free tier is enough).

### Where jobs come from

| Source         | Needs company slugs? | Notes                                          |
| -------------- | -------------------- | ---------------------------------------------- |
| **Greenhouse** | yes                  | `?content=true`; descriptions are escaped HTML |
| **Lever**      | yes                  | Public JSON API                                |
| **Ashby**      | yes                  | Public JSON API, often has structured salary   |
| **Remote OK**  | no                   | Aggregator; attribution required               |
| **Himalayas**  | no                   | Aggregator, paginated; attribution required    |

Curated ATS boards give the highest signal but need slugs, which each profile
lists under `boards`. The aggregators need none and are the only option for a
profile with no target companies. Both require visible attribution as a
condition of free API access — the alert footer applies it automatically, so
don't remove it.

The board lists live in the profiles, not in code: see the `boards` block in
[profiles/engineering.yml](profiles/engineering.yml).

## Quick Start

### Step 1: Clone & Setup Local Environment

```bash
cd peckham-rye

python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

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

## Search Profiles

A **profile** is a YAML file describing who the search is for: which job titles
count, the salary floor per currency, acceptable work modes and regions, which
sources to poll, and which Discord webhook to alert. Two ship with the repo:

| Profile                      | For                          | Sources                        |
| ---------------------------- | ---------------------------- | ------------------------------ |
| `profiles/engineering.yml`   | Frontend/fullstack engineers | Curated Ashby/Greenhouse/Lever |
| `profiles/product-owner.yml` | Product owners/managers      | Remote OK + Himalayas          |

Omitting `--profile` uses the built-in defaults, which are identical to
`profiles/engineering.yml`.

```bash
python track_jobs.py --profile profiles/product-owner.yml
python dashboard.py --profile profiles/product-owner.yml
python update_application.py --profile profiles/product-owner.yml list
```

**Writing your own:** copy `profiles/engineering.yml` — it is a fully annotated
dump of every available field. A profile only needs to declare what differs
from the defaults; everything else is inherited. `profiles/product-owner.yml`
shows that minimal style.

**Per-profile webhooks:** a profile named `product-owner` looks for
`DISCORD_WEBHOOK_PRODUCT_OWNER`, then falls back to `DISCORD_WEBHOOK_URL`. A
profile can also name its own variable via the `webhook_env` field. This is how
each persona gets its own Discord channel.

**Sources:** curated ATS boards (`ashby`, `greenhouse`, `lever`) give the
highest signal but need company slugs. The aggregators (`remoteok`,
`himalayas`) need no slugs and are the only option for a profile with no target
companies — but they skew US/EU remote, so region-specific searches will see
thin results until board slugs are added. Both aggregators require attribution,
which the alert footer applies automatically.

### Database

The tracker owns three tables — `seen_jobs`, `applications` and
`applications_history` — and expects its own database. Give it a dedicated
role rather than reusing an existing one: in Postgres a separate _database_ is
not a security boundary, since any role with `CONNECT` can reach the others in
the same project.

A suitable setup, run once as the owning role:

```sql
-- Create via SQL, not the provider's console: managed providers often grant
-- console-created roles a superuser-like role that defeats the purpose.
CREATE ROLE job_tracker WITH LOGIN PASSWORD '<password>';
GRANT CONNECT ON DATABASE "job-tracker" TO job_tracker;
GRANT USAGE ON SCHEMA public TO job_tracker;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO job_tracker;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO job_tracker;

-- Close the implicit cross-database path on any other database in the project.
REVOKE ALL ON DATABASE <other_database> FROM PUBLIC;
```

These grants cover normal operation but not `ALTER TABLE`, which only a table's
owner may run — so use the owning role's connection string when running
`migrate_db.py`, then switch back.

Profiles are isolated by a `profile` column on each table. A fresh database
needs no migration — `init_db()` creates the current schema on first run. If
you ran an earlier single-profile version, upgrade the schema once before
running again:

```bash
python migrate_db.py --dry-run   # show what would change
python migrate_db.py             # apply
```

Existing rows are attributed to `engineering` by default
(`--backfill-profile` to change). The script is idempotent and safe to re-run.

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

Also add `DATABASE_URL` for the Neon connection string.

The scheduled workflow runs every profile in a matrix, one job each. To give a
profile its own channel, add a secret named after it —
`DISCORD_WEBHOOK_ENGINEERING` or `DISCORD_WEBHOOK_PRODUCT_OWNER`. Profiles
without one fall back to `DISCORD_WEBHOOK_URL`.

| Name                        | Kind   | Required | Purpose                    |
| --------------------------- | ------ | -------- | -------------------------- |
| `DISCORD_WEBHOOK_URL`       | secret | yes      | Fallback alert channel     |
| `DATABASE_URL`              | secret | yes      | Postgres connection string |
| `DISCORD_WEBHOOK_<PROFILE>` | secret | no       | Per-profile channel        |

### Step 6: Verify Workflow

1. **Go to repo** → Actions tab
2. **Select** "Daily Remote Job Tracker" from the left sidebar
3. **Click** "Run workflow" → "Run workflow" button
4. **Monitor** the execution (should complete in ~30 seconds)
5. **Check** your Discord channel for results

**Success indicator:** You'll see an embedded message with matching jobs in Discord!

## Customization

Everything below is a profile field. Edit the YAML — no code changes needed.
[profiles/engineering.yml](profiles/engineering.yml) is an annotated dump of
every available field.

### Add / Remove Companies

```yaml
boards:
  greenhouse:
    - stripe
    - cloudflare
  lever:
    - postman
  ashby:
    - linear
```

The slug is the last path segment of a company's job board URL.

### Adjust Filtering

```yaml
primary_role_keywords: [full stack, frontend] # scores 15
secondary_role_keywords: [react, typescript] # scores 12
exclude_title_exact: [platform engineer] # checked first, always wins
generic_title_fallbacks: [software engineer] # needs a description signal
require_in_description: [react, typescript]

min_salary: { USD: 145000, CAD: 200000, EUR: 130000 }
work_modes: [remote] # remote | hybrid | onsite | unknown
regions: [] # empty means anywhere
alert_threshold: 0 # counted but not carded below this score
```

Exclusions are phrase-level and matched on word boundaries, so `platform
engineer` won't kill `Frontend Engineer, Platform Team`.

### Quality Scoring

Each match scores 0–100 across four buckets:

| Bucket       | Max | Driven by                                                |
| ------------ | --- | -------------------------------------------------------- |
| Signal match | 35  | `premium_signals` (7 each), `good_signals` (3 each)      |
| Level match  | 30  | `high_level_keywords` in the title                       |
| Salary fit   | 20  | verified against `min_salary`; unlisted or hourly = 5    |
| Role focus   | 15  | `primary_role_keywords` 15, `secondary_role_keywords` 12 |

A title accepted only via `generic_title_fallbacks` scores 0 for role focus,
so those cap around 70 even when everything else matches.

### Change Execution Schedule

Edit [.github/workflows/daily_tracker.yml](.github/workflows/daily_tracker.yml):

```yaml
schedule:
  - cron: "0 3,9,15,21 * * *" # UTC
```

**Common cron patterns:**

- `'0 9 * * *'` → Daily at 9 AM UTC
- `'0 */6 * * *'` → Every 6 hours
- `'0 8,14,20 * * *'` → 3 times daily (8 AM, 2 PM, 8 PM UTC)

## Supported Sources

| Platform       | Status      | API Type                         |
| -------------- | ----------- | -------------------------------- |
| **Greenhouse** | ✅ Active   | Public JSON API                  |
| **Lever**      | ✅ Active   | Public JSON API                  |
| **Ashby**      | ✅ Active   | Public JSON API                  |
| **Remote OK**  | ✅ Active   | Aggregator, attribution required |
| **Himalayas**  | ✅ Active   | Aggregator, attribution required |
| **Remotive**   | ❌ Rejected | Stale postings in live testing   |
| **LinkedIn**   | 🚧 Planned  | Scraping (rate-limited)          |

## Expanding to New Platforms

Fetchers are responsible for **normalization**, so ATS-specific field names
never leak into filtering or scoring. Every fetcher emits this shape:

```python
{
    "id": "greenhouse_pinterest_7301594",  # must be globally unique
    "source": "greenhouse",
    "company": "Pinterest",
    "title": "Staff Software Engineer",
    "location": "Remote, CA, US",
    "workplace_type": "remote",
    "content": "...",       # plain text, not HTML
    "url": "https://...",
    "comp_data": None,      # structured salary, when the ATS provides it
}
```

To add a platform:

1. Write `_normalize_<platform>(job, board) -> dict` returning that shape.
   Run HTML descriptions through `html_to_text()` — leaving markup in place
   breaks word-boundary signal matching and hides the salary block.
2. Write `check_<platform>(seen_jobs, profile)` and register it in
   `SOURCE_FETCHERS`.
3. Add the source name to a profile's `sources` list.
4. Add tests in [test_track_jobs.py](test_track_jobs.py) and run the suite.

`process_job_posting` handles filtering, scoring and alerting from there.

## Tests

```bash
python -m pytest test_track_jobs.py -q
```

109 tests covering scoring, role filtering, salary parsing, HTML flattening,
profile loading, work-mode and region logic, embeds and action-link signing.
No network or database access, so they run in well under a second.

## Directory Structure

```
peckham-rye/
├── .github/
│   └── workflows/
│       ├── daily_tracker.yml     # Scheduled tracker run (per-profile matrix)
│       └── tests.yml             # CI test run
├── profiles/
│   ├── engineering.yml           # Annotated reference profile
│   └── product-owner.yml         # Minimal profile, declares only diffs
├── track_jobs.py                 # Fetching, filtering, scoring, alerting, DB
├── tracker_service.py            # Action-link service (deployed separately)
├── dashboard.py                  # Pipeline and quality reporting
├── update_application.py         # Stage updates from the CLI
├── migrate_db.py                 # Idempotent schema migrations
├── test_track_jobs.py            # Test suite
├── requirements.txt              # Tracker dependencies
├── requirements-service.txt      # Adds FastAPI/uvicorn for the service
└── README.md                     # This file
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
- Himalayas is paginated; `aggregator_max_pages` bounds how deep each run goes

### Action link returns 400

- `TRACKER_SIGNING_KEY` differs between GitHub Actions and the service. A
  trailing newline from pasting is the usual cause.
- Verify both sides agree:
  ```bash
  python3 -c "import hmac,hashlib,os;print(hmac.new(os.environ['TRACKER_SIGNING_KEY'].encode(),b'test',hashlib.sha256).hexdigest()[:16])"
  ```
  Run it in both environments — the 16 characters must match.
- Links older than 14 days have expired; update the stage from the CLI.

### Discord cards show no "Mark as Applied" button

- `TRACKER_SIGNING_KEY` or `TRACKER_BASE_URL` is unset. The button is omitted
  rather than pointing at a service that may not exist.

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

- [x] Database caching to track new vs. existing jobs
- [x] Deduplication across runs to reduce duplicate notifications
- [x] Salary range extraction
- [x] Metrics dashboard (quality distribution, pipeline stages)
- [x] Multi-profile support
- [x] One-click application tracking from Discord
- [ ] Compare the midpoint or top of a salary range against the floor, not
      just the low end — a $138k–$305k staff role is currently dropped
- [ ] Score role focus for titles accepted via `generic_title_fallbacks`
- [ ] Support for LinkedIn Recruiter / direct company APIs
- [ ] Email fallback if Discord is unavailable

## License

MIT

## Contributing

Found an ATS platform we're missing? Want to improve filtering? Submit an issue or PR!

---

**Happy job hunting!** 🎯
