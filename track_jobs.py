from __future__ import annotations

import argparse
import html
import json
import os
import re
import time
import zoneinfo
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus
import requests
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

# Load .env for local runs. Real environment variables win over the file, so
# this is inert in CI where GitHub Actions injects secrets directly. Done at
# import time so every entry point (tracker, dashboard, migration) gets it.
load_dotenv()

# =============================================================================
# SEARCH PROFILE
# =============================================================================
# Every user-specific criterion lives on SearchProfile. The defaults below
# reproduce the original hardcoded configuration, so running without a profile
# file behaves exactly as it always has. Pass --profile <file.yml> to override
# any subset of these fields for a different persona.

PROFILE_NAME_PATTERN = re.compile(r"^[a-z0-9-]+$")
VALID_WORK_MODES = ("remote", "hybrid", "onsite", "unknown")

# Compensation parsing. These are properties of how postings are written
# rather than of any one user, so they stay module-level.
CURRENCY_CODES = ("USD", "CAD", "EUR", "GBP")
CURRENCY_BY_TOKEN = {
    "€": "EUR",
    "£": "GBP",
    "USD": "USD",
    "CAD": "CAD",
    "EUR": "EUR",
    "GBP": "GBP",
    # "$" is deliberately absent: it is ambiguous between USD and CAD.
}
HOURLY_MARKERS = ("/hr", "/ hr", "/hour", "per hour", "hourly", "an hour")
HOURLY_INTERVALS = ("hourly", "hour", "per_hour")
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
HTTP_USER_AGENT = "peckham-rye-job-tracker/1.0"

# Remote OK and Himalayas both require visible attribution as a condition of
# free API access. This is rendered into every alert -- don't remove it.
SOURCE_ATTRIBUTION = {
    "remoteok": "Remote OK",
    "himalayas": "Himalayas",
}
SALARY_STATUS_POINTS = {"VERIFIED": 20, "UNLISTED": 5, "HOURLY": 5}

# Quality-score buckets and their default point allocations. A profile can
# redraw these via `score_weights`; every bucket computes a 0-100 fraction
# internally and is then scaled to its weight, so the weights are the single
# place that decides what a profile cares about.
#
# Setting a weight to 0 removes the bucket from both the score and the card.
# `location` and `tools` default to 0 so this is inert for existing profiles.
DEFAULT_SCORE_WEIGHTS = {
    "signal": 35,
    "level": 30,
    "salary": 20,
    "role": 15,
    "location": 0,
    "tools": 0,
}

# Raw scale each bucket reports on before it is scaled to its weight. Kept
# equal to the historical point values so the default weights reproduce the
# original scores exactly, including the integer rounding.
SCORE_BUCKET_RAW_MAX = {
    "signal": 35,
    "level": 30,
    "salary": 20,
    "role": 15,
    "location": 100,
    "tools": 100,
}

SCORE_BUCKET_LABELS = {
    "signal": "Signal",
    "level": "Level",
    "salary": "Salary",
    "role": "Role",
    "location": "Location",
    "tools": "Tools",
}

# Hiring reach: how reachable a posting is for a candidate outside the
# employer's home geography. Deliberately NOT a filter -- a posting can state
# a hard requirement and still flex for the right candidate, and nothing in
# the text distinguishes the two. These tiers only annotate and order cards.
#   OPEN       explicit cross-border mechanism named (EOR, vendor, anywhere)
#   NEGOTIABLE an obstacle is stated but it is an entity/payroll one
#   UNSTATED   nothing said either way -- the common case
#   BLOCKED    legally immovable (clearance, citizenship, export control)
HIRING_REACH_OPEN = "open"
HIRING_REACH_NEGOTIABLE = "negotiable"
HIRING_REACH_UNSTATED = "unstated"
HIRING_REACH_BLOCKED = "blocked"

# Card ordering: best-reachable first, legally-blocked last.
HIRING_REACH_ORDER = {
    HIRING_REACH_OPEN: 0,
    HIRING_REACH_NEGOTIABLE: 1,
    HIRING_REACH_UNSTATED: 2,
    HIRING_REACH_BLOCKED: 3,
}

# Rendered on the alert. UNSTATED shows nothing: absence of a claim must not
# be presented as a finding, the same rule the EOR field follows.
HIRING_REACH_BADGES = {
    HIRING_REACH_OPEN: "🟢 Hires across borders",
    HIRING_REACH_NEGOTIABLE: "🟡 Location stated — worth asking",
    HIRING_REACH_BLOCKED: "🔴 Legally restricted",
}


# Discord accepts at most 10 embeds per webhook message.
DISCORD_EMBEDS_PER_MESSAGE = 10

_CURRENCY_TOKEN = r"\$|€|£|USD|CAD|EUR|GBP"
# Allows an optional comma so both "145,000" and "145000" match, plus a "150k"
# shorthand. The original pattern silently missed uncommaed six-digit figures.
_AMOUNT = r"\d{2,3}(?:,?\d{3})?k?"
# Em dash included because Greenhouse's pay-transparency widget renders its
# range as "$177,185&mdash;$364,795 USD".
_RANGE_SEP = r"\s*(?:-|–|—|to)\s*"

