"""Resume tailoring + cover letters.

Two engines:
  * rule-based (always available): reorders skills/bullets by relevance to the JD and
    adds a "relevant strengths" line using ONLY skills already on the resume.
  * LLM (Anthropic API, optional): rewords bullets/summary in the JD's vocabulary.

Either way the output goes through verify_truthful(): any new skill, new number, or
changed role/date line makes us discard the LLM draft and fall back to rule-based.
We never invent experience.
"""
from __future__ import annotations

import copy
import logging
import os
import re
from dataclasses import dataclass, field

from .analyzer import Analysis, find_skills
from .resume_io import BULLET, Resume, parse_resume_text
from .sources.base import Job

log = logging.getLogger(__name__)

SUMMARY_TITLES = {"summary", "professional summary", "profile", "objective"}

SYSTEM = """You tailor resumes to job descriptions.
HARD RULES:
- Never invent or change employers, job titles, dates, degrees, certifications, metrics, numbers, tools, or skills that are not in the original resume.
- You may reorder bullets and skills, trim the least relevant bullets, and reword bullets or the summary to use the job's vocabulary ONLY where it truthfully describes the same work.
- Keep the exact markdown structure: '# Name', a contact line, '## SECTION' headings, '- ' bullets, role/date header lines unchanged.
- Output ONLY the resume markdown, nothing else."""


@dataclass
class TailorResult:
    resume: Resume
    engine: str                      # "llm" | "rules"
    issues: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- rules engine
def _reorder_skill_line(line: str, jd_skills: set[str]) -> str:
    prefix = "- " if line.startswith("- ") else ""
    body = line[2:] if prefix else line
    head, sep, rest = body.partition(":")
    if not sep:
        head, rest = "", body
    items = [x.strip() for x in rest.split(",") if x.strip()]
    if len(items) < 2:
        return line
    items.sort(key=lambda it: 0 if find_skills(it) & jd_skills else 1)  # stable
    return f"{prefix}{head + ': ' if sep else ''}{', '.join(items)}"


def _reorder_bullets(lines: list[str], jd_skills: set[str], cap: int) -> list[str]:
    out, group = [], []

    def flush():
        group.sort(key=lambda b: -len(find_skills(b) & jd_skills))
        out.extend(group[:cap])
        group.clear()

    for ln in lines:
        if BULLET.match(ln) or ln.startswith("- "):
            group.append(ln)
        else:
            flush()
            out.append(ln)
    flush()
    return out


def rule_based(resume: Resume, job: Job, analysis: Analysis, max_bullets: int = 7) -> Resume:
    new = copy.deepcopy(resume)
    jd = find_skills(f"{job.title}\n{job.description}")
    for sec in new.sections:
        t = sec.title.lower()
        if "skill" in t or "competenc" in t:
            sec.lines = [_reorder_skill_line(l, jd) for l in sec.lines]
        elif t in SUMMARY_TITLES and analysis.matched and sec.lines:
            top = ", ".join(analysis.matched[:6])
            sec.lines[-1] = sec.lines[-1].rstrip() + f" Relevant strengths for this role: {top}."
        elif "experience" in t or "project" in t:
            sec.lines = _reorder_bullets(sec.lines, jd, max_bullets)
    return new


# ------------------------------------------------------------------ guardrail
def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d[\d,.]*%?", text))


def verify_truthful(base: Resume, new: Resume) -> list[str]:
    issues = []
    extra = find_skills(new.text) - find_skills(base.text)
    if extra:
        issues.append(f"new skills not in original: {sorted(extra)}")
    nums = _numbers(new.text) - _numbers(base.text)
    if nums:
        issues.append(f"new numbers not in original: {sorted(nums)}")
    base_headers = {l.strip() for s in base.sections if "experience" in s.title.lower() or "education" in s.title.lower()
                    for l in s.lines if not l.startswith("- ")}
    new_lines = {l.strip() for s in new.sections for l in s.lines}
    lost = [h for h in base_headers if h not in new_lines]
    if lost:
        issues.append(f"role/education header lines changed or removed: {lost[:3]}")
    return issues


# ------------------------------------------------------------------ LLM engine
def _llm_client(cfg: dict):
    if not cfg["llm"].get("enabled") or not os.getenv("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic

        return anthropic.Anthropic()
    except ImportError:
        return None


def _llm_text(client, model: str, system: str, user: str, max_tokens: int = 3000) -> str:
    msg = client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                 messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()


def tailor_resume(resume: Resume, job: Job, analysis: Analysis, cfg: dict) -> TailorResult:
    cap = cfg["resume"].get("max_bullets_per_role", 7)
    fallback = rule_based(resume, job, analysis, cap)
    client = _llm_client(cfg)
    if client is None:
        return TailorResult(fallback, "rules")
    try:
        prompt = (f"JOB TITLE: {job.title}\nCOMPANY: {job.company}\n\nJOB DESCRIPTION:\n{job.description[:6000]}\n\n"
                  f"SKILLS TO EMPHASISE (already on resume): {', '.join(analysis.matched)}\n\n"
                  f"ORIGINAL RESUME:\n{resume.to_markdown()}")
        draft = parse_resume_text(_llm_text(client, cfg["llm"]["model"], SYSTEM, prompt))
        issues = verify_truthful(resume, draft)
        if issues:
            log.warning("LLM draft rejected: %s", issues)
            return TailorResult(fallback, "rules", ["LLM draft rejected -> " + "; ".join(issues)])
        return TailorResult(draft, "llm")
    except Exception as e:  # noqa: BLE001
        log.warning("LLM tailoring failed (%s); using rules", e)
        return TailorResult(fallback, "rules", [f"LLM error: {e}"])


# ---------------------------------------------------------------- cover letter
def cover_letter(resume: Resume, job: Job, analysis: Analysis, cfg: dict) -> str:
    client = _llm_client(cfg)
    if client is not None:
        try:
            sys_p = ("Write a concise, specific cover letter (max 220 words, 3 short paragraphs). "
                     "Use only facts present in the resume. No invented achievements, no clichés, no placeholders.")
            user = (f"JOB: {job.title} at {job.company}\n\n{job.description[:4000]}\n\nRESUME:\n{resume.to_markdown()}")
            text = _llm_text(client, cfg["llm"]["model"], sys_p, user, 700)
            if not (find_skills(text) - find_skills(resume.text)) and not (_numbers(text) - _numbers(resume.text)):
                return text
        except Exception as e:  # noqa: BLE001
            log.warning("LLM cover letter failed: %s", e)
    top = ", ".join(analysis.matched[:5]) or "data engineering"
    return (f"Dear Hiring Team at {job.company},\n\n"
            f"I'm applying for the {job.title} role. My background includes hands-on work with {top}, "
            f"which lines up closely with what your posting describes.\n\n"
            f"I'd welcome the chance to discuss how my experience can support your team. "
            f"My resume is attached for details.\n\nSincerely,\n{resume.name}")
