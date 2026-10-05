from pathlib import Path

import pytest

from jobpilot import pipeline
from jobpilot.analyzer import analyze, find_skills, passes_filters
from jobpilot.db import DB
from jobpilot.resume_io import load_resume, parse_resume_text
from jobpilot.sources.base import Job, clean_html
from jobpilot.tailor import rule_based, tailor_resume, verify_truthful

ROOT = Path(__file__).resolve().parent.parent
RESUME = load_resume(ROOT / "data" / "resume.md")
SEARCH = {"title_include": ["data"], "title_exclude": ["intern", "director"], "locations": ["remote"], "remote_ok": True, "min_score": 40}

JD = ("We need a Data Engineer with 3+ years of experience in Python, SQL, Spark, Airflow, Snowflake, "
      "AWS and Kubernetes. Build ETL pipelines and data models. You will own batch pipelines end to end, "
      "partner with analytics teams, and improve data quality across our warehouse and lake platforms.")


def job(title="Data Engineer", desc=JD, remote=True, ext="1"):
    return Job("test", ext, title, "Acme", "Remote - US", f"https://x/{ext}", desc, remote=remote)


def test_find_skills_boundaries():
    s = find_skills("Experience with Java, JavaScript and Node. PostgreSQL, k8s, C++")
    assert "java" in s and "javascript" in s and "postgresql" in s and "kubernetes" in s


def test_analyze_matches_and_gaps():
    a = analyze(job(), RESUME, SEARCH, years=5)
    assert "python" in a.matched and "airflow" in a.matched
    assert "kubernetes" in a.missing
    assert 40 < a.score <= 100 and a.eligible


def test_filters():
    assert not passes_filters(job(title="Data Intern"), SEARCH)[0]
    assert not passes_filters(job(title="Chef"), SEARCH)[0]


def test_rule_tailor_is_truthful_and_reorders():
    j = job()
    a = analyze(j, RESUME, SEARCH)
    new = rule_based(RESUME, j, a)
    assert verify_truthful(RESUME, new) == []
    skills = next(s for s in new.sections if s.title == "Skills")
    assert skills.lines[0].startswith("Languages:")


def test_guardrail_catches_invented_skill_and_number():
    fake = parse_resume_text(RESUME.to_markdown() + "\n- Led Kubernetes migration saving 99% of costs\n")
    issues = verify_truthful(RESUME, fake)
    assert any("kubernetes" in i for i in issues) and any("99%" in i for i in issues)


def test_tailor_without_api_key_uses_rules(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    j = job()
    r = tailor_resume(RESUME, j, analyze(j, RESUME, SEARCH), {"llm": {"enabled": True, "model": "x"}, "resume": {}})
    assert r.engine == "rules"


def test_clean_html():
    assert "Hello" in clean_html("&lt;p&gt;Hello &amp; welcome&lt;/p&gt;")


def test_daily_run_respects_cap_and_landed(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(pipeline, "data_dir", lambda: tmp_path)
    db = DB(tmp_path / "t.db")
    jobs = [job(ext=str(i), title=f"Data Engineer {i}") for i in range(8)]
    monkeypatch.setattr(pipeline, "fetch_all", lambda cfg: (jobs, []))
    cfg = {"profile": {"years_experience": 5}, "resume": {"base_path": str(ROOT / "data" / "resume.md"), "max_bullets_per_role": 7},
           "search": SEARCH, "sources": {}, "apply": {"daily_limit": 3, "mode": "prepare"}, "answers": {},
           "llm": {"enabled": False, "model": "x"}}
    s1 = pipeline.run_daily(cfg, db)
    assert s1["prepared"] == 3 and s1["new_jobs"] == 8
    assert len(db.list_jobs("ready")) == 3
    assert all(Path(r["resume_path"]).exists() for r in db.list_jobs("ready"))
    s2 = pipeline.run_daily(cfg, db)            # same day -> cap already used
    assert s2["prepared"] == 0
    db.set_setting("landed", "1")
    assert pipeline.run_daily(cfg, db) == {"skipped": "landed"}
