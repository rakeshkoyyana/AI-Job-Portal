"""The daily run: fetch -> filter -> score -> tailor -> (optionally) apply, capped per day."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from . import applier
from .analyzer import analyze, job_from_row, passes_filters
from .config import ROOT, data_dir
from .db import DB, now
from .resume_io import load_resume, render_docx, render_text_docx
from .sources import fetch_all
from .tailor import cover_letter, tailor_resume

log = logging.getLogger(__name__)
MIN_JD_CHARS = 200


def _slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()[:40]


def base_resume(cfg: dict):
    p = Path(cfg["resume"]["base_path"])
    return load_resume(p if p.is_absolute() else ROOT / p)


def score_new_jobs(db: DB, cfg: dict, resume) -> int:
    n = 0
    for row in db.list_jobs("new", limit=100000, order="id"):
        job = job_from_row(row)
        if len((job.description or "").strip()) < MIN_JD_CHARS:
            # e.g. LinkedIn/Indeed alert emails: no description yet. Can't score or tailor honestly.
            ok, why = passes_filters(job, cfg["search"])
            db.update(row["id"], status="needs_jd" if ok else "filtered",
                      notes="paste the job description to score & tailor" if ok else f"filtered: {why}")
            n += 1
            continue
        a = analyze(job, resume, cfg["search"], cfg["profile"].get("years_experience", 5))
        status = "scored" if (a.eligible and a.score >= cfg["search"]["min_score"]) else "filtered"
        db.update(row["id"], score=a.score, matched=", ".join(a.matched), missing=", ".join(a.missing),
                  notes="; ".join(a.reasons), status=status)
        n += 1
    return n


def _keep_user_choice(db: DB, job_id: int) -> None:
    """A job the user added/pasted themselves must not be silently dropped by title/score filters."""
    row = db.get(job_id)
    if row["status"] == "filtered" and len(row["description"] or "") >= MIN_JD_CHARS:
        db.update(job_id, status="scored", notes=f"{row['notes'] or ''}; kept because you added it".strip("; "))


def add_job(db: DB, cfg: dict, job) -> int:
    """Insert a manually added / imported job, score it, and return its id."""
    db.upsert_job(job)
    jid = db.find_id(job.source, job.external_id)
    score_new_jobs(db, cfg, base_resume(cfg))
    _keep_user_choice(db, jid)
    return jid


def set_description(db: DB, cfg: dict, job_id: int, text: str) -> None:
    """Attach a pasted job description to a needs_jd job and (re)score it."""
    db.update(job_id, description=text.strip(), status="new")
    score_new_jobs(db, cfg, base_resume(cfg))
    _keep_user_choice(db, job_id)


def prepare_job(db: DB, cfg: dict, resume, job_id: int) -> dict:
    """Tailor resume + cover letter for one job and save files. Returns paths + engine info."""
    row = db.get(job_id)
    job = job_from_row(row)
    a = analyze(job, resume, cfg["search"], cfg["profile"].get("years_experience", 5))
    res = tailor_resume(resume, job, a, cfg)
    letter = cover_letter(res.resume, job, a, cfg)
    stem = f"{job_id:05d}_{_slug(job.company)}_{_slug(job.title)}"
    out = data_dir() / "out"
    rpath = render_docx(res.resume, out / f"{stem}_resume.docx")
    cpath = render_text_docx(letter, out / f"{stem}_cover.docx")
    note = f"{row['notes'] or ''}; tailored via {res.engine}" + (f" ({'; '.join(res.issues)})" if res.issues else "")
    db.update(job_id, resume_path=str(rpath), cover_path=str(cpath), notes=note)
    return {"resume": rpath, "cover": cpath, "engine": res.engine, "issues": res.issues}


def run_daily(cfg: dict, db: DB, fetch: bool = True) -> dict:
    started = now()
    if db.get_setting("landed") == "1":
        log.info("Marked as landed - nothing to do. Congratulations!")
        return {"skipped": "landed"}

    resume = base_resume(cfg)
    fetched, new_jobs, errors = 0, 0, []
    if fetch:
        jobs, errors = fetch_all(cfg)
        fetched = len(jobs)
        new_jobs = sum(db.upsert_job(j) for j in jobs)
    score_new_jobs(db, cfg, resume)

    remaining = max(0, cfg["apply"]["daily_limit"] - db.processed_today())
    queue = db.list_jobs("scored", limit=remaining, order="score DESC") if remaining else []
    prepared = applied = 0
    for row in queue:
        try:
            info = prepare_job(db, cfg, resume, row["id"])
            db.update(row["id"], status="ready", processed_at=now())
            prepared += 1
            if cfg["apply"]["mode"] == "auto":
                r = applier.apply_auto(row["url"], row["apply_url"], cfg["profile"], cfg["answers"],
                                       str(info["resume"]), str(info["cover"]), cfg["apply"].get("headless", True))
                note = f"{db.get(row['id'])['notes']}; apply: {r.message} {r.unresolved or ''}".strip()
                db.update(row["id"], status=r.status if r.status != "unsupported" else "needs_review", notes=note,
                          applied_at=now() if r.status == "applied" else None)
                applied += r.status == "applied"
        except Exception as e:  # noqa: BLE001
            log.exception("job %s failed", row["id"])
            db.update(row["id"], status="failed", notes=f"error: {e}")
            errors.append(f"job {row['id']}: {e}")

    stats = dict(started_at=started, finished_at=now(), fetched=fetched, new_jobs=new_jobs,
                 prepared=prepared, applied=applied, errors="\n".join(errors))
    db.log_run(**stats)
    return stats
