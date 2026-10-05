from __future__ import annotations

import html
import re
from dataclasses import dataclass


@dataclass
class Job:
    source: str
    external_id: str
    title: str
    company: str
    location: str
    url: str
    description: str
    posted_at: str = ""
    remote: bool = False
    apply_url: str = ""


def clean_html(raw: str) -> str:
    """HTML (possibly entity-escaped) -> readable plain text."""
    text = html.unescape(raw or "")
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def looks_remote(*parts: str) -> bool:
    return any("remote" in (p or "").lower() for p in parts)
