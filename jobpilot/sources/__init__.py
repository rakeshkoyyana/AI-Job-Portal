"""Job sources.

* LinkedIn / Indeed / Glassdoor / Handshake: via your saved-search ALERT EMAILS (alerts.py). They are
  never scraped or logged into: their terms forbid it and accounts get banned.
* Company career sites: Workday (workday.py) and any career-page URL via JSON-LD (importer.py),
  plus Greenhouse / Lever public boards (many career pages are hosted there).
* Remotive / Adzuna: optional, off by default.
"""
from __future__ import annotations

import logging
import os

import requests

from .base import Job, clean_html, looks_remote
from .workday import fetch_workday

log = logging.getLogger(__name__)
UA = {"User-Agent": "JobPilot/0.1 (personal job search tool)"}
TIMEOUT = 25


def _get(url: str, **params):
    r = requests.get(url, params=params or None, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def fetch_greenhouse(token: str) -> list[Job]:
    data = _get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", content="true")
    out = []
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        out.append(Job("greenhouse", f"{token}:{j['id']}", j["title"], token.replace("-", " ").title(),
                       loc, j["absolute_url"], clean_html(j.get("content", "")),
                       j.get("updated_at", ""), looks_remote(loc, j["title"])))
    return out


def fetch_lever(company: str) -> list[Job]:
    data = _get(f"https://api.lever.co/v0/postings/{company}", mode="json")
    out = []
    for j in data:
        loc = (j.get("categories") or {}).get("location", "") or ""
        out.append(Job("lever", f"{company}:{j['id']}", j["text"], company.replace("-", " ").title(), loc,
                       j["hostedUrl"], j.get("descriptionPlain") or clean_html(j.get("description", "")),
                       str(j.get("createdAt", "")), looks_remote(loc, j.get("workplaceType", "")),
                       j.get("applyUrl", "")))
    return out


def fetch_remotive(keyword: str) -> list[Job]:
    data = _get("https://remotive.com/api/remote-jobs", search=keyword)
    return [Job("remotive", str(j["id"]), j["title"], j["company_name"],
                j.get("candidate_required_location", "Remote"), j["url"],
                clean_html(j.get("description", "")), j.get("publication_date", ""), True)
            for j in data.get("jobs", [])]


def fetch_adzuna(keyword: str, country: str = "us") -> list[Job]:
    app_id, app_key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        raise RuntimeError("ADZUNA_APP_ID / ADZUNA_APP_KEY not set")
    data = _get(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1", app_id=app_id, app_key=app_key,
                what=keyword, results_per_page=50, **{"content-type": "application/json"})
    return [Job("adzuna", str(j["id"]), j["title"], (j.get("company") or {}).get("display_name", ""),
                (j.get("location") or {}).get("display_name", ""), j["redirect_url"],
                clean_html(j.get("description", "")), j.get("created", ""),
                looks_remote(j.get("title", ""), j.get("description", "")))
            for j in data.get("results", [])]


def fetch_all(cfg: dict) -> tuple[list[Job], list[str]]:
    """Fetch from every enabled source. One failing source never stops the run."""
    src, kws = cfg["sources"], cfg["search"]["keywords"]
    jobs: list[Job] = []
    errors: list[str] = []
    tasks = [("greenhouse:" + t, lambda t=t: fetch_greenhouse(t)) for t in src.get("greenhouse", [])]
    tasks += [("lever:" + c, lambda c=c: fetch_lever(c)) for c in src.get("lever", [])]
    if src.get("remotive"):
        tasks += [("remotive:" + k, lambda k=k: fetch_remotive(k)) for k in kws]
    if src.get("adzuna"):
        tasks += [("adzuna:" + k, lambda k=k: fetch_adzuna(k, src.get("adzuna_country", "us"))) for k in kws]
    tasks += [(f"workday:{e.get('company', e['tenant'])}:{k}", lambda e=e, k=k: fetch_workday(e, k))
              for e in src.get("workday", []) for k in kws]
    alerts = src.get("email_alerts") or {}
    if alerts.get("enabled"):
        from .alerts import fetch_alert_emails

        try:
            alert_jobs, notes = fetch_alert_emails(alerts.get("days_back", 3))
            jobs += alert_jobs
            log.info("email alerts: %s", "; ".join(notes))
        except Exception as e:  # noqa: BLE001
            errors.append(f"email_alerts: {e}")
    for name, fn in tasks:
        try:
            jobs += fn()
        except Exception as e:  # noqa: BLE001
            log.warning("source %s failed: %s", name, e)
            errors.append(f"{name}: {e}")
    return jobs, errors
