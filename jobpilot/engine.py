"""Resume + job description in -> tailored resume (same format) + ATS score + match probability + interview prep out."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .analyzer import ALIASES, estimate_years, find_skills, has_term, jd_requirements, supported_skills
from .ats import ATSReport, ats_score, interview_prep, match_probability, suggestions
from .docx_rewrite import (apply_docx_edits, display, docx_has_table_text, paras_from_docx, paras_from_resume,
                           plan_llm_edits, plan_rule_edits, resume_from_paras, verify_edits)
from .resume_io import Resume, load_resume, render_docx
from .tailor import _llm_client

log = logging.getLogger(__name__)


@dataclass
class TailorOutput:
    docx_path: Path
    engine: str                              # "llm" | "rules"
    before: ATSReport
    after: ATSReport
    match_before: dict
    match_after: dict
    added_skills: list[str]
    not_added: list[str]                     # required skills missing from the resume and NOT confirmed by the user
    changes: list[tuple[str, str]]           # (before, after) paragraph text
    prep: dict
    suggestions: list[str]
    warnings: list[str] = field(default_factory=list)


def norm_terms(terms) -> set[str]:
    out = set()
    for t in terms or []:
        t = t.strip().lower()
        out.add(ALIASES.get(t, t))
    return out


def _literal(text: str, term: str) -> bool:
    return re.search(rf"(?<![\w+#.]){re.escape(term)}(?![\w+#])", text, re.I) is not None


def tailor(resume_path: str | Path, jd_text: str, title: str = "", company: str = "", confirmed=None,
           cfg: dict | None = None, out_path: str | Path | None = None, years: float | None = None) -> TailorOutput:
    cfg = cfg or {"llm": {"enabled": False, "model": ""}}
    src = Path(resume_path)
    confirmed = norm_terms(confirmed)
    base = load_resume(src)
    is_docx = src.suffix.lower() == ".docx"
    warnings: list[str] = []

    req, pref = jd_requirements(jd_text)
    wanted = req | pref
    text0 = base.text
    # terms to ADD to the skills section: evidenced by the resume (implied) or personally confirmed
    add_terms = sorted(t for t in wanted if not _literal(text0, t) and (t in supported_skills(text0) or t in confirmed))
    jd_terms = wanted | confirmed
    before = ats_score(base, title, jd_text, docx_path=src if is_docx else None)
    matched = sorted(t for t in req if has_term(text0, t))      # on the resume, literally or by implication

    paras = paras_from_docx(src) if is_docx else paras_from_resume(base)
    if is_docx and docx_has_table_text(src):
        warnings.append("Your resume uses tables; text inside tables is left unchanged (ATS parsers also struggle with tables).")
    allowed = supported_skills(text0) | confirmed
    edits = plan_rule_edits(paras, jd_terms, matched, add_terms)
    engine = "rules"

    client = _llm_client(cfg)
    if client is not None:
        try:
            llm_edits = plan_llm_edits(client, cfg["llm"]["model"], paras, jd_text, title, [display(t) for t in add_terms], matched)
            problems = verify_edits(paras, llm_edits, allowed)
            if problems:
                warnings.append("AI draft rejected by the truthfulness check, used safe edits instead: " + "; ".join(problems[:3]))
            else:
                edits, engine = {**edits, **llm_edits}, "llm"
        except Exception as e:  # noqa: BLE001
            warnings.append(f"AI rewrite unavailable ({e.__class__.__name__}); used safe edits.")

    problems = verify_edits(paras, edits, allowed)
    if problems:                                  # the rules engine must pass its own guardrail too
        raise RuntimeError("internal guardrail failure: " + "; ".join(problems[:3]))

    dst = Path(out_path or src.with_name(src.stem + "_tailored.docx"))
    if is_docx:
        apply_docx_edits(src, dst, edits)
        after_resume = load_resume(dst)
    else:
        after_resume = resume_from_paras(base, paras, edits)
        render_docx(after_resume, dst)
        warnings.append("Original format can't be preserved from a PDF/text file; rendered a clean ATS-friendly layout. "
                        "Upload your .docx to keep your exact formatting.")

    after = ats_score(after_resume, title, jd_text, docx_path=dst)
    yrs = years if years is not None else estimate_years(text0)
    prob_b = match_probability(base, title, jd_text, yrs)
    prob_a = match_probability(after_resume, title, jd_text, yrs, confirmed)
    by_idx = {p.idx: p.text for p in paras}
    changes = [(by_idx[i], t) for i, t in sorted(edits.items()) if by_idx.get(i, "") != t]
    not_added = sorted(t for t in req if not has_term(text0, t) and t not in confirmed)
    return TailorOutput(dst, engine, before, after, prob_b, prob_a, [display(t) for t in add_terms], not_added, changes,
                        interview_prep(after_resume, title, jd_text, confirmed), suggestions(after, prob_a), warnings)


def report_markdown(o: TailorOutput, title: str = "", company: str = "") -> str:
    L = [f"# Resume report: {title} @ {company}".strip(), ""]
    L += [f"**ATS score:** {o.before.score:.0f} -> **{o.after.score:.0f}** / 100",
          f"**Match probability:** {o.match_before['probability']:.0%} -> **{o.match_after['probability']:.0%}** ({o.match_after['label']})",
          "_Heuristic estimate of recruiter-response likelihood, not a guarantee._", ""]
    L += ["## ATS breakdown (after)"] + [f"- {k}: {p:g}/{m}" for k, (p, m) in o.after.breakdown.items()] + [""]
    L += ["## Keywords", f"- Matched required: {', '.join(o.after.matched_required) or '-'}",
          f"- Added to your skills section: {', '.join(o.added_skills) or '-'}",
          f"- Required but NOT on your resume (not added): {', '.join(o.not_added) or '-'}", ""]
    L += ["## Suggestions"] + [f"- {s}" for s in o.suggestions] + [""]
    L += ["## Interview prep", "**Likely technical questions**"]
    L += [f"- ({q['topic']}) {q['question']}" for q in o.prep["likely_questions"]]
    L += ["", "**Gaps to prepare for**"] + [f"- {g['topic']}: {g['plan']}" for g in o.prep["gap_study_plan"]]
    L += ["", "**Behavioral**"] + [f"- {b}" for b in o.prep["behavioral"]]
    L += ["", "**Stories from your own resume**"] + [f"- {a}" for a in o.prep["story_anchors_from_your_resume"]]
    L += ["", "**Ask them**"] + [f"- {a}" for a in o.prep["questions_to_ask_them"]]
    if o.warnings:
        L += ["", "## Notes"] + [f"- {w}" for w in o.warnings]
    return "\n".join(L) + "\n"