# A currency token is required on one side or the other. Without it, ranges
# like "10-15 years experience" would parse as a salary and get the posting
# dropped for being below threshold.
SALARY_PATTERN_LEADING = re.compile(
    rf"(?P<cur>{_CURRENCY_TOKEN})\s?(?P<low>{_AMOUNT}){_RANGE_SEP}"
    rf"(?:{_CURRENCY_TOKEN})?\s?(?P<high>{_AMOUNT})",
    re.IGNORECASE,
)
SALARY_PATTERN_TRAILING = re.compile(
    rf"(?P<low>{_AMOUNT}){_RANGE_SEP}(?P<high>{_AMOUNT})"
    rf"\s*(?P<cur>{_CURRENCY_TOKEN})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SearchProfile:
  """Search criteria for a single user/persona."""

  name: str = "engineering"

  # Name of the env var holding this profile's Discord webhook URL. When unset,
  # resolution falls back to DISCORD_WEBHOOK_<NAME> then DISCORD_WEBHOOK_URL.
  # Never store the URL itself here -- profile files are committed.
  webhook_env: str | None = None
  timezone: str = "America/Toronto"

  # Target company slugs, keyed by ATS name. Every slug here was verified to
  # return HTTP 200 with a non-empty posting list -- a company only ever lives
  # on the one ATS it actually uses, so do not repeat a slug across platforms.
  boards: dict[str, list[str]] = field(
      default_factory=lambda: {
          "ashby": [
              "linear", "ramp", "vanta", "sentry",
              # Dev tools / frontend ecosystem
              "supabase", "clerk", "plane", "n8n", "notion", "zapier",
              "render", "railway", "docker", "temporal", "confluent", "neon",
              "miro", "plaid", "1password",
              # Canadian employers
              "wealthsimple", "jobber", "benevity", "thinkific", "oyster",
              # Sports & Analytics
              "teamworks", "strava", "whoop",
              # Aviation & Aerospace
              "skydio", "boom",
              # Canadian employers (second wave)
              "cohere", "koho", "neofinancial", "float", "clearco",
              "loopio", "miovision", "lightspeedhq", "hopper", "trulioo",
              "docebo", "felix", "jane",
              # Dev tools / product engineering
              "replit", "posthog", "clickup", "sanity", "fullstory",
              "helpscout", "gorgias", "dovetail", "mazedesign", "nylas",
              "substack", "patreon", "amplitude",
              # Fintech
              "moderntreasury", "column", "persona", "middesk", "headway",
          ],
          "greenhouse": [
              "stripe", "figma", "cloudflare", "datadog",
              "airbnb", "pinterest", "twitch",
              # Dev tools / frontend ecosystem
              "vercel", "gitlab", "netlify", "grafanalabs", "elastic",
              "mongodb", "planetscale", "cockroachlabs", "webflow", "twilio",
              "mozilla", "discord", "reddit",
              # Fintech / product engineering
              "robinhood", "coinbase", "affirm", "brex", "mercury", "gusto",
              "checkr", "faire", "remotecom",
              # Canadian employers
              "hootsuite", "later",
              # Sports Tech
              "hudl", "sportradar", "geniussports", "fanduel",
              "catapultsports", "zwift", "peloton",
              # Aviation/Aerospace/Flight
              "archer", "rocketlab", "relativity", "astranis", "flyzipline",
              "eve", "planetlabs", "spire",
              # Canadian employers (second wave)
              "pagerduty", "tailscale", "leagueinc", "d2l", "flipp",
              "alayacare", "shakepay", "staffbase",
              # SaaS / product engineering
              "asana", "smartsheet", "calendly", "typeform", "contentful",
              "storyblok", "algolia", "fastly", "chainguard", "jfrog",
              "circleci", "buildkite", "honeycomb", "newrelic",
              "launchdarkly", "mixpanel", "braze",
              "customerio", "klaviyo", "iterable", "intercom",
              # Fintech
              "block", "wise", "monzo", "n26", "adyen", "lithic", "alloy",
              "ledgy", "carta", "globalizationpartners",
              # Health / education / media
              "oscar", "duolingo", "khanacademy", "coursera", "bitmovin",
              # Sports Tech (second wave)
              "playonsports", "seatgeek",
          ],
          # Verified Lever boards. Generic slugs were identity-checked against
          # a sample posting first -- `porter`, `fly` and `d2l` on Lever are
          # different companies than the names suggest, so they are absent.
          "lever": [
              # Canadian employers
              "wattpad", "eqbank", "waveapps", "achievers", "getmaple",
              "pointclickcare", "telesat", "kepler",
              # Product / media
              "spotify", "lyrahealth", "ro", "angellist", "cloudinary",
              # Aviation/Aerospace
              "merlinlabs", "pyka", "elroyair",
          ],
      }
  )

  # Minimum acceptable base salary, keyed by currency code. Add or drop
  # currencies freely; unlisted currencies are treated as below threshold.
  min_salary: dict[str, int] = field(
      default_factory=lambda: {
          "USD": 145_000,
          "CAD": 200_000,  # Staff/Principal & Senior remote target for Canada
          "EUR": 130_000,
      }
  )

  # Title keywords that qualify a posting. Filtering accepts either tier;
  # scoring rewards `primary` more highly than `secondary`.
  primary_role_keywords: list[str] = field(
      default_factory=lambda: [
          "full stack",
          "fullstack",
          "frontend",
          "front end",
      ]
  )
  secondary_role_keywords: list[str] = field(
      default_factory=lambda: [
          "react",
          "typescript",
          "product engineer",
          "ui engineer",
          "web engineer",
          "application engineer",
          "vue.js",
          "next.js",
      ]
  )

  # Generic titles accepted ONLY when require_in_description also matches.
  generic_title_fallbacks: list[str] = field(
      default_factory=lambda: ["software engineer"]
  )
  require_in_description: list[str] = field(
      default_factory=lambda: [
          "react",
          "typescript",
          "frontend",
          "full stack",
          "fullstack",
          "next.js",
          "remix",
          "graphql",
      ]
  )

  # How many DISTINCT `require_in_description` terms a generic-title posting
  # must hit before it qualifies. 1 reproduces the original any() behaviour,
  # so profiles that don't set it are unaffected. Raise it when a broad
  # `generic_title_fallbacks` entry is letting adjacent roles through: a
  # recruiter or legal-counsel posting for a product team mentions "roadmap"
  # once, whereas a real product posting also names discovery or backlog.
  require_in_description_min: int = 1

  # Titles rejected outright. Checked before any include rule, so keep these
  # phrase-level ("platform engineer", not "platform") to avoid collisions.
  exclude_title_exact: list[str] = field(
      default_factory=lambda: [
          "platform engineer",
          "devops engineer",
          "site reliability engineer",
          "infrastructure engineer",
          "data engineer",
          "machine learning",
          "data science",
      ]
  )

  # Seniority markers worth a scoring bonus.
  high_level_keywords: list[str] = field(
      default_factory=lambda: ["staff", "principal", "lead"]
  )

  # Skill/domain signals used by the quality score. For a non-engineering
  # profile these become domain terms (e.g. "roadmap", "discovery").
  premium_signals: list[str] = field(
      default_factory=lambda: [
          "React",
          "TypeScript",
          "Next.js",
          "GraphQL",
          "FastAPI",
      ]
  )
  good_signals: list[str] = field(
      default_factory=lambda: [
          "Node.js",
          "Python",
          "PostgreSQL",
          "Redis",
          "Vue.js",
      ]
  )

  # Tooling worth a small nudge but never a requirement. Scored in its own
  # bucket so it cannot crowd out domain signals the way it would if it shared
  # the `good_signals` cap. Empty by default; `tools` weight is 0 unless a
  # profile asks for it.
  tool_signals: list[str] = field(default_factory=list)

  # Point allocation per scoring bucket. Missing keys fall back to
  # DEFAULT_SCORE_WEIGHTS. Weights need not sum to 100 -- the total is capped
  # at 100 either way -- but making them sum to 100 keeps the card readable.
  score_weights: dict[str, int] = field(
      default_factory=lambda: dict(DEFAULT_SCORE_WEIGHTS)
  )

  # Signals surfaced on the Discord card.
  key_signal_terms: list[str] = field(
      default_factory=lambda: [
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
  )
  key_signal_fallback: str = "Full Stack / Frontend Architecture"

  # Work-mode detection. A posting is classified as exactly one of
  # remote / hybrid / onsite / unknown, then checked against `work_modes`.
  remote_positive: list[str] = field(
      default_factory=lambda: [
          "remote",
          "work from anywhere",
          "anywhere in north america",
          "distributed",
      ]
  )
  hybrid_markers: list[str] = field(
      default_factory=lambda: ["hybrid", "hybrid remote"]
  )
  onsite_markers: list[str] = field(
      default_factory=lambda: ["on-site", "onsite", "in-office", "in office"]
  )

  # Employer of Record detection. Deliberately narrow: only explicit EOR
  # terminology and named EOR vendors. Broad terms like "canada",
  # "international" or "contractor" were removed because they match EEO
  # boilerplate and office-location lists, which made this match everything.
  # Matched on word boundaries, so "eor" cannot fire on "theory" or "reorg".
  eor_signals: list[str] = field(
      default_factory=lambda: [
          "eor",
          "employer of record",
          "global payroll",
          "globally distributed payroll",
          "deel",
          "remote.com",
          "oyster hr",
          "velocity global",
          "globalization partners",
          "papaya global",
          "safeguard global",
          "workmotion",
          "multiplier.com",
      ]
  )

  # Legally immovable barriers. A cleared/citizenship-gated role will not open
  # up for a strong candidate, so this is the only tier worth treating as a
  # genuine no. Keep it short: every entry here must be non-negotiable in fact,
  # not merely firmly worded.
  hiring_blockers: list[str] = field(
      default_factory=lambda: [
          "security clearance",
          "active clearance",
          "ts/sci",
          "itar",
          "export control",
          "us citizens only",
          "u.s. citizens only",
          "must be a us citizen",
          "must be a u.s. citizen",
          "citizenship is required",
      ]
  )

  # A stated location/payroll requirement. Counter-intuitively this is a
  # POSITIVE signal versus silence: the employer has thought about where it can
  # employ people, so there is a named obstacle to negotiate. Visa-sponsorship
  # language lives here on purpose -- it concerns relocating someone onto the
  # employer's soil, which is unrelated to employing them where they already
  # are, so it must never be treated as a blocker.
  hiring_gatekeepers: list[str] = field(
      default_factory=lambda: [
          "must reside in",
          "must live in",
          "must be located in",
          "must be based in",
          "must be physically located",
          "candidates must be located",
          "authorized to work in",
          "work authorization",
          "unable to provide sponsorship",
          "unable to sponsor",
          "do not provide sponsorship",
          "without sponsorship",
          "no visa sponsorship",
          "cannot hire outside",
          "do not have an entity",
          "legal entity",
      ]
  )

  # Accepted work modes. Empty list disables work-mode filtering entirely.
  # Include "unknown" to accept postings that state no work mode either way.
  work_modes: list[str] = field(default_factory=lambda: ["remote"])

  # Accepted geographies, matched against the location string and the opening
  # of the description. Empty list means anywhere.
  regions: list[str] = field(default_factory=list)

  # Location phrases meaning "no geographic restriction". A posting carrying
  # one of these doesn't exclude `regions`, so it is kept rather than dropped.
  region_wildcards: list[str] = field(
      default_factory=lambda: [
          "worldwide", "anywhere", "global", "international", "remote",
      ]
  )

  # Geographies that rule the candidate out. Used ONLY by the location score,
  # never as a filter, and matched against the title and location string --
  # never the description, where country names appear in EEO boilerplate and
  # office lists. Empty by default, so this is inert for existing profiles.
  region_exclusions: list[str] = field(default_factory=list)

  # Off by default: EOR support is rarely stated even when it exists, so
  # requiring it drops good postings rather than filtering bad ones. Detection
  # still runs, and a positive hit is shown on the alert.
  require_eor: bool = False

  # Which fetchers to run. Curated ATS sources need matching `boards` entries.
  sources: list[str] = field(
      default_factory=lambda: ["ashby", "greenhouse", "lever"]
  )

  # Matches scoring below this still count in the run summary but get no card
  # of their own. Raise it when a broad source makes the channel noisy.
  alert_threshold: int = 0

  # How deep to page into cursor-paginated aggregators. Each page is one HTTP
  # request, so this trades breadth against politeness.
  aggregator_max_pages: int = 10

  # Formatted with {title} and {company}.
  outreach_note_template: str = (
      "Hi [Name], saw the {title} opening at {company} and wanted to connect"
      " regarding frontend/fullstack architectural impact."
  )


DEFAULT_PROFILE = SearchProfile()


def load_profile(path: str | None = None) -> SearchProfile:
  """Build a SearchProfile from an optional YAML file layered over defaults.

  Any field omitted from the file keeps its default value, so a profile only
  needs to declare what actually differs. The profile name defaults to the
  file stem unless the file sets `name` explicitly.
  """
  if not path:
    return DEFAULT_PROFILE

  import yaml  # Imported lazily so the default path needs no extra dependency.

  raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
  if not isinstance(raw, dict):
    raise ValueError(f"Profile {path} must contain a YAML mapping")

  known = {f.name for f in fields(SearchProfile)}
  unknown = sorted(set(raw) - known)
  if unknown:
    raise ValueError(f"Unknown profile keys in {path}: {', '.join(unknown)}")

  data = {f.name: getattr(DEFAULT_PROFILE, f.name) for f in fields(SearchProfile)}
  data["name"] = Path(path).stem
  data.update(raw)

  profile = SearchProfile(**data)
  if not PROFILE_NAME_PATTERN.match(profile.name):
    raise ValueError(
        f"Profile name '{profile.name}' must match {PROFILE_NAME_PATTERN.pattern}"
    )

  bad_modes = sorted(set(profile.work_modes) - set(VALID_WORK_MODES))
  if bad_modes:
    raise ValueError(
        f"Invalid work_modes in {path}: {', '.join(bad_modes)}."
        f" Valid values: {', '.join(VALID_WORK_MODES)}"
    )

  return profile


def get_webhook_url(profile: SearchProfile) -> str | None:
  """Resolve this profile's Discord webhook from the environment.

  Resolved at call time (not import time) so a run can target whichever
  profile was selected on the command line.
  """
  if profile.webhook_env:
    return os.environ.get(profile.webhook_env)

  per_profile_key = f"DISCORD_WEBHOOK_{profile.name.upper().replace('-', '_')}"
  return os.environ.get(per_profile_key) or os.environ.get("DISCORD_WEBHOOK_URL")





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
  """Create the tables if they don't exist.

  This only ever runs CREATE TABLE IF NOT EXISTS, so it is a no-op against a
  database that already has the tables -- even if their shape is out of date.
  Use `python migrate_db.py` to bring an existing database up to this schema.
  """
  conn = get_db_connection()
  if not conn:
    return
  try:
    with conn, conn.cursor() as cursor:
      cursor.execute("""
        CREATE TABLE IF NOT EXISTS seen_jobs (
          profile TEXT NOT NULL,
          job_id TEXT NOT NULL,
          created_at TIMESTAMP DEFAULT NOW(),
          PRIMARY KEY (profile, job_id)
        )
      """)
  except Exception as e:
    print(f"Error creating table: {e}")
  finally:
    conn.close()


def load_seen_jobs(profile_name: str) -> set[str]:
  """Load the job IDs this profile has already reported on."""
  conn = get_db_connection()
  if not conn:
    return set()
  try:
    with conn, conn.cursor() as cursor:
      cursor.execute(
        "SELECT job_id FROM seen_jobs WHERE profile = %s", (profile_name,)
      )
      return {row[0] for row in cursor.fetchall()}
  except Exception as e:
    print(f"Error loading from DB: {e}")
    return set()
  finally:
    conn.close()


def save_seen_jobs(seen_jobs: set[str], profile_name: str):
  """Record job IDs as seen for this profile."""
  if not seen_jobs:
    return
  conn = get_db_connection()
  if not conn:
    return
  try:
    with conn, conn.cursor() as cursor:
      execute_values(
        cursor,
        "INSERT INTO seen_jobs (profile, job_id) VALUES %s ON CONFLICT DO NOTHING",
        [(profile_name, job_id) for job_id in seen_jobs],
      )
  except Exception as e:
    print(f"Error saving to DB: {e}")
  finally:
    conn.close()





# =============================================================================
# FILTERING HELPER FUNCTIONS
# =============================================================================
def _phrase_in(text: str, phrases: list[str]) -> bool:
  """True when any phrase occurs in `text` on word boundaries.

  Include rules used to be plain substring tests while exclusions were
  word-boundary matched. That asymmetry let the generic fallback `product`
  match "Productivity", so "Senior Enterprise Systems Engineer, AI
  Productivity" was carded as a product role. Both sides now agree.
  """
  return any(
      re.search(r"\b" + re.escape(p.lower()) + r"\b", text) for p in phrases
  )


def is_target_role(
    title: str,
    description: str = "",
    profile: SearchProfile = DEFAULT_PROFILE,
) -> bool:
  """Filters role titles against target keywords while dropping unwanted domains."""
  t = title.lower().strip()
  d = (description or "").lower()

  # Exclusions are checked first and always beat inclusions. Word-boundary
  # matched so short entries like "vp" cannot match inside another word.
  if _phrase_in(t, profile.exclude_title_exact):
    return False

  # Either keyword tier qualifies the posting; the tiers only affect scoring.
  # Automatically handles "Staff Frontend Engineer", "Product Engineer", etc.
  if _phrase_in(
      t, [*profile.primary_role_keywords, *profile.secondary_role_keywords]
  ):
    return True

  # Fallback: generic titles accepted only when the description carries enough
  # responsibility signal. Counted rather than any()-ed, because one passing
  # mention of a term like "roadmap" appears in postings for adjacent roles
  # (recruiting for a product team, counsel supporting product) that are not
  # the job itself.
  if _phrase_in(t, profile.generic_title_fallbacks):
    hits = sum(
        1 for keyword in profile.require_in_description
        if re.search(r"\b" + re.escape(keyword.lower()) + r"\b", d)
    )
    return hits >= profile.require_in_description_min

  return False


def detect_work_mode(
    location: str,
    workplace_type: str,
    description: str,
    profile: SearchProfile = DEFAULT_PROFILE,
) -> str:
  """Classify a posting as exactly one of remote / hybrid / onsite / unknown.

  Explicit hybrid/onsite markers win over remote language, so a posting tagged
  "remote" but located "Hybrid - Toronto" is treated as hybrid.
  """
  loc_str = (location or "").lower()
  wp_type = (workplace_type or "").lower()
  text_head = (description or "").lower()[:500]

  if wp_type in ("hybrid", "onsite"):
    return wp_type

  if any(marker in loc_str for marker in profile.hybrid_markers):
    return "hybrid"

  if any(marker in loc_str for marker in profile.onsite_markers):
    return "onsite"

  if wp_type == "remote" or any(
      p in loc_str or p in text_head for p in profile.remote_positive
  ):
    return "remote"

  return "unknown"


def matches_work_mode(
    location: str,
    workplace_type: str,
    description: str,
    profile: SearchProfile = DEFAULT_PROFILE,
) -> bool:
  """Check the detected work mode against the profile's accepted modes."""
  if not profile.work_modes:
    return True

  return detect_work_mode(location, workplace_type, description, profile) in (
      profile.work_modes
  )


def matches_region(
    location: str,
    description: str,
    profile: SearchProfile = DEFAULT_PROFILE,
) -> bool:
  """Check the posting's geography against the profile's accepted regions.

  A posting that names no country -- "Remote", "Worldwide", or nothing at all
  -- passes. It does not exclude the profile's regions, and on remote-first
  boards that describes most of the genuinely open roles.
  """
  if not profile.regions:
    return True

  loc_str = (location or "").lower().strip()
  text_head = (description or "").lower()[:500]

  if any(r in loc_str or r in text_head for r in profile.regions):
    return True

  if not loc_str:
    return True
  return any(w in loc_str for w in profile.region_wildcards)


def is_eor_supported(
    location: str,
    description: str,
    profile: SearchProfile = DEFAULT_PROFILE,
) -> bool:
  """Check for an explicit Employer of Record signal.

  Word-boundary matched so short signals like "eor" can't fire on "theory" or
  "reorganization". A False here means "not stated", not "not supported" --
  most employers that do offer EOR never say so in the posting.
  """
  combined = f"{location or ''} {description or ''}".lower()

  return any(
      re.search(r"\b" + re.escape(sig) + r"\b", combined)
      for sig in profile.eor_signals
  )


def detect_hiring_reach(
    location: str,
    description: str,
    profile: SearchProfile = DEFAULT_PROFILE,
) -> str:
  """Classify how reachable a posting is from outside the employer's geography.

  Returns exactly one of HIRING_REACH_{OPEN,NEGOTIABLE,UNSTATED,BLOCKED}.
  This annotates and orders cards; it deliberately drops nothing. A detector
  can only observe what a posting *states*, and plenty of employers state a
  firm location and then hire the right candidate anyway -- those postings are
  textually identical to the ones that mean it.

  Precedence is blocked > open > negotiable. A legal bar cannot be talked
  around even by an employer that also advertises EOR, so it wins outright.

  Unlike the work-mode and region checks, this scans the FULL description:
  restriction language sits in the footer next to the EEO boilerplate, which a
  leading-500-character window never reaches.
  """
  combined = f"{location or ''} {description or ''}".lower()

  def _stated(phrases: list[str]) -> bool:
    return any(
        re.search(r"\b" + re.escape(p) + r"\b", combined) for p in phrases
    )

  if _stated(profile.hiring_blockers):
    return HIRING_REACH_BLOCKED

  if is_eor_supported(location, description, profile):
    return HIRING_REACH_OPEN

  if _stated(profile.hiring_gatekeepers):
    return HIRING_REACH_NEGOTIABLE

  return HIRING_REACH_UNSTATED


def parse_salary_info(
    text: str,
    comp_data: dict = None,
    profile: SearchProfile = DEFAULT_PROFILE,
) -> tuple[bool, str, str]:
  """Extracts compensation info and returns:

  (meets_threshold: bool, display_text: str, status_tag: str)
  status_tag options: "VERIFIED", "BELOW_THRESHOLD", "HOURLY", "UNLISTED"

  A currency the profile has no threshold for is reported as UNLISTED rather
  than dropped, so an otherwise-good posting still surfaces for manual review.
  """
  structured = _parse_structured_comp(comp_data, profile)
  if structured:
    return structured

  from_text = _parse_text_comp(text, profile)
  if from_text:
    return from_text

  return True, "Unlisted in posting", "UNLISTED"


def _parse_structured_comp(
    comp_data: dict | None,
    profile: SearchProfile,
) -> tuple[bool, str, str] | None:
  """Read a structured ATS compensation payload, if usable."""
  if not isinstance(comp_data, dict):
    return None

  min_comp = comp_data.get("targetCompensationMin")
  max_comp = comp_data.get("targetCompensationMax")
  if not isinstance(min_comp, (int, float)):
    return None

  currency = (comp_data.get("currency") or "USD").upper()
  max_str = f" - {int(max_comp):,}" if max_comp else "+"
  display = f"{currency} {int(min_comp):,}{max_str}"

  if str(comp_data.get("interval") or "").lower() in HOURLY_INTERVALS:
    return True, display, "HOURLY"

  threshold = profile.min_salary.get(currency)
  if threshold is None:
    return True, f"{display} (no {currency} threshold set)", "UNLISTED"

  if min_comp >= threshold:
    return True, display, "VERIFIED"
  return False, display, "BELOW_THRESHOLD"


def _parse_text_comp(
    text: str,
    profile: SearchProfile,
) -> tuple[bool, str, str] | None:
  """Scan free text for a salary range."""
  text = text or ""
  match = SALARY_PATTERN_LEADING.search(text) or SALARY_PATTERN_TRAILING.search(
      text
  )
  if not match:
    return None

  raw_match = match.group(0).strip()

  # Hourly rates must be caught before the annualization heuristic below,
  # which would otherwise read "$75 - $95/hr" as $75,000.
  window = (text[match.start():match.end() + 20]).lower()
  if any(marker in window for marker in HOURLY_MARKERS):
    return True, raw_match, "HOURLY"

  digits = re.findall(r"\d+", match.group("low").replace(",", ""))
  if not digits:
    return None

  low_val = int(digits[0])
  low_val = low_val * 1000 if low_val < 1000 else low_val

  currency = _detect_currency(match, text)
  threshold = profile.min_salary.get(currency) if currency else None
  if threshold is None:
    # Ambiguous "$", or a currency this profile has no target for. Fall back to
    # the most permissive threshold rather than dropping the posting.
    threshold = min(profile.min_salary.values())

  if low_val >= threshold:
    return True, raw_match, "VERIFIED"
  return False, raw_match, "BELOW_THRESHOLD"


def _detect_currency(match: re.Match, text: str) -> str | None:
  """Resolve the currency of a salary match, or None when ambiguous.

  "$" is shared by USD and CAD, so a trailing code ("... 250,000 CAD") is
  consulted before giving up.
  """
  token = (match.group("cur") or "").upper()
  if token in CURRENCY_BY_TOKEN:
    return CURRENCY_BY_TOKEN[token]

  trailing = text[match.end():match.end() + 6].upper()
  return next((code for code in CURRENCY_CODES if code in trailing), None)


def extract_key_signals(
    content: str,
    profile: SearchProfile = DEFAULT_PROFILE,
) -> str:
  """Scans text for this profile's headline signals."""
  found = [
      term
      for term in profile.key_signal_terms
      if re.search(r"\b" + re.escape(term) + r"\b", content, re.I)
  ]
  return ", ".join(found) if found else profile.key_signal_fallback


def score_location_fit(
    title: str,
    location: str,
    description: str = "",
    profile: SearchProfile = DEFAULT_PROFILE,
    reach: str | None = None,
) -> int:
  """Rate how employable the candidate is for this posting, 0-100.

  Deliberately reads the TITLE and LOCATION only, never the description.
  Country names are scattered through EEO boilerplate and office lists, so a
  full-text scan would flag almost every posting; the same reasoning already
  keeps broad terms out of `eor_signals`. The evidence is in the short fields
  anyway -- "Remote, USA" in the location, "Createspace, USA Based" in the
  title.

  `detect_hiring_reach` is the one full-text input, and only via its verdict.
  Callers that already have it should pass it in: it is the most expensive
  scan in the pipeline and `process_job_posting` needs it regardless.
  """
  if reach is None:
    reach = detect_hiring_reach(location, description, profile)
  if reach == HIRING_REACH_BLOCKED:
    return 0

  hay = f"{title or ''} {location or ''}".lower()
  names_region = bool(profile.regions) and _phrase_in(hay, profile.regions)
  names_excluded = _phrase_in(hay, profile.region_exclusions)

  # Both named means a genuinely multi-country posting ("Canada, Remote" on a
  # role titled "USA Based"). Reachable, but not on the candidate's terms.
  if names_region and names_excluded:
    return 50
  if names_region:
    return 100
  if names_excluded:
    return 0

  if reach == HIRING_REACH_OPEN:
    return 100
  if reach == HIRING_REACH_NEGOTIABLE:
    return 20

  # Nothing stated either way. The common case, and not evidence of a problem.
  return 60


def _scale_to_weight(raw: int, bucket: str, weights: dict[str, int]) -> int:
  """Scale a bucket's raw 0-`raw_max` value onto its configured weight.

  Integer arithmetic throughout: at the default weights `raw * 35 // 35`
  returns `raw` unchanged, so existing profiles keep bit-identical scores.
  Float fractions drift by a point at the boundaries.
  """
  weight = weights.get(bucket, DEFAULT_SCORE_WEIGHTS.get(bucket, 0))
  if weight <= 0:
    return 0
  raw_max = SCORE_BUCKET_RAW_MAX[bucket]
  return min(weight, (raw * weight) // raw_max)


def _role_focus_raw(title_lower: str, profile: SearchProfile) -> int:
  """Role-focus points before weighting: primary 15, secondary 12, else 0."""
  if _phrase_in(title_lower, profile.primary_role_keywords):
    return 15
  if _phrase_in(title_lower, profile.secondary_role_keywords):
    return 12
  return 0


def calculate_job_quality_components(
    title: str,
    content: str,
    salary_status: str,
    profile: SearchProfile = DEFAULT_PROFILE,
    location: str = "",
    reach: str | None = None,
) -> dict[str, int]:
  """Score a posting bucket by bucket, scaled to the profile's weights.

  Every bucket is computed on its own raw scale and then scaled by
  `profile.score_weights`, so a profile changes what matters by redrawing the
  weights rather than by editing this function. Buckets weighted 0 are absent
  from the result and from the card.
  """
  weights = profile.score_weights
  content_lower = content.lower()
  title_lower = title.lower()
  combined_text = f"{title_lower} {content_lower}"

  def _hits(terms: list[str]) -> int:
    return sum(
        1 for term in terms
        if re.search(r"\b" + re.escape(term.lower()) + r"\b", combined_text)
    )

  # 1. Signal match. Scanned over the whole description, the same text
  # extract_key_signals sees. A truncated window made the two disagree, so a
  # card could list four signals and still score them as zero.
  raw = {
      "signal": min(35, (_hits(profile.premium_signals) * 7)
                    + (_hits(profile.good_signals) * 3)),
      # 2. Level match: binary on the title.
      "level": 30 if any(
          level in title_lower for level in profile.high_level_keywords
      ) else 0,
      # 3. Salary fit. An hourly rate scores the same as an unlisted one:
      # present, but not verified against an annual target.
      "salary": SALARY_STATUS_POINTS.get(salary_status, 0),
      # 4. Role focus.
      "role": _role_focus_raw(title_lower, profile),
      # 5. Location / work-authorization fit.
      "location": score_location_fit(title, location, content, profile, reach),
      # 6. Tooling. A small nudge, never a requirement, so a posting that
      # names none of them is not penalised beyond forgoing the bucket.
      # Scored against a handful of hits rather than the whole list: the
      # bucket is only worth a few points, so dividing by a long list rounds
      # every realistic posting down to zero.
      "tools": min(100, _hits(profile.tool_signals) * 25),
  }

  components = {
      bucket: _scale_to_weight(value, bucket, weights)
      for bucket, value in raw.items()
      if weights.get(bucket, DEFAULT_SCORE_WEIGHTS.get(bucket, 0)) > 0
  }
  components["total"] = min(100, sum(components.values()))
  return components


def calculate_job_quality_score(
    title: str,
    content: str,
    salary_status: str,
    profile: SearchProfile = DEFAULT_PROFILE,
    location: str = "",
    reach: str | None = None,
) -> int:
  """Total quality score, 0-100. See calculate_job_quality_components."""
  return calculate_job_quality_components(
      title, content, salary_status, profile, location, reach
  )["total"]


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


def _salary_badge(match: dict) -> tuple[str, int]:
  """Return the compensation badge text and the embed colour for a match."""
  status = match["salary_status"]
  if status == "VERIFIED":
    return f"🟢 **{match['salary_text']}** (Verified)", 0x2ECC71
  if status == "HOURLY":
    return f"🕐 **{match['salary_text']}** (Hourly rate)", 0xF1C40F
  if status == "UNLISTED":
    return f"⚠️ **{match['salary_text']}**", 0xF1C40F
  return f"🔴 **{match['salary_text']}** (Below target)", 0xE74C3C


SCORE_BAR_WIDTH = 20


def _score_bar(value: int, max_pts: int) -> str:
  """Fixed-width Unicode meter for one bucket."""
  filled = int((value / max_pts) * SCORE_BAR_WIDTH) if max_pts > 0 else 0
  return f"{'█' * filled}{'░' * (SCORE_BAR_WIDTH - filled)}"


def _score_strength_emoji(value: int, max_pts: int) -> str:
  """Coloured circle reflecting how much of a bucket the posting earned."""
  if max_pts == 0:
    return "⚪"
  pct = value / max_pts
  if pct >= 0.70:
    return "🟢"
  if pct >= 0.30:
    return "🟡"
  return "🔴"


def _score_verdict(total: int) -> tuple[str, str]:
  """Overall emoji and label for a total score."""
  if total >= 85:
    return "⭐", "Excellent Match"
  if total >= 70:
    return "✅", "Strong Match"
  if total >= 50:
    return "🔶", "Moderate Match"
  return "🔹", "Low Match"


def _score_breakdown_lines(
    components: dict[str, int],
    weights: dict[str, int],
) -> list[str]:
  """One bar per weighted bucket, in the order the weights declare them.

  Iterating the weights means a profile that redraws its buckets gets a card
  matching its own scoring, and a bucket weighted 0 renders nothing at all.
  """
  lines = []
  for bucket, max_pts in weights.items():
    if max_pts <= 0 or bucket not in components:
      continue
    value = components[bucket]
    label = f"{SCORE_BUCKET_LABELS.get(bucket, bucket.title())}:"
    lines.append(
        f"{_score_strength_emoji(value, max_pts)} {label:<9}"
        f" {_score_bar(value, max_pts)} ({value})"
    )
  return lines


def _score_badge(
    score: int,
    components: dict[str, int] | None = None,
    weights: dict[str, int] | None = None,
) -> str:
  """Build score display. If components provided, show detailed breakdown with bars.

  `weights` supplies each bucket's maximum. It defaults to
  DEFAULT_SCORE_WEIGHTS, so a caller holding a plain four-bucket component
  dict renders exactly as before.
  """
  if components is None:
    emoji, label_text = _score_verdict(score)
    return f"{emoji} {score}/100 ({label_text.replace('Match', 'match')})"

  total = components["total"]
  emoji, label_text = _score_verdict(total)
  lines = _score_breakdown_lines(components, weights or DEFAULT_SCORE_WEIGHTS)
  lines.append("─" * 40)
  lines.append(f"{emoji} **{total}/100** — {label_text}")
  return "\n".join(lines)


def build_job_embed(
    match: dict,
    run_time_str: str,
) -> dict:
  """Build the Discord embed for a single match."""
  salary_badge, color = _salary_badge(match)

  location_value = f"{match['location']} — {match['work_mode'].title()}"
  fields = [
      {"name": "📊 Quality Breakdown",
       "value": _score_badge(
           match["quality_score"],
           match.get("score_components"),
           match.get("score_weights"),
       ),
       "inline": False},
      {"name": "💰 Compensation", "value": salary_badge, "inline": True},
      {"name": "📍 Location & Work Type", "value": location_value,
       "inline": True},
  ]

  # Only claimed when the posting actually says so. Absence of this field
  # means "not stated", which is the common case even for employers that do
  # support EOR.
  if match.get("eor_detected"):
    fields.append(
        {"name": "🌍 EOR", "value": "Supports EOR", "inline": True}
    )

  # UNSTATED renders nothing, for the same reason: the posting made no claim.
  reach_badge = HIRING_REACH_BADGES.get(match.get("hiring_reach"))
  if reach_badge:
    fields.append(
        {"name": "🧭 Hiring Reach", "value": reach_badge, "inline": True}
    )

  fields.extend([
      {"name": "🛠️ Key Signals", "value": match.get("key_tech") or "Not specified",
       "inline": True},
      {"name": "👔 Recruiter Outreach",
       "value": f"[Find Hiring Team on LinkedIn]({match['recruiter_url']})",
       "inline": False},
      {"name": "📝 Quick Outreach Note",
       "value": f"```\n{match['outreach_note']}\n```", "inline": False},
  ])

  source = match["source"]
  return {
      "title": f"{match['title']} @ {match['company']}",
      "url": match["url"],
      "color": color,
      "fields": fields,
      "footer": {
          "text": (
              f"Source: {SOURCE_ATTRIBUTION.get(source, source.upper())}"
              f" • Found {run_time_str}"
          )
      },
  }



def send_discord_alerts(
    matches: list[dict],
    profile: SearchProfile = DEFAULT_PROFILE,
):
  """Dispatch enriched embeds to the profile's Discord webhook."""
  webhook_url = get_webhook_url(profile)
  if not webhook_url or not matches:
    return

  alertable = [
      m for m in matches
      if m.get("quality_score", 0) >= profile.alert_threshold
  ]
  skipped = len(matches) - len(alertable)
  if skipped:
    print(
        f"{skipped} match(es) below alert_threshold"
        f" {profile.alert_threshold}; counted but not carded."
    )
  if not alertable:
    return

  run_time_str = get_formatted_timestamp(profile.timezone)

  # Most-reachable first, then best-scoring. Nothing is dropped by reach; a
  # legally-blocked posting still gets a card, it just lands at the bottom.
  alertable.sort(
      key=lambda m: (
          HIRING_REACH_ORDER.get(
              m.get("hiring_reach"), HIRING_REACH_ORDER[HIRING_REACH_UNSTATED]
          ),
          -m.get("quality_score", 0),
      )
  )
  embeds = [build_job_embed(m, run_time_str) for m in alertable]

  # Discord accepts up to 10 embeds per message. Batching keeps a broad
  # source from tripping the webhook rate limit.
  for i in range(0, len(embeds), DISCORD_EMBEDS_PER_MESSAGE):
    batch = embeds[i:i + DISCORD_EMBEDS_PER_MESSAGE]
    try:
      requests.post(webhook_url, json={"embeds": batch}, timeout=20)
    except Exception as e:
      print(f"Failed to post alert batch {i // DISCORD_EMBEDS_PER_MESSAGE}: {e}")


def process_job_posting(
    job: dict,
    profile: SearchProfile = DEFAULT_PROFILE,
) -> dict | None:
  """Central evaluation pipeline for every detected role.

  `job` is the normalized shape every fetcher produces:
      id, source, company, title, location, workplace_type, content, url,
      comp_data (optional)
  Keeping fetchers responsible for normalization means ATS-specific field
  names never leak into filtering or alerting.
  """
  title = job.get("title") or ""
  content = job.get("content") or ""
  location = job.get("location") or ""
  company = job.get("company") or ""

  if not is_target_role(title, content, profile):
    return None

  work_mode = detect_work_mode(
      location, job.get("workplace_type") or "", content, profile
  )
  if profile.work_modes and work_mode not in profile.work_modes:
    return None

  if not matches_region(location, content, profile):
    return None

  eor_detected = is_eor_supported(location, content, profile)
  if profile.require_eor and not eor_detected:
    return None

  # Annotation only -- never a rejection. See detect_hiring_reach.
  hiring_reach = detect_hiring_reach(location, content, profile)

  _, salary_text, salary_status = parse_salary_info(
      content, job.get("comp_data"), profile
  )

  if salary_status == "BELOW_THRESHOLD":
    return None

  key_tech = extract_key_signals(content, profile)
  score_components = calculate_job_quality_components(
      title, content, salary_status, profile, location, hiring_reach
  )
  quality_score = score_components["total"]
  recruiter_url = (
      "https://www.linkedin.com/search/results/people/?keywords="
      f"{quote_plus(company)}%20recruiter"
  )
  outreach_note = profile.outreach_note_template.format(
      title=title, company=company
  )

  return {
      "id": job["id"],
      "source": job.get("source") or "unknown",
      "company": company,
      "title": title,
      "url": job.get("url"),
      "location": location or "Remote",
      "work_mode": work_mode,
      "eor_detected": eor_detected,
      "hiring_reach": hiring_reach,
      "salary_text": salary_text,
      "salary_status": salary_status,
      "key_tech": key_tech,
      "quality_score": quality_score,
      "score_components": score_components,
      "score_weights": profile.score_weights,
      "recruiter_url": recruiter_url,
      "outreach_note": outreach_note,
  }


# =============================================================================
# ATS POLLING ENGINES
# =============================================================================
def _fetch_json(url: str, label: str):
  """GET and parse JSON, returning None on any failure.

  A non-200 is logged rather than swallowed: a dead board slug is otherwise
  indistinguishable from a live board with no matching roles.
  """
  try:
    resp = requests.get(url, timeout=20, headers={"User-Agent": HTTP_USER_AGENT})
    if resp.status_code != 200:
      print(f"{label}: HTTP {resp.status_code}")
      return None
    return resp.json()
  except Exception as e:
    print(f"Error fetching {label}: {e}")
    return None


def _run_board_source(
    source: str,
    profile: SearchProfile,
    seen_jobs: set,
    url_for,
    jobs_from,
    normalize,
) -> list[dict]:
  """Poll every configured board for one ATS and evaluate its postings."""
  matches = []
  for board in profile.boards.get(source, []):
    payload = _fetch_json(url_for(board), f"{source.capitalize()} board {board}")
    if payload is None:
      continue

    for raw in jobs_from(payload):
      job = normalize(raw, board)
      if job["id"] in seen_jobs:
        continue

      match = process_job_posting(job, profile)
      if match:
        matches.append(match)
  return matches


def html_to_text(raw: str) -> str:
  """Flatten an HTML job description into plain text for filtering and scoring.

  Two unescape passes are deliberate. Greenhouse's `?content=true` payload is
  an entity-escaped HTML document, so entities belonging to the markup itself
  arrive escaped twice: the pay-transparency em dash is literally
  `&amp;mdash;`. The first pass peels the API's encoding, the second resolves
  the document's own entities.

  Tags collapse to a space rather than being deleted. Removing them outright
  would fuse `<li>React</li><li>Go</li>` into one token and defeat the
  word-boundary matching that signal extraction and scoring rely on.
  """
  if not raw:
    return ""
  text = HTML_TAG_PATTERN.sub(" ", html.unescape(raw))
  return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _normalize_ashby(job: dict, board: str) -> dict:
  raw_id = job.get("id") or job.get("jobUrl")
  return {
      "id": f"ashby_{board}_{raw_id}",
      "source": "ashby",
      "company": board.capitalize(),
      "title": job.get("title", ""),
      "location": job.get("location", ""),
      "workplace_type": job.get("workplaceType", ""),
      "content": job.get("descriptionPlain")
      or html_to_text(job.get("descriptionHtml") or ""),
      "url": job.get("jobUrl") or job.get("applyUrl"),
      "comp_data": job.get("compensation"),
  }


def _normalize_greenhouse(job: dict, board: str) -> dict:
  location_obj = job.get("location", {})
  loc_name = (
      location_obj.get("name", "")
      if isinstance(location_obj, dict)
      else str(location_obj)
  )
  return {
      "id": f"greenhouse_{board}_{job.get('id')}",
      "source": "greenhouse",
      "company": board.capitalize(),
      "title": job.get("title", ""),
      "location": loc_name,
      "workplace_type": "remote" if "remote" in loc_name.lower() else "",
      "content": html_to_text(job.get("content", "")),
      "url": job.get("absolute_url"),
      "comp_data": None,
  }


def _normalize_lever(job: dict, board: str) -> dict:
  categories = job.get("categories", {})
  return {
      "id": f"lever_{board}_{job.get('id')}",
      "source": "lever",
      "company": board.capitalize(),
      "title": job.get("text", ""),
      "location": categories.get("location", ""),
      "workplace_type": job.get("workplaceType", ""),
      "content": job.get("descriptionPlain") or job.get("description") or "",
      "url": job.get("hostedUrl"),
      "comp_data": None,
  }


# Per-ATS board endpoint and payload shape. Hoisted to module level so the
# board health check can exercise exactly the URLs the tracker polls -- an
# inline lambda would let the checker and the fetcher drift apart silently,
# which is the same class of bug the check exists to catch.
BOARD_ENDPOINTS = {
    "ashby": {
        "url_for": lambda b: (
            f"https://api.ashbyhq.com/posting-api/job-board/{b}"
            "?includeCompensation=true"
        ),
        "jobs_from": lambda payload: payload.get("jobs", []),
    },
    "greenhouse": {
        "url_for": lambda b: (
            f"https://boards-api.greenhouse.io/v1/boards/{b}/jobs?content=true"
        ),
        "jobs_from": lambda payload: payload.get("jobs", []),
    },
    "lever": {
        "url_for": lambda b: f"https://api.lever.co/v0/postings/{b}?mode=json",
        "jobs_from": lambda payload: payload,
    },
}


def check_ashby(
    seen_jobs: set,
    profile: SearchProfile = DEFAULT_PROFILE,
) -> list[dict]:
  return _run_board_source(
      "ashby",
      profile,
      seen_jobs,
      url_for=BOARD_ENDPOINTS["ashby"]["url_for"],
      jobs_from=BOARD_ENDPOINTS["ashby"]["jobs_from"],
      normalize=_normalize_ashby,
  )


def check_greenhouse(
    seen_jobs: set,
    profile: SearchProfile = DEFAULT_PROFILE,
) -> list[dict]:
  return _run_board_source(
      "greenhouse",
      profile,
      seen_jobs,
      url_for=BOARD_ENDPOINTS["greenhouse"]["url_for"],
      jobs_from=BOARD_ENDPOINTS["greenhouse"]["jobs_from"],
      normalize=_normalize_greenhouse,
  )


def check_lever(
    seen_jobs: set,
    profile: SearchProfile = DEFAULT_PROFILE,
) -> list[dict]:
  return _run_board_source(
      "lever",
      profile,
      seen_jobs,
      url_for=BOARD_ENDPOINTS["lever"]["url_for"],
      jobs_from=BOARD_ENDPOINTS["lever"]["jobs_from"],
      normalize=_normalize_lever,
  )


SOURCE_FETCHERS = {
    "ashby": check_ashby,
    "greenhouse": check_greenhouse,
    "lever": check_lever,
}


# =============================================================================
# AGGREGATOR POLLING ENGINES
# =============================================================================
# Unlike the ATS engines above, these are company-agnostic feeds: one request
# returns postings from many employers. They are the only way a profile with no
# curated board slugs finds anything at all. Attribution is mandatory -- see
# SOURCE_ATTRIBUTION near the top of this file.

# Himalayas caps its page size at 20 regardless of what `limit` asks for, so
# breadth costs requests.
HIMALAYAS_PAGE_SIZE = 20


def _normalize_remoteok(job: dict) -> dict | None:
  """Map a Remote OK posting onto the shared job shape."""
  job_id = job.get("id")
  if not job_id:
    return None

  # Remote OK reports "0" for both bounds when compensation is unknown.
  salary_min = _coerce_int(job.get("salary_min"))
  salary_max = _coerce_int(job.get("salary_max"))
  comp_data = None
  if salary_min:
    comp_data = {
        "targetCompensationMin": salary_min,
        "targetCompensationMax": salary_max or None,
        "currency": "USD",
        "interval": "yearly",
    }

  tags = job.get("tags") or []
  return {
      "id": f"remoteok_{job_id}",
      "source": "remoteok",
      "company": job.get("company") or "Unknown",
      "title": job.get("position") or "",
      "location": job.get("location") or "Remote",
      "workplace_type": "remote",
      "content": " ".join([
          job.get("description") or "",
          _join_feed_values(tags),
      ]),
      "url": job.get("url") or job.get("apply_url"),
      "comp_data": comp_data,
  }


def _normalize_himalayas(job: dict) -> dict | None:
  """Map a Himalayas posting onto the shared job shape."""
  guid = job.get("guid")
  if not guid:
    return None

  min_salary = _coerce_int(job.get("minSalary"))
  comp_data = None
  if min_salary:
    comp_data = {
        "targetCompensationMin": min_salary,
        "targetCompensationMax": _coerce_int(job.get("maxSalary")) or None,
        "currency": job.get("currency") or "USD",
        "interval": job.get("salaryPeriod") or "yearly",
    }

  restrictions = job.get("locationRestrictions") or []
  categories = job.get("categories") or []
  seniority = job.get("seniority") or []
  return {
      "id": f"himalayas_{guid}",
      "source": "himalayas",
      "company": job.get("companyName") or "Unknown",
      "title": job.get("title") or "",
      "location": ", ".join(map(str, restrictions)) or "Remote",
      "workplace_type": "remote",
      "content": " ".join([
          job.get("description") or "",
          job.get("excerpt") or "",
          _join_feed_values(seniority),
          _join_feed_values(categories),
      ]),
      "url": job.get("applicationLink"),
      "comp_data": comp_data,
  }


def _join_feed_values(value) -> str:
  """Flatten a feed field that may arrive as a string or a list of strings."""
  if isinstance(value, str):
    return value
  if isinstance(value, (list, tuple)):
    return " ".join(str(v) for v in value)
  return ""


def _coerce_int(value) -> int | None:
  """Read an int from a feed field that may be a string, None, or zero."""
  try:
    number = int(float(value))
  except (TypeError, ValueError):
    return None
  return number or None


def _evaluate_jobs(raw_jobs, normalize, seen_jobs: set, profile: SearchProfile):
  """Normalize, de-duplicate and score a batch of postings."""
  matches = []
  for raw in raw_jobs:
    if not isinstance(raw, dict):
      continue
    job = normalize(raw)
    if not job or job["id"] in seen_jobs:
      continue
    match = process_job_posting(job, profile)
    if match:
      matches.append(match)
  return matches


def check_remoteok(
    seen_jobs: set,
    profile: SearchProfile = DEFAULT_PROFILE,
) -> list[dict]:
  """Poll Remote OK's public feed (a single request returns the full feed)."""
  payload = _fetch_json("https://remoteok.com/api", "Remote OK")
  if not isinstance(payload, list):
    return []

  # Element 0 is a legal/metadata header rather than a posting.
  return _evaluate_jobs(payload[1:], _normalize_remoteok, seen_jobs, profile)


def check_himalayas(
    seen_jobs: set,
    profile: SearchProfile = DEFAULT_PROFILE,
) -> list[dict]:
  """Walk Himalayas' cursor-paginated feed, newest postings first."""
  matches = []
  cursor = None

  for page in range(profile.aggregator_max_pages):
    url = f"https://himalayas.app/jobs/api?limit={HIMALAYAS_PAGE_SIZE}"
    if cursor:
      url += f"&cursor={quote_plus(cursor)}"

    payload = _fetch_json(url, f"Himalayas page {page + 1}")
    if not isinstance(payload, dict):
      break

    jobs = payload.get("jobs") or []
    if not jobs:
      break

    matches.extend(_evaluate_jobs(jobs, _normalize_himalayas, seen_jobs, profile))

    cursor = payload.get("nextCursor")
    if not cursor:
      break

  return matches


SOURCE_FETCHERS["remoteok"] = check_remoteok
SOURCE_FETCHERS["himalayas"] = check_himalayas


def collect_matches(
    seen_jobs: set,
    profile: SearchProfile = DEFAULT_PROFILE,
) -> list[dict]:
  """Run every source the profile enables and merge the results."""
  matches = []
  for source in profile.sources:
    fetcher = SOURCE_FETCHERS.get(source)
    if not fetcher:
      print(f"WARNING: unknown source '{source}' in profile '{profile.name}'")
      continue
    matches.extend(fetcher(seen_jobs, profile))
  return matches


# =============================================================================
# MAIN EXECUTION
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="Remote job tracker")
    parser.add_argument(
        "--profile",
        help="Path to a YAML profile file. Omit to use the built-in defaults.",
    )
    args = parser.parse_args()

    profile = load_profile(args.profile)
    print(f"Running profile: {profile.name}")

    if not get_webhook_url(profile):
        print(
            f"WARNING: no Discord webhook configured for profile"
            f" '{profile.name}'. Alerts will be skipped."
        )

    init_db()  # Initialize database on startup
    seen_jobs = load_seen_jobs(profile.name)

    all_matches = collect_matches(seen_jobs, profile)

    if all_matches:
        print(f"Found {len(all_matches)} new matching roles. Dispatching alerts...")
        send_discord_alerts(all_matches, profile)
        # Only the new IDs need writing; the rest are already stored.
        save_seen_jobs({m["id"] for m in all_matches}, profile.name)
    else:
        print("Execution complete. No new matching roles found.")


if __name__ == "__main__":
    main()


