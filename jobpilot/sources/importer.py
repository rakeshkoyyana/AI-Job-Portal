"""Import a single job from any company career-site URL.

Almost every career site (Workday, iCIMS, SmartRecruiters, Taleo, custom sites ...) embeds a
schema.org `JobPosting` JSON-LD block because Google for Jobs requires it. We read that, so one
importer covers most employers. Falls back to the page's visible text.

LinkedIn / Indeed / Glassdoor / Handshake URLs are refused on purpose (their terms forbid
automated fetching, and the pages are login-walled anyway): paste the description instead.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import requests

from .base import Job, clean_html, looks_remote

BLOCKED = ("linkedin.com", "indeed.com", "glassdoor.com", "joinhandshake.com")
UA = {"User-Agent": "Mozilla/5.0 (compatible; JobPilot/0.1; personal use)"}
LD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)


def is_portal(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(host == d or host.endswith("." + d) for d in BLOCKED)


def _find_posting(node):
    if isinstance(node, list):
        for n in node:
            r = _find_posting(n)
            if r:
                return r
    elif isinstance(node, dict):
        t = node.get("@type")
        if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
            return node
        return _find_posting(node.get("@graph", []))
    return None


def _location(p: dict) -> str:
    loc = p.get("jobLocation")
    locs = loc if isinstance(loc, list) else [loc] if loc else []
    parts = []
    for l in locs:
        a = (l or {}).get("address", {}) or {}
        if isinstance(a, dict):
            parts.append(", ".join(x for x in (a.get("addressLocality"), a.get("addressRegion"), a.get("addressCountry") if isinstance(a.get("addressCountry"), str) else "") if x))
    return " | ".join(x for x in parts if x)


def parse_job_page(url: str, html_text: str) -> Job:
    posting = None
    for block in LD.findall(html_text):
        try:
            posting = _find_posting(json.loads(block.strip()))
        except ValueError:
            continue
        if posting:
            break
    if posting:
        org = posting.get("hiringOrganization") or {}
        company = org.get("name", "") if isinstance(org, dict) else str(org)
        loc = _location(posting)
        remote = posting.get("jobLocationType") == "TELECOMMUTE" or looks_remote(loc, posting.get("title", ""))
        return Job("import", url, posting.get("title", "").strip(), company, loc, url,
                   clean_html(posting.get("description", "")), str(posting.get("datePosted", "")), remote)
    # fallback: visible text
    title = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.S | re.I)
    body = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", html_text)
    return Job("import", url, clean_html(title.group(1)) if title else "Imported role", urlparse(url).netloc,
               "", url, clean_html(body)[:12000], "", False)


def import_url(url: str) -> Job:
    if is_portal(url):
        raise ValueError("LinkedIn/Indeed/Glassdoor/Handshake pages can't be fetched automatically - "
                         "open the job, copy the description, and use 'Paste job description' instead.")
    r = requests.get(url, headers=UA, timeout=25)
    r.raise_for_status()
    return parse_job_page(url, r.text)
