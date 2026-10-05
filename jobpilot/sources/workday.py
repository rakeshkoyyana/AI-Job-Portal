"""Workday-hosted career sites (a large share of big-company jobs: pharma, banks, retail, ...).

Workday career sites load listings from a public JSON endpoint; this reads the same data a visitor's
browser does. Config entry (find the three values in the career-site URL
https://<host>/<locale>/<site>, tenant is the first label of the host):

  sources:
    workday:
      - {company: "Example Co", host: "example.wd5.myworkdayjobs.com", tenant: "example", site: "ExternalCareers"}

NOTE: written from Workday's public endpoint shape; verify against your target company first.
"""
from __future__ import annotations

import logging

import requests

from .base import Job, clean_html, looks_remote

log = logging.getLogger(__name__)
UA = {"User-Agent": "JobPilot/0.1 (personal job search tool)", "Content-Type": "application/json"}
DETAIL_CAP = 25      # detail pages fetched per keyword per run (be polite)


def fetch_workday(entry: dict, keyword: str) -> list[Job]:
    host, tenant, site = entry["host"], entry["tenant"], entry["site"]
    base = f"https://{host}/wday/cxs/{tenant}/{site}"
    r = requests.post(f"{base}/jobs", json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": keyword},
                      headers=UA, timeout=25)
    r.raise_for_status()
    out: list[Job] = []
    for p in r.json().get("jobPostings", [])[:DETAIL_CAP]:
        path = p.get("externalPath", "")
        try:
            d = requests.get(f"{base}{path}", headers=UA, timeout=25)
            d.raise_for_status()
            info = d.json().get("jobPostingInfo", {})
        except Exception as e:  # noqa: BLE001
            log.warning("workday detail failed %s: %s", path, e)
            continue
        loc = info.get("location") or p.get("locationsText", "")
        url = info.get("externalUrl") or f"https://{host}/en-US/{site}{path}"
        out.append(Job("workday", f"{tenant}:{info.get('jobReqId') or path}", info.get("title") or p.get("title", ""),
                       entry.get("company", tenant.title()), loc, url, clean_html(info.get("jobDescription", "")),
                       info.get("startDate", ""), looks_remote(loc, info.get("remoteType", ""), p.get("title", ""))))
    return out
