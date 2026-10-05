"""Ingest jobs from the job-alert emails LinkedIn / Indeed / Glassdoor / Handshake send you.

You create saved searches + email alerts on each site (their supported feature); this module
reads those emails from your inbox over IMAP and turns each job link into a row. Nothing here
touches the sites themselves, so there is no scraping, no login and no ban risk.

Alert emails carry title / company / location but not the full description. Those jobs get
status `needs_jd`: open the link, paste the description into the dashboard, and the normal
score -> tailor flow runs. (Layouts change; the parser is best-effort and tested on samples.)

Env (.env):  IMAP_USER, IMAP_PASSWORD (use an app password), IMAP_HOST (default imap.gmail.com)
"""
from __future__ import annotations

import datetime as dt
import email
import imaplib
import os
import re
from email.header import decode_header, make_header
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

from .base import Job, looks_remote

SENDER_DOMAINS = {
    "linkedin.com": "linkedin",
    "indeed.com": "indeed",
    "glassdoor.com": "glassdoor",
    "joinhandshake.com": "handshake",
}


class _Tokens(HTMLParser):
    """Flatten an email's HTML into a stream of ('a', href, text) and ('t', text) tokens."""

    def __init__(self):
        super().__init__()
        self.tokens: list[tuple] = []
        self._href: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._buf = []

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.tokens.append(("a", self._href, " ".join(self._buf).strip()))
            self._href = None

    def handle_data(self, data):
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        if self._href is not None:
            self._buf.append(text)
        else:
            self.tokens.append(("t", text))


def canonical(source: str, href: str) -> tuple[str, str] | None:
    """Return (external_id, clean_url) if href is a job link for this source."""
    u = urlparse(href)
    path, qs = u.path, parse_qs(u.query)
    if source == "linkedin":
        m = re.search(r"/jobs/view/(?:[^/?]*-)?(\d{6,})", path)
        return (m.group(1), f"https://www.linkedin.com/jobs/view/{m.group(1)}") if m else None
    if source == "indeed":
        jk = (qs.get("jk") or qs.get("vjk") or [None])[0]
        return (jk, f"https://www.indeed.com/viewjob?jk={jk}") if jk else None
    if source == "glassdoor":
        if "job-listing" in path or "partner/jobListing" in path:
            jl = (qs.get("jl") or [None])[0]
            ident = jl or re.sub(r"\W+", "-", path).strip("-")[-60:]
            return ident, (f"https://www.glassdoor.com/job-listing/j?jl={jl}" if jl else f"{u.scheme}://{u.netloc}{path}")
    if source == "handshake":
        m = re.search(r"/(?:stu/)?jobs/(\d+)", path)
        return (m.group(1), f"https://app.joinhandshake.com/jobs/{m.group(1)}") if m else None
    return None


def parse_alert_html(source: str, html_body: str) -> list[Job]:
    p = _Tokens()
    p.feed(html_body)
    jobs: dict[str, Job] = {}
    toks = p.tokens
    for i, tok in enumerate(toks):
        if tok[0] != "a" or len(tok[2]) < 4:
            continue
        c = canonical(source, tok[1])
        if not c or c[0] in jobs:
            continue
        ext_id, url = c
        following = [t[1] for t in toks[i + 1:i + 6] if t[0] == "t" and not re.match(r"(?i)(apply|view job|easy apply|new|promoted)", t[1])]
        company = following[0] if following else ""
        location = following[1] if len(following) > 1 else ""
        jobs[ext_id] = Job(source, ext_id, tok[2], company, location, url, "", "", looks_remote(location, tok[2]))
    return list(jobs.values())


def _html_part(msg: email.message.Message) -> str:
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            payload = part.get_payload(decode=True) or b""
            return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    return ""


def fetch_alert_emails(days_back: int = 3) -> tuple[list[Job], list[str]]:
    user, pw = os.getenv("IMAP_USER"), os.getenv("IMAP_PASSWORD")
    if not (user and pw):
        raise RuntimeError("IMAP_USER / IMAP_PASSWORD not set in .env")
    since = (dt.date.today() - dt.timedelta(days=days_back)).strftime("%d-%b-%Y")
    jobs: list[Job] = []
    notes: list[str] = []
    imap = imaplib.IMAP4_SSL(os.getenv("IMAP_HOST", "imap.gmail.com"))
    try:
        imap.login(user, pw)
        imap.select("INBOX", readonly=True)       # read-only: never modifies your mailbox
        for domain, source in SENDER_DOMAINS.items():
            _, data = imap.search(None, f'(FROM "{domain}" SINCE {since})')
            ids = (data[0] or b"").split()
            found = 0
            for mid in ids:
                _, msg_data = imap.fetch(mid, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])
                body = _html_part(msg)
                if body:
                    parsed = parse_alert_html(source, body)
                    found += len(parsed)
                    jobs += parsed
            notes.append(f"{source}: {len(ids)} emails, {found} job links")
    finally:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001
            pass
    return jobs, notes
