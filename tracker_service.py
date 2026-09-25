#!/usr/bin/env python3
"""
Companion web service for the Discord action links.

The tracker signs a token into every alert card; this service verifies it and
records the stage change. It is deployed separately (Railway) from the tracker
(GitHub Actions), so both must carry the same TRACKER_SIGNING_KEY -- HMAC is
symmetric, and a mismatch makes every link 400.

    uvicorn tracker_service:app --reload

Required environment:
    TRACKER_SIGNING_KEY   same value as the tracker's
    DATABASE_URL          the job-tracker database

Why GET renders a form instead of just doing the work: Discord unfurls every
URL it sees, and so do link scanners, mobile clients and corporate proxies. A
GET that writes would mark jobs applied on its own, corrupting the exact
signal this is meant to capture. GET is therefore read-only and the write
lives behind POST.
"""

from __future__ import annotations

import html
import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from track_jobs import (
    InvalidActionToken,
    SIGNING_KEY_ENV,
    get_signing_key,
    load_application,
    update_application_stage,
    verify_action,
)

app = FastAPI(title="Peckham Rye tracker actions", docs_url=None, redoc_url=None)

# Tokens travel in the path, so they would otherwise leak to any third-party
# resource the page references via the Referer header.
SECURITY_HEADERS = {
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
}

PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{title}</title>
<style>
  body {{ font: 16px/1.5 system-ui, sans-serif; margin: 0; padding: 2rem;
         display: flex; justify-content: center; background: #f6f7f9; }}
  main {{ max-width: 32rem; width: 100%; background: #fff; padding: 2rem;
          border-radius: 12px; box-shadow: 0 1px 4px rgba(0,0,0,.12); }}
  h1 {{ font-size: 1.25rem; margin: 0 0 1rem; }}
  dl {{ margin: 0 0 1.5rem; }}
  dt {{ font-size: .75rem; text-transform: uppercase; color: #667;
        letter-spacing: .04em; }}
  dd {{ margin: 0 0 .75rem; font-weight: 600; }}
  button {{ font: inherit; font-weight: 600; padding: .7rem 1.4rem;
            border: 0; border-radius: 8px; background: #2ecc71; color: #fff;
            cursor: pointer; }}
  .muted {{ color: #667; font-size: .875rem; }}
</style>
<main>{body}</main>
"""


def _render(body: str, title: str, status: int) -> HTMLResponse:
  return HTMLResponse(
      PAGE.format(title=html.escape(title), body=body),
      status_code=status,
      headers=SECURITY_HEADERS,
  )


def _message(title: str, detail: str, status: int) -> HTMLResponse:
  return _render(
      f"<h1>{html.escape(title)}</h1><p class=muted>{html.escape(detail)}</p>",
      title,
      status,
  )


def _resolve(token: str) -> tuple[dict | None, HTMLResponse | None]:
  """Verify a token and load its application. Returns (context, error page)."""
  key = get_signing_key()
  if not key:
    # Configuration fault, not a client one -- don't imply a bad link.
    return None, _message(
        "Service not configured",
        f"{SIGNING_KEY_ENV} is not set on this deployment.",
        503,
    )

  try:
    claims = verify_action(token, key)
  except InvalidActionToken as exc:
    return None, _message(
        "Link not valid",
        f"This link could not be used ({exc}). Update the stage from the"
        " command line instead.",
        400,
    )

  application = load_application(claims["j"], claims["p"])
  if application is None:
    return None, _message(
        "Not found",
        "No tracked application matches this link.",
        404,
    )

  return {"claims": claims, "application": application}, None


@app.get("/health")
def health() -> dict:
  """Liveness probe that reports config without leaking the key."""
  return {
      "ok": True,
      "signing_key_configured": get_signing_key() is not None,
      "database_configured": bool(os.environ.get("DATABASE_URL")),
  }


@app.get("/a/{token}", response_class=HTMLResponse)
def confirm(token: str) -> HTMLResponse:
  """Render a confirmation form. Never writes -- see the module docstring."""
  context, error = _resolve(token)
  if error:
    return error

  stage = context["claims"]["s"]
  app_row = context["application"]

  if app_row["current_stage"] == stage:
    return _message(
        "Already recorded",
        f"{app_row['role_title']} at {app_row['company']} is already marked"
        f" '{stage}'.",
        200,
    )

  body = f"""
    <h1>Mark as {html.escape(stage)}?</h1>
    <dl>
      <dt>Role</dt><dd>{html.escape(app_row['role_title'])}</dd>
      <dt>Company</dt><dd>{html.escape(app_row['company'])}</dd>
      <dt>Current stage</dt><dd>{html.escape(app_row['current_stage'])}</dd>
    </dl>
    <form method="post">
      <button type="submit">Confirm</button>
    </form>
  """
  return _render(body, f"Mark as {stage}", 200)


@app.post("/a/{token}", response_class=HTMLResponse)
def commit(token: str) -> HTMLResponse:
  """Apply the stage change. Idempotent: re-posting writes no extra history."""
  context, error = _resolve(token)
  if error:
    return error

  claims = context["claims"]
  app_row = context["application"]
  ok = update_application_stage(claims["j"], claims["s"], claims["p"])

  if not ok:
    return _message("Update failed", "The application could not be updated.", 500)

  return _message(
      f"Marked as {claims['s']}",
      f"{app_row['role_title']} at {app_row['company']} is now"
      f" '{claims['s']}'.",
      200,
  )
