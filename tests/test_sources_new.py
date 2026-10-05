from pathlib import Path

import pytest

from jobpilot import pipeline
from jobpilot.db import DB
from jobpilot.sources.alerts import canonical, parse_alert_html
from jobpilot.sources.importer import import_url, is_portal, parse_job_page

ROOT = Path(__file__).resolve().parent.parent
LONG_JD = ("Build ETL pipelines in Python and SQL on Snowflake and Databricks with Airflow on AWS. " * 4)

LINKEDIN_EMAIL = """
<html><body>
<a href="https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=abc&refId=x">Senior Data Engineer</a>
<span>Acme Analytics</span><span>Dallas, TX (Hybrid)</span>
<a href="https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=dup">Senior Data Engineer</a>
<a href="https://www.linkedin.com/comm/jobs/view/4099999999/?x=1">Machine Learning Engineer</a>
<span>Globex</span><span>Remote</span>
<a href="https://www.linkedin.com/help">Help</a>
</body></html>
"""

INDEED_EMAIL = '<a href="https://www.indeed.com/rc/clk?jk=a1b2c3d4e5f6&fccid=zz">Data Analyst</a><p>Initech</p><p>Austin, TX</p>'

JSONLD_PAGE = """<html><head><title>Careers</title>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting","title":"Data Engineer",
"hiringOrganization":{"@type":"Organization","name":"Example Co"},
"jobLocation":{"@type":"Place","address":{"@type":"PostalAddress","addressLocality":"Plano","addressRegion":"TX"}},
"datePosted":"2026-10-01","description":"&lt;p&gt;Build ETL in Python and SQL on Snowflake.&lt;/p&gt;"}</script></head><body></body></html>"""


def test_linkedin_alert_parsing_dedupes_and_extracts_fields():
    jobs = parse_alert_html("linkedin", LINKEDIN_EMAIL)
    assert [j.external_id for j in jobs] == ["4012345678", "4099999999"]
    assert jobs[0].title == "Senior Data Engineer" and jobs[0].company == "Acme Analytics"
    assert jobs[0].location.startswith("Dallas") and jobs[1].remote
    assert jobs[0].url == "https://www.linkedin.com/jobs/view/4012345678"     # tracking params stripped


def test_indeed_alert_parsing():
    (j,) = parse_alert_html("indeed", INDEED_EMAIL)
    assert j.external_id == "a1b2c3d4e5f6" and j.company == "Initech"


def test_canonical_rejects_non_job_links():
    assert canonical("linkedin", "https://www.linkedin.com/help") is None
    assert canonical("handshake", "https://app.joinhandshake.com/stu/jobs/12345?x=1")[0] == "12345"


def test_jsonld_import():
    j = parse_job_page("https://careers.example.com/job/1", JSONLD_PAGE)
    assert (j.title, j.company, j.location) == ("Data Engineer", "Example Co", "Plano, TX")
    assert "Snowflake" in j.description


def test_portals_refused():
    assert is_portal("https://www.linkedin.com/jobs/view/1") and is_portal("https://app.joinhandshake.com/jobs/1")
    with pytest.raises(ValueError):
        import_url("https://www.indeed.com/viewjob?jk=abc")


def _cfg(tmp_path):
    return {"profile": {"years_experience": 5}, "resume": {"base_path": str(ROOT / "data" / "resume.md"), "max_bullets_per_role": 7},
            "search": {"title_include": ["data"], "title_exclude": ["intern"], "locations": ["remote", "dallas"], "remote_ok": True, "min_score": 40},
            "sources": {}, "apply": {"daily_limit": 5, "mode": "prepare"}, "answers": {}, "llm": {"enabled": False, "model": "x"}}


def test_alert_jobs_wait_for_jd_then_score(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "data_dir", lambda: tmp_path)
    db, cfg = DB(tmp_path / "t.db"), _cfg(tmp_path)
    for j in parse_alert_html("linkedin", LINKEDIN_EMAIL):
        db.upsert_job(j)
    pipeline.score_new_jobs(db, cfg, pipeline.base_resume(cfg))
    jid = db.find_id("linkedin", "4012345678")
    assert db.get(jid)["status"] == "needs_jd" and db.get(jid)["score"] is None
    # daily run must NOT tailor/apply to jobs that have no description
    assert pipeline.run_daily(cfg, db, fetch=False)["prepared"] == 0
    pipeline.set_description(db, cfg, jid, LONG_JD)
    row = db.get(jid)
    assert row["status"] == "scored" and row["score"] > 40


def test_manual_add_survives_title_filter(tmp_path, monkeypatch):
    from jobpilot.sources.base import Job

    monkeypatch.setattr(pipeline, "data_dir", lambda: tmp_path)
    db, cfg = DB(tmp_path / "t.db"), _cfg(tmp_path)
    jid = pipeline.add_job(db, cfg, Job("indeed", "x1", "Business Intelligence Lead", "Initech", "Austin, TX", "", LONG_JD))
    assert db.get(jid)["status"] == "scored"
