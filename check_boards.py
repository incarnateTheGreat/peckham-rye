#!/usr/bin/env python3
"""
Board health check for the curated ATS slugs.

Slug rot is silent. A company gets acquired or migrates ATS, its board starts
404ing, the fetcher skips it, and the tracker keeps reporting success with a
quietly smaller search. StatsBomb -> Hudl is the worked example: it had been
dead for as long as the config existed.

This is deliberately NOT part of the unit suite. It makes live network calls,
so putting it in `pytest` would make CI fail whenever an ATS hiccuped. It runs
on its own schedule instead, and never blocks a tracker run.

    python check_boards.py                       # every profile
    python check_boards.py --profile profiles/engineering.yml
    python check_boards.py --fail-on-empty       # also fail on 0-posting boards

Exit status:
    0  every board answered, and none were dead
    1  at least one board is dead (or unreachable, or malformed)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from track_jobs import BOARD_ENDPOINTS, HTTP_USER_AGENT, load_profile

PROFILES_DIR = Path(__file__).parent / "profiles"

# Slugs are interpolated into a URL path. They come from a committed config
# file rather than user input, but validating here keeps a stray "../" or a
# pasted full URL from being sent as a request.
SLUG_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]*\Z")

REQUEST_TIMEOUT = 20
MAX_WORKERS = 12

# Outcome codes, ordered worst-first for reporting.
DEAD = "DEAD"
UNREACHABLE = "UNREACHABLE"
MALFORMED = "MALFORMED"
EMPTY = "EMPTY"
OK = "OK"
PERSISTENT_EMPTY = "PERSISTENT_EMPTY"


def _board_key(source: str, slug: str) -> str:
  return f"{source}/{slug}"


def load_empty_streaks(path: Path) -> dict[str, int]:
  """Load prior EMPTY streak counters from disk."""
  if not path.exists():
    return {}
  try:
    data = json.loads(path.read_text(encoding="utf-8"))
  except (OSError, ValueError):
    return {}

  if not isinstance(data, dict):
    return {}
  streaks = {}
  for key, value in data.items():
    if isinstance(key, str) and isinstance(value, int) and value >= 0:
      streaks[key] = value
  return streaks


def save_empty_streaks(path: Path, streaks: dict[str, int]) -> None:
  """Persist EMPTY streak counters for the next run."""
  path.parent.mkdir(parents=True, exist_ok=True)
  payload = json.dumps(streaks, indent=2, sort_keys=True)
  path.write_text(payload + "\n", encoding="utf-8")


def next_empty_streaks(
    previous: dict[str, int],
    results: list[tuple[str, str, str, str]],
) -> dict[str, int]:
  """Advance per-board EMPTY streaks based on current outcomes."""
  current: dict[str, int] = {}
  for source, slug, outcome, _ in results:
    key = _board_key(source, slug)
    current[key] = previous.get(key, 0) + 1 if outcome == EMPTY else 0
  return current


def classify(status_code: int | None, job_count: int | None) -> tuple[str, str]:
  """Map a probe result onto an outcome and a human explanation.

  The distinction this encodes is the one that caused the original confusion:
  a 404 board is never polled at all and is a coverage gap, whereas a 200
  board with no postings was polled correctly and simply had nothing to say.
  """
  if status_code is None:
    return UNREACHABLE, "request failed"
  if status_code != 200:
    return DEAD, f"HTTP {status_code}"
  if not job_count:
    return EMPTY, "HTTP 200 but no postings"
  return OK, f"{job_count} postings"


def probe(source: str, slug: str) -> tuple[str, str, str, str]:
  """Fetch one board. Returns (source, slug, outcome, detail)."""
  if not SLUG_PATTERN.match(slug):
    return source, slug, MALFORMED, "not a bare lowercase slug"

  endpoint = BOARD_ENDPOINTS[source]
  try:
    resp = requests.get(
        endpoint["url_for"](slug),
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": HTTP_USER_AGENT},
    )
  except requests.RequestException as exc:
    return source, slug, UNREACHABLE, type(exc).__name__

  if resp.status_code != 200:
    outcome, detail = classify(resp.status_code, None)
    return source, slug, outcome, detail

  try:
    jobs = endpoint["jobs_from"](resp.json())
  except ValueError:
    return source, slug, DEAD, "HTTP 200 but body was not JSON"

  outcome, detail = classify(200, len(jobs or []))
  return source, slug, outcome, detail


def collect_boards(profile_paths: list[Path]) -> dict[tuple[str, str], list[str]]:
  """Map every (source, slug) to the profiles that reference it.

  Profiles routinely share slugs, and probing the same board once per profile
  would triple the request count for no extra information.
  """
  boards: dict[tuple[str, str], list[str]] = {}
  for path in profile_paths:
    profile = load_profile(str(path))
    for source, slugs in profile.boards.items():
      if source not in BOARD_ENDPOINTS:
        print(f"WARNING: {profile.name} lists unknown ATS '{source}'")
        continue
      for slug in slugs or []:
        boards.setdefault((source, slug), []).append(profile.name)
  return boards


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument(
      "--profile",
      action="append",
      dest="profiles",
      help="Profile YAML to check. Repeatable. Defaults to every profile.",
  )
  parser.add_argument(
      "--fail-on-empty",
      action="store_true",
      help="Treat a live board with zero postings as a failure too.",
  )
  parser.add_argument(
      "--empty-state-file",
      help=(
          "Optional JSON file that stores consecutive EMPTY streaks by"
          " board between runs."
      ),
  )
  parser.add_argument(
      "--empty-streak-threshold",
      type=int,
      default=3,
      help="Report boards that have been EMPTY this many runs in a row.",
  )
  args = parser.parse_args()

  paths = (
      [Path(p) for p in args.profiles]
      if args.profiles
      else sorted(PROFILES_DIR.glob("*.yml"))
  )
  if not paths:
    print("No profiles to check.")
    return 1

  boards = collect_boards(paths)
  print(
      f"Checking {len(boards)} boards from {len(paths)} profile(s): "
      f"{', '.join(p.stem for p in paths)}\n"
  )

  with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
    results = list(pool.map(lambda kv: probe(*kv), boards))

  grouped: dict[str, list[tuple[str, str, str]]] = {}
  for source, slug, outcome, detail in results:
    grouped.setdefault(outcome, []).append((source, slug, detail))

  for outcome in (MALFORMED, DEAD, UNREACHABLE, EMPTY):
    entries = grouped.get(outcome)
    if not entries:
      continue
    print(f"{outcome} ({len(entries)})")
    for source, slug, detail in sorted(entries):
      owners = ", ".join(boards[(source, slug)])
      print(f"  {source:11} {slug:24} {detail:28} [{owners}]")
    print()

  persistent_empty = []
  if args.empty_state_file:
    state_path = Path(args.empty_state_file)
    previous = load_empty_streaks(state_path)
    streaks = next_empty_streaks(previous, results)
    save_empty_streaks(state_path, streaks)

    for source, slug, outcome, _ in results:
      key = _board_key(source, slug)
      streak = streaks.get(key, 0)
      if outcome == EMPTY and streak >= max(args.empty_streak_threshold, 1):
        persistent_empty.append((source, slug, streak))

  if persistent_empty:
    print(f"{PERSISTENT_EMPTY} (>= {args.empty_streak_threshold} runs) ({len(persistent_empty)})")
    for source, slug, streak in sorted(persistent_empty):
      owners = ", ".join(boards[(source, slug)])
      print(f"  {source:11} {slug:24} {streak:>2} empty runs in a row [{owners}]")
    print()

  ok_count = len(grouped.get(OK, []))
  print(
      f"Summary: {ok_count} healthy, "
      f"{len(grouped.get(EMPTY, []))} empty, "
      f"{len(grouped.get(DEAD, []))} dead, "
      f"{len(grouped.get(UNREACHABLE, []))} unreachable, "
      f"{len(grouped.get(MALFORMED, []))} malformed"
  )

  failed = (
      grouped.get(DEAD, [])
      + grouped.get(UNREACHABLE, [])
      + grouped.get(MALFORMED, [])
  )
  if args.fail_on_empty:
    failed += grouped.get(EMPTY, [])

  if failed:
    print(
        "\nDead boards are a coverage gap, not an empty result: the company is"
        "\nnever polled. Move the slug to the ATS the company actually uses, or"
        "\ndrop it from the profile."
    )
    return 1
  return 0


if __name__ == "__main__":
  sys.exit(main())
