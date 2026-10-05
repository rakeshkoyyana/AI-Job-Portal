"""Local API used by the browser extension and the dashboard.   Run:  python -m jobpilot api

Binds to 127.0.0.1 only and requires the X-JobPilot-Token header (token is created on first run in
data/api_token.txt and pasted into the extension's options page). Your resumes, profile and API key stay on
your machine; the only outbound call is to the LLM provider, if you configure one.
"""
from __future__ import annotations

import base64
import re
import secrets
import tempfile
import time
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .analyzer import analyze, estimate_years
from .answers import answer_question, normalize
from .ats import match_probability
from .config import ROOT, data_dir, load_config
from .db import DB, now
from .engine import norm_terms, report_markdown, tailor as engine_tailor
from .resume_io import load_resume, parse_resume_text, render_docx, render_text_docx
from .sources.base import Job
from .tailor import _llm_client, cover_letter, tailor_resume

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class ResumeIn(BaseModel):
    id: str
    text: str

class MatchIn(BaseModel):
    title: str = ""
    description: str
    resumes: list[ResumeIn]
    years_experience: float = 5

class TailorIn(BaseModel):
    resume_text: str
    title: str = ""
    company: str = ""
    description: str
    with_cover_letter: bool = True
    years_experience: float = 5

class AnswerIn(BaseModel):
    question: str
    field_type: str = "text"
    options: list[str] | None = None
    profile: dict = Field(default_factory=dict)
    resume_text: str = ""
    job: dict = Field(default_factory=dict)

class AppIn(BaseModel):
    source: str                       # linkedin | indeed | career-site
    external_id: str
    title: str = ""
    company: str = ""
    location: str = ""
    url: str = ""
    description: str = ""
    status: str = "applied"           # applied | needs_review | skipped | failed
    notes: str = ""
    score: float | None = None
    resume_id: int | None = None

class JobMatchIn(BaseModel):
    platform: str = "career-site"
    job_key: str = ""
    url: str = ""
    title: str = ""
    company: str = ""
    location: str = ""
    description: str
    confirmed: list[str] = Field(default_factory=list)

class AnswerSaveIn(BaseModel):
    question: str
    answer: str


def get_token() -> str:
    f = data_dir() / "api_token.txt"
    if not f.exists():
        f.write_text(secrets.token_urlsafe(24))
        try:
            f.chmod(0o600)
        except OSError:
            pass
    return f.read_text().strip()


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:40] or "x"


