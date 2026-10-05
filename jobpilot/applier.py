"""Application submission.

Modes (config apply.mode):
  prepare : tailor + save materials, job goes to the dashboard queue ("ready"). You click Apply.
  auto    : additionally try to fill + submit Greenhouse / Lever forms with Playwright.
            Anything unusual (captcha, unanswered required question, no success page) is NOT
            submitted; the job is marked 'needs_review' instead.

We do not bypass captchas or log in to LinkedIn/Indeed.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger(__name__)

SUCCESS = re.compile(r"thank you for (applying|your application)|application (has been )?(submitted|received)|successfully submitted", re.I)
CAPTCHA_SEL = 'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], .g-recaptcha, .h-captcha'


@dataclass
class ApplyResult:
    status: str                       # applied | needs_review | failed | unsupported
    message: str = ""
    unresolved: list[str] = field(default_factory=list)


def platform(url: str) -> str | None:
    host = urlparse(url).netloc.lower()
    if "greenhouse.io" in host:
        return "greenhouse"
    if "lever.co" in host:
        return "lever"
    return None


def _split_name(full: str) -> tuple[str, str]:
    parts = full.split()
    return (parts[0], " ".join(parts[1:])) if parts else ("", "")


def _try_fill(page, selectors: list[str], value: str) -> bool:
    if not value:
        return False
    for sel in selectors:
        loc = page.locator(sel).first
        if loc.count():
            loc.fill(value)
            return True
    return False


def _answer_for(label: str, answers: dict) -> str | None:
    for pattern, ans in answers.items():
        if ans and re.search(pattern, label):
            return ans
    return None


def _fill_required_questions(page, answers: dict) -> list[str]:
    """Fill required fields we know answers for; return labels we couldn't resolve."""
    unresolved = []
    fields = page.locator("input[required]:not([type=file]):not([type=hidden]), textarea[required], select[required], [aria-required=true]")
    for i in range(fields.count()):
        el = fields.nth(i)
        try:
            if not el.is_visible():
                continue
            tag = el.evaluate("e => e.tagName.toLowerCase()")
            typ = el.get_attribute("type") or ""
            current = el.input_value() if tag in {"input", "textarea", "select"} and typ not in {"checkbox", "radio"} else ""
            if current:
                continue
            label = el.evaluate(
                "e => (e.labels && e.labels[0] ? e.labels[0].innerText : (e.getAttribute('aria-label') || e.name || e.id || ''))"
            ) or ""
            ans = _answer_for(label, answers)
            if ans is None or typ in {"checkbox", "radio"}:
                unresolved.append(label.strip()[:80] or f"field #{i}")
            elif tag == "select":
                el.select_option(label=ans)
            else:
                el.fill(ans)
        except Exception as e:  # noqa: BLE001
            unresolved.append(f"field #{i} ({e.__class__.__name__})")
    return unresolved


def apply_auto(url: str, apply_url: str, profile: dict, answers: dict, resume_path: str,
               cover_path: str | None, headless: bool = True) -> ApplyResult:
    plat = platform(apply_url or url)
    if plat is None:
        return ApplyResult("needs_review", "Not a Greenhouse/Lever form - apply manually from the dashboard.")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return ApplyResult("failed", "Playwright not installed (pip install playwright && playwright install chromium)")

    target = apply_url or url
    if plat == "lever" and not target.rstrip("/").endswith("/apply"):
        target = target.rstrip("/") + "/apply"
    first, last = _split_name(profile.get("full_name", ""))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            page.goto(target, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1500)
            if page.locator(CAPTCHA_SEL).count():
                return ApplyResult("needs_review", "Captcha present - open the link and finish manually.")

            if plat == "greenhouse":
                _try_fill(page, ["#first_name", "input[name='first_name']"], first)
                _try_fill(page, ["#last_name", "input[name='last_name']"], last)
                _try_fill(page, ["#email", "input[name='email']"], profile.get("email", ""))
                _try_fill(page, ["#phone", "input[name='phone']"], profile.get("phone", ""))
            else:
                _try_fill(page, ["input[name='name']"], profile.get("full_name", ""))
                _try_fill(page, ["input[name='email']"], profile.get("email", ""))
                _try_fill(page, ["input[name='phone']"], profile.get("phone", ""))
                _try_fill(page, ["input[name='urls[LinkedIn]']"], profile.get("linkedin", ""))
                _try_fill(page, ["input[name='urls[GitHub]']"], profile.get("github", ""))
                _try_fill(page, ["input[name='location']"], profile.get("location", ""))

            files = page.locator("input[type=file]")
            if files.count():
                files.first.set_input_files(str(resume_path))
                if cover_path and files.count() > 1:
                    files.nth(1).set_input_files(str(cover_path))
            else:
                return ApplyResult("needs_review", "No resume upload field found.")

            unresolved = _fill_required_questions(page, answers)
            if unresolved:
                return ApplyResult("needs_review", "Required questions need your answer.", unresolved)
            if page.locator(CAPTCHA_SEL).count():
                return ApplyResult("needs_review", "Captcha appeared - finish manually.")

            btn = page.locator("button[type=submit], input[type=submit], button:has-text('Submit')").first
            if not btn.count():
                return ApplyResult("needs_review", "Submit button not found.")
            btn.click()
            page.wait_for_timeout(4000)
            if SUCCESS.search(page.inner_text("body")):
                return ApplyResult("applied", "Submitted.")
            return ApplyResult("needs_review", "Clicked submit but no confirmation page detected - verify manually.")
        except Exception as e:  # noqa: BLE001
            log.exception("auto apply failed")
            return ApplyResult("failed", f"{e.__class__.__name__}: {e}")
        finally:
            browser.close()


PORTALS = ("linkedin.com", "indeed.com", "glassdoor.com", "joinhandshake.com")


def assist_one(url: str, apply_url: str, profile: dict, resume_path: str) -> None:
    """Open a VISIBLE browser, pre-fill the basics and hand control to you to review & submit.

    On LinkedIn / Indeed / Glassdoor / Handshake we only OPEN the page (and show you the files):
    no form filling or clicking there, so those accounts never see automation.
    """
    import webbrowser

    from playwright.sync_api import sync_playwright

    target = apply_url or url
    if any(d in urlparse(target).netloc.lower() for d in PORTALS):
        print(f"Opening {target}\nUpload this tailored resume yourself: {resume_path}")
        webbrowser.open(target)
        return
    if platform(target) == "lever" and not target.rstrip("/").endswith("/apply"):
        target = target.rstrip("/") + "/apply"
    first, last = _split_name(profile.get("full_name", ""))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(target, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        for sels, val in [(["#first_name", "input[name='first_name']"], first), (["#last_name", "input[name='last_name']"], last),
                          (["#email", "input[name='email']"], profile.get("email", "")),
                          (["#phone", "input[name='phone']"], profile.get("phone", "")),
                          (["input[name='name']"], profile.get("full_name", ""))]:
            _try_fill(page, sels, val)
        files = page.locator("input[type=file]")
        if files.count() and Path(resume_path).exists():
            files.first.set_input_files(str(resume_path))
        input("Review the form in the browser, submit it yourself, then press Enter here... ")
        browser.close()
