import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jobpilot.answers import validate
from jobpilot.api import create_app

ROOT = Path(__file__).resolve().parent.parent
RESUME = (ROOT / "data" / "resume.md").read_text()
JD = ("Data Engineer: build ETL pipelines in Python and SQL on Snowflake and Databricks, orchestrate with Airflow "
      "on AWS. 3+ years of experience. Kubernetes is a plus. " * 2)
H = {"X-JobPilot-Token": "secret"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return TestClient(create_app(tmp_path / "t.db", token="secret"))


def test_auth_required(client):
    assert client.get("/api/health").status_code == 401
    assert client.get("/api/health", headers=H).json()["ok"] is True


def test_parse_resume_upload(client):
    r = client.post("/api/parse-resume", headers=H, files={"file": ("r.md", RESUME.encode(), "text/markdown")})
    assert r.status_code == 200 and r.json()["name"] == "Jane Sample" and "## Skills" in r.json()["text"]


def test_match_picks_best_resume(client):
    weak = "# Bob\nx@y.z\n\n## Skills\nJava, Oracle\n\n## Experience\nDeveloper, Co — 2020\n- Wrote Java services\n"
    r = client.post("/api/match", headers=H, json={"title": "Data Engineer", "description": JD,
                    "resumes": [{"id": "weak", "text": weak}, {"id": "strong", "text": RESUME}]}).json()
    assert r["best_id"] == "strong" and r["score"] > r["scores"][1]["score"]
    assert "kubernetes" in r["missing"]


def test_tailor_returns_docx_and_is_truthful(client):
    r = client.post("/api/tailor", headers=H, json={"resume_text": RESUME, "title": "Data Engineer", "company": "Acme", "description": JD}).json()
    assert base64.b64decode(r["resume_docx_base64"])[:2] == b"PK" and r["engine"] == "rules"
    assert base64.b64decode(r["cover_docx_base64"])[:2] == b"PK"


def test_answer_without_llm_returns_null(client):
    r = client.post("/api/answer", headers=H, json={"question": "Why us?", "resume_text": RESUME}).json()
    assert r["answer"] is None


def test_answer_validation_blocks_invention():
    facts = "years_experience: 5\nPython, SQL, AWS"
    assert validate("Yes", ["Yes", "No"], facts) == "Yes"
    assert validate("Yes, I am", ["Yes", "No"], facts) == "Yes"
    assert validate("Maybe", ["Yes", "No"], facts) is None
    assert validate("5", None, facts) == "5"
    assert validate("12", None, facts) is None                       # number not in facts
    assert validate("I led Kubernetes migrations", None, facts) is None   # skill not in facts
    assert validate("UNKNOWN", None, facts) is None


def test_tracker_roundtrip(client):
    body = {"source": "linkedin", "external_id": "123", "title": "Data Engineer", "company": "Acme", "status": "applied"}
    assert client.post("/api/applications", headers=H, json=body).status_code == 200
    client.post("/api/applications", headers=H, json={**body, "external_id": "124", "status": "needs_review", "notes": "Q: sponsorship?"})
    rows = client.get("/api/applications", headers=H).json()
    assert {r["status"] for r in rows} == {"applied", "needs_review"}
    assert client.get("/api/stats", headers=H).json()["applied_today"] == 1


# ------------------------------------------------------------------ new endpoints
def _upload_resume(client, name="r.md", data=None):
    return client.post("/api/resumes", headers=H, files={"file": (name, (data or RESUME).encode(), "text/markdown")}, data={"name": "Main"})


def test_resume_library_and_default(client):
    rid = _upload_resume(client).json()["id"]
    rid2 = _upload_resume(client, "b.md").json()["id"]
    rows = client.get("/api/resumes", headers=H).json()
    assert [r["is_default"] for r in rows] == [True, False]
    client.post(f"/api/resumes/{rid2}/default", headers=H)
    assert next(r for r in client.get("/api/resumes", headers=H).json() if r["id"] == rid2)["is_default"]
    client.delete(f"/api/resumes/{rid2}", headers=H)
    assert len(client.get("/api/resumes", headers=H).json()) == 1
    assert client.post("/api/resumes", headers=H, files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 400


def test_job_match_returns_tailored_docx_and_gaps(client):
    _upload_resume(client)
    r = client.post("/api/job-match", headers=H, json={"platform": "linkedin", "job_key": "1", "title": "Data Engineer", "company": "Acme",
                                                          "description": JD}).json()
    assert r["apply"] is True and 0 < r["probability"] <= 1 and r["ats_after"] >= r["ats_before"]
    assert "kubernetes" in r["missing"]                                   # never claimed
    assert base64.b64decode(r["resume"]["b64"])[:2] == b"PK" and r["resume"]["filename"].endswith("_Resume.docx")
    ok = client.post("/api/job-match", headers=H, json={"title": "Data Engineer", "description": JD, "confirmed": ["Kubernetes"]}).json()
    assert "kubernetes" not in ok["missing"]


def test_job_match_skips_poor_fit(client):
    _upload_resume(client)
    jd = ("Senior Embedded Firmware Engineer. 10+ years of experience with C, C++, RTOS, Verilog, FPGA and PCB design. " * 4)
    r = client.post("/api/job-match", headers=H, json={"title": "Embedded Firmware Engineer", "description": jd}).json()
    assert r["apply"] is False and "below your minimum" in r["reason"]


def test_answer_bank_sensitive_and_dedupe(client):
    q = {"question": "What is your gender? *", "options": ["Male", "Female", "Decline to self-identify"]}
    assert client.post("/api/answer", headers=H, json=q).json() == {"answer": None, "reason": "sensitive"}   # never guessed
    assert [x["question"] for x in client.get("/api/questions?unanswered=true", headers=H).json()] == ["What is your gender? *"]
    client.post("/api/questions/answer", headers=H, json={"question": "What is your gender?", "answer": "Decline to self-identify"})
    assert client.post("/api/answer", headers=H, json=q).json() == {"answer": "Decline to self-identify", "reason": "bank"}
    assert client.get("/api/questions?unanswered=true", headers=H).json() == []


def test_application_status_for_dedupe(client):
    assert client.get("/api/applications/status?platform=linkedin&job_key=9", headers=H).json() == {"status": None}
    client.post("/api/applications", headers=H, json={"source": "linkedin", "external_id": "9", "status": "applied"})
    assert client.get("/api/applications/status?platform=linkedin&job_key=9", headers=H).json() == {"status": "applied"}
    assert client.get("/api/profile", headers=H).json()["extension"]["daily_cap"]["linkedin"] == 25