def create_app(db_path: str | Path | None = None, token: str | None = None) -> FastAPI:
    app = FastAPI(title="JobPilot API", docs_url=None, redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origin_regex=r"chrome-extension://.*", allow_methods=["*"], allow_headers=["*"])
    db = DB(db_path or data_dir() / "jobpilot.db")
    secret = token or get_token()
    out_dir = (Path(db_path).parent if db_path else data_dir()) / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    def auth(x_jobpilot_token: str = Header(default="")):
        if not secrets.compare_digest(x_jobpilot_token, secret):
            raise HTTPException(401, "bad token")

    # ---------------------------------------------------------------- health / profile
    @app.get("/api/health", dependencies=[Depends(auth)])
    def health():
        return {"ok": True, "llm": _llm_client(load_config()) is not None}

    @app.get("/api/profile", dependencies=[Depends(auth)])
    def profile():
        cfg = load_config()
        return {"profile": cfg["profile"], "extension": cfg.get("extension", {}), "answers": cfg.get("answers", {})}

    # ---------------------------------------------------------------- resumes (multi-resume library)
    @app.post("/api/parse-resume", dependencies=[Depends(auth)])
    async def parse_resume(file: UploadFile = File(...)):
        suffix = Path(file.filename or "resume.txt").suffix.lower()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as t:
            t.write(await file.read())
        try:
            r = load_resume(t.name)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"cannot read resume: {e}")
        finally:
            Path(t.name).unlink(missing_ok=True)
        return {"name": r.name, "text": r.to_markdown()}

    @app.get("/api/resumes", dependencies=[Depends(auth)])
    def list_resumes():
        return [{"id": r["id"], "name": r["name"], "filename": r["filename"], "is_default": bool(r["is_default"])}
                for r in db.list_resumes()]

    @app.post("/api/resumes", dependencies=[Depends(auth)])
    async def add_resume(file: UploadFile = File(...), name: str = Form("")):
        suffix = Path(file.filename or "resume.docx").suffix.lower()
        if suffix not in {".docx", ".pdf", ".md", ".txt"}:
            raise HTTPException(400, "resume must be .docx, .pdf, .md or .txt")
        dest = out_dir.parent / "resumes" / f"{int(time.time())}_{_slug(file.filename or 'resume')}{suffix}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(await file.read())
        try:
            parsed = load_resume(dest)
        except Exception as e:  # noqa: BLE001
            dest.unlink(missing_ok=True)
            raise HTTPException(400, f"cannot read resume: {e}")
        rid = db.add_resume(name or Path(file.filename or "resume").stem, file.filename or dest.name, str(dest), parsed.to_markdown())
        return {"id": rid}

    @app.post("/api/resumes/{rid}/default", dependencies=[Depends(auth)])
    def default_resume(rid: int):
        if not db.get_resume(rid):
            raise HTTPException(404, "no such resume")
        db.set_default_resume(rid)
        return {"ok": True}

    @app.delete("/api/resumes/{rid}", dependencies=[Depends(auth)])
    def delete_resume(rid: int):
        db.delete_resume(rid)
        return {"ok": True}

    # ---------------------------------------------------------------- job match (the extension's main call)
    @app.post("/api/job-match", dependencies=[Depends(auth)])
    def job_match(body: JobMatchIn):
        """Pick the best stored resume for this job, rewrite it in its own format, and score it."""
        cfg = load_config()
        ext = cfg.get("extension", {})
        rows = db.list_resumes()
        candidates = []
        for r in rows:
            p = Path(r["path"] or "")
            if not p.exists():
                p = out_dir / f"_resume_{r['id']}.md"
                p.write_text(r["text"])
            candidates.append((r["id"], p, parse_resume_text(r["text"])))
        if not candidates:                                    # fall back to the resume in config.yaml
            base = Path(cfg["resume"]["base_path"])
            base = base if base.is_absolute() else ROOT / base
            if not base.exists():
                raise HTTPException(400, "no resume uploaded yet - add one in the dashboard or extension options")
            candidates.append((0, base, load_resume(base)))
        confirmed = norm_terms(body.confirmed)
        scored = [(match_probability(res, body.title, body.description, estimate_years(res.text), confirmed)["probability"], rid, path)
                  for rid, path, res in candidates]
        scored.sort(key=lambda x: -x[0])
        _, best_id, best_path = scored[0]
        stem = f"{_slug(body.company)}_{_slug(body.title)}_{int(time.time())}"
        out = engine_tailor(best_path, body.description, body.title, body.company, confirmed, cfg, out_path=out_dir / f"{stem}.docx")
        base_name = load_resume(best_path).name
        min_p = float(ext.get("min_probability", 0.3))
        apply_ok = out.match_after["probability"] >= min_p
        return {
            "apply": apply_ok,
            "reason": "" if apply_ok else f"match probability {out.match_after['probability']:.0%} is below your minimum {min_p:.0%}",
            "resume_id": best_id, "engine": out.engine,
            "ats_before": out.before.score, "ats_after": out.after.score,
            "probability": out.match_after["probability"], "label": out.match_after["label"],
            "missing": out.not_added, "added": out.added_skills, "warnings": out.warnings,
            "resume": {"filename": f"{_slug(base_name)}_Resume.docx", "mime": DOCX_MIME,
                       "b64": base64.b64encode(out.docx_path.read_bytes()).decode()},
        }

    # ---------------------------------------------------------------- full tailor report (dashboard / API users)
    @app.post("/api/tailor-file", dependencies=[Depends(auth)])
    async def tailor_file(file: UploadFile = File(...), description: str = Form(...), title: str = Form(""),
                          company: str = Form(""), confirmed: str = Form("")):
        suffix = Path(file.filename or "resume.docx").suffix.lower()
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / f"resume{suffix}"
            src.write_bytes(await file.read())
            try:
                out = engine_tailor(src, description, title, company, [c for c in confirmed.split(",") if c.strip()],
                                    load_config(), out_path=Path(d) / "tailored.docx")
            except Exception as e:  # noqa: BLE001
                raise HTTPException(400, f"cannot tailor: {e}")
            return {"ats_before": out.before.score, "ats_after": out.after.score,
                    "probability": out.match_after["probability"], "label": out.match_after["label"],
                    "report_markdown": report_markdown(out, title, company), "engine": out.engine,
                    "resume_docx_base64": base64.b64encode(out.docx_path.read_bytes()).decode()}

    # ---------------------------------------------------------------- legacy simple endpoints
    @app.post("/api/match", dependencies=[Depends(auth)])
    def match(body: MatchIn):
        """Score every resume against the job; return the best one and the skill gaps."""
        job = Job("ext", "tmp", body.title, "", "", "", body.description, remote=True)
        lenient = {"title_include": [], "title_exclude": [], "locations": [], "remote_ok": True}
        scored = []
        for r in body.resumes:
            a = analyze(job, parse_resume_text(r.text), lenient, body.years_experience)
            scored.append((a.score, r.id, a))
        if not scored:
            raise HTTPException(400, "no resumes")
        scored.sort(key=lambda x: -x[0])
        best = scored[0][2]
        return {"best_id": scored[0][1], "score": scored[0][0],
                "scores": [{"id": i, "score": s} for s, i, _ in scored],
                "matched": best.matched, "missing": best.missing, "required_years": best.required_years}

    @app.post("/api/tailor", dependencies=[Depends(auth)])
    def tailor(body: TailorIn):
        cfg = load_config()
        resume = parse_resume_text(body.resume_text)
        job = Job("ext", "tmp", body.title, body.company, "", "", body.description, remote=True)
        a = analyze(job, resume, {"title_include": [], "locations": []}, body.years_experience)
        res = tailor_resume(resume, job, a, cfg)
        with tempfile.TemporaryDirectory() as d:
            rp = render_docx(res.resume, Path(d) / "resume.docx")
            out = {"engine": res.engine, "issues": res.issues, "score": a.score, "matched": a.matched,
                   "resume_docx_base64": base64.b64encode(rp.read_bytes()).decode(),
                   "filename": f"{(body.company or 'job').replace(' ', '_')}_resume.docx"}
            if body.with_cover_letter:
                cp = render_text_docx(cover_letter(res.resume, job, a, cfg), Path(d) / "cover.docx")
                out["cover_docx_base64"] = base64.b64encode(cp.read_bytes()).decode()
        return out

    # ---------------------------------------------------------------- screening questions
    @app.post("/api/answer", dependencies=[Depends(auth)])
    def answer(body: AnswerIn):
        cfg, req = load_config(), body.model_dump()
        if not req.get("resume_text"):                       # ground answers in your default resume
            r = db.default_resume()
            if r:
                req["resume_text"] = r["text"]
        return answer_question(req, cfg, db)

    @app.get("/api/questions", dependencies=[Depends(auth)])
    def questions(unanswered: bool = False):
        return [{k: r[k] for k in ("id", "normalized", "question", "field_type", "options", "answer", "source", "times_seen")}
                for r in db.list_questions(unanswered)]

    @app.post("/api/questions/answer", dependencies=[Depends(auth)])
    def save_answer(body: AnswerSaveIn):
        norm = normalize(body.question)
        db.see_question(norm, body.question, "text", "[]")
        db.save_answer(norm, body.answer, "user")
        return {"ok": True}

    # ---------------------------------------------------------------- tracker
    @app.get("/api/applications/status", dependencies=[Depends(auth)])
    def application_status(platform: str, job_key: str):
        return {"status": db.application_status(platform, job_key)}

    @app.post("/api/applications", dependencies=[Depends(auth)])
    def log_application(body: AppIn):
        fields = dict(title=body.title, company=body.company, location=body.location, url=body.url,
                      status=body.status, notes=body.notes, match_score=body.score, resume_id=body.resume_id)
        return {"id": db.log_application(body.source, body.external_id, **fields)}

    @app.get("/api/applications", dependencies=[Depends(auth)])
    def list_applications(limit: int = 200, status: str | None = None):
        return [{"id": r["id"], "source": r["platform"], "title": r["title"], "company": r["company"], "location": r["location"],
                 "url": r["url"], "status": r["status"], "notes": r["notes"], "score": r["match_score"],
                 "applied_at": r["updated_at"] if r["status"] == "applied" else None}
                for r in db.list_applications(status, limit)]

    @app.get("/api/stats", dependencies=[Depends(auth)])
    def stats():
        by_status = {r["status"]: r["c"] for r in db.conn.execute("SELECT status, COUNT(*) c FROM applications GROUP BY status")}
        by_platform = db.applied_today_by_platform()
        return {"applied_today": sum(by_platform.values()), "applied_today_by_platform": by_platform, "by_status": by_status}

    return app


def main(host: str = "127.0.0.1", port: int = 8765):
    import uvicorn

    print(f"JobPilot API on http://{host}:{port}\nExtension token: {get_token()}")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
