import datetime as dt
import shutil
from pathlib import Path

import pytest

from dashboard import metrics as M
from dashboard import theme as T
from jobpilot.db import DB
from jobpilot.sources.base import Job

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def seeded(tmp_path):
    db = DB(tmp_path / "jobpilot.db")
    for i, (st, sc) in enumerate([("ready", 80), ("applied", 70), ("interview", 90), ("needs_jd", None), ("skipped", 20)]):
        db.upsert_job(Job("linkedin", f"x{i}", f"Data Engineer {i}", f"Co{i}", "Remote", "http://x", "desc"))
        jid = db.find_id("linkedin", f"x{i}")
        db.update(jid, status=st, score=sc, missing="airflow, dbt" if i % 2 else "kafka",
                  processed_at=dt.datetime.now().isoformat(timespec="seconds"), applied_at=dt.datetime.now().isoformat(timespec="seconds"))
    db.log_application("indeed", "k1", title="ML Engineer", company="Acme", status="applied", match_score=0.72)
    db.log_application("career-site", "k2", title="AI Eng", company="Beta", status="needs_review", match_score=0.55)
    return db


def test_metrics(seeded):
    jobs, apps = M.frames(seeded)
    ev = M.applied_events(jobs, apps)
    assert len(ev) == 3  # indeed app + applied + interview job
    daily = M.daily_applied(ev, 7)
    assert len(daily) == 7 and int(daily.values.sum()) == 3
    fun = M.funnel_counts(jobs, apps)
    assert fun["applied"] == 3 and fun["interview"] == 1 and fun["found"] == 7
    assert M.top_gaps(jobs)[0][1] >= 2
    cols, totals = M.board(jobs, apps)
    assert totals["needs_review"] == 1 and totals["ready"] == 1
    assert "Acme" in T.board(cols, totals) and M.rate(1, 0) is None


def test_empty_frames(tmp_path):
    jobs, apps = M.frames(DB(tmp_path / "e.db"))
    assert M.daily_applied(M.applied_events(jobs, apps), 5).shape[0] == 5
    assert M.funnel_counts(jobs, apps)["found"] == 0
    cols, totals = M.board(jobs, apps)
    assert "Empty" in T.board(cols, totals)


def _run_app(tmp_path, monkeypatch, db_seed):
    from streamlit.testing.v1 import AppTest
    import streamlit as st
    import jobpilot.config as C
    shutil.copy(ROOT / "config.yaml", tmp_path / "config.yaml")
    monkeypatch.setattr(C, "ROOT", tmp_path)
    st.cache_resource.clear()
    if db_seed:
        shutil.copy(db_seed, tmp_path / "data" / "jobpilot.db") if (tmp_path / "data").exists() else None
    at = AppTest.from_file(str(ROOT / "dashboard" / "app.py"), default_timeout=60)
    at.run()
    return at


def test_app_renders_empty(tmp_path, monkeypatch):
    at = _run_app(tmp_path, monkeypatch, None)
    assert not at.exception
    assert [t.label for t in at.tabs][:3] == ["Command center", "Pipeline board", "Applications"]


def test_app_renders_seeded(tmp_path, monkeypatch, seeded):
    (tmp_path / "data").mkdir()
    seeded.conn.commit()
    shutil.copy(seeded.path if hasattr(seeded, "path") else tmp_path / "jobpilot.db", tmp_path / "data" / "jobpilot.db")
    at = _run_app(tmp_path, monkeypatch, None)
    assert not at.exception
