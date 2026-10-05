"""Answers for application screening questions.

Order of authority (first hit wins):
  1. Question bank   - answers YOU saved (dashboard) or approved; always trusted, even for sensitive topics.
  2. config `answers`- regex -> answer rules in config.yaml.
  3. Sensitive guard - EEO / salary / legal-status style questions are never guessed by the model.
  4. LLM             - only from facts in your profile + resume, then validated (options must match,
                       numbers and skills must already exist in the facts).
If nothing qualifies we return answer=None and the extension flags the question for a human instead of guessing.
Every unanswered question is recorded in the bank so you can answer it once and never be asked again.
"""
from __future__ import annotations

import json
import re

from .analyzer import find_skills
from .tailor import _llm_client, _llm_text, _numbers

SENSITIVE = re.compile(
    r"(?i)gender|race|ethnic|veteran|disabilit|sexual|pronoun|criminal|convict|felony|salary|compensation|"
    r"pay expect|date of birth|\bssn\b|social security|citizenship|visa|religio|hispanic|lgbt"
)

SYSTEM = """You answer job-application questions on behalf of a candidate.
Use ONLY facts found in PROFILE and RESUME. If the facts do not support an answer, reply exactly: UNKNOWN
- Yes/No questions: reply exactly Yes or No.
- Multiple choice: reply with exactly one of the given options, copied verbatim.
- Numeric questions (years of experience, salary): reply with only a number, and only if the facts state it.
- Free text: first person, specific, under 80 words, no filler, no invented achievements.
Never claim a skill, employer, degree, certification, or number that is not in the facts."""


def normalize(q: str) -> str:
    q = re.sub(r"\(?\brequired\b\)?|\*", " ", q.lower())
    q = re.sub(r"[^a-z0-9 ]+", " ", q)
    return re.sub(r"\s+", " ", q).strip()


def pick_option(answer: str, options: list[str]) -> str | None:
    a = answer.strip().strip('"').strip().lower()
    if not a:
        return None
    low = {o.strip().lower(): o for o in options}
    if a in low:
        return low[a]
    for k, o in low.items():           # tolerate "Yes, I am" vs option "Yes"
        if a.startswith(k) or k.startswith(a):
            return o
    for k, o in low.items():
        if a in k or k in a:
            return o
    return None


def validate(answer: str | None, options: list[str] | None, facts: str) -> str | None:
    if answer is None:
        return None
    a = answer.strip().strip('"').strip()
    if not a or a.upper().startswith("UNKNOWN"):
        return None
    if options:
        low = {o.strip().lower(): o for o in options}
        if a.lower() in low:
            return low[a.lower()]
        for k, o in low.items():
            if a.lower().startswith(k) or k.startswith(a.lower()):
                return o
        return None
    if _numbers(a) - _numbers(facts):
        return None
    if find_skills(a) - find_skills(facts):
        return None
    return a


def answer_question(req: dict, cfg: dict, db=None) -> dict:
    q = (req.get("question") or "").strip()
    options = [str(o) for o in (req.get("options") or [])]
    if not q:
        return {"answer": None, "reason": "empty_question"}
    norm = normalize(q)

    # 1) question bank
    if db is not None:
        row = db.get_question(norm)
        if row and row["answer"]:
            ans = pick_option(row["answer"], options) if options else row["answer"]
            if ans:
                db.see_question(norm, q, req.get("field_type", "text"), json.dumps(options))
                return {"answer": ans, "reason": "bank"}
    # 2) config rules
    for pattern, ans in (cfg.get("answers") or {}).items():
        if ans and re.search(pattern, q):
            picked = pick_option(str(ans), options) if options else str(ans)
            if picked:
                return {"answer": picked, "reason": "config"}

    def unanswered(reason: str) -> dict:
        if db is not None:
            db.see_question(norm, q, req.get("field_type", "text"), json.dumps(options))
        return {"answer": None, "reason": reason}

    # 3) sensitive guard
    if SENSITIVE.search(q):
        return unanswered("sensitive")
    # 4) LLM, validated
    client = _llm_client(cfg)
    if client is None:
        return unanswered("llm_unavailable")
    profile = json.dumps(req.get("profile") or cfg.get("profile") or {}, indent=1)
    resume = req.get("resume_text") or ""
    facts = f"{profile}\n{resume}"
    job = req.get("job") or {}
    user = (f"PROFILE:\n{profile}\n\nRESUME:\n{resume[:6000]}\n\n"
            f"JOB: {job.get('title', '')} at {job.get('company', '')}\n{(job.get('description') or '')[:2500]}\n\n"
            f"QUESTION: {q}\nFIELD TYPE: {req.get('field_type', 'text')}\n"
            + (f"OPTIONS: {json.dumps(options)}\n" if options else ""))
    try:
        raw = _llm_text(client, cfg["llm"]["model"], SYSTEM, user, 400)
    except Exception as e:  # noqa: BLE001
        return unanswered(f"llm_error: {e.__class__.__name__}")
    ans = validate(re.sub(r"\s+", " ", raw), options or None, facts)
    if ans is None:
        return unanswered("unknown_or_unsupported")
    return {"answer": ans, "reason": "llm"}
