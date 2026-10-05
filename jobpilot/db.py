from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from .sources.base import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  external_id TEXT NOT NULL,
  title TEXT, company TEXT, location TEXT, url TEXT, apply_url TEXT,
  description TEXT, posted_at TEXT, remote INTEGER DEFAULT 0,
  score REAL, matched TEXT, missing TEXT, notes TEXT,
  status TEXT DEFAULT 'new',
  resume_path TEXT, cover_path TEXT,
  created_at TEXT, processed_at TEXT, applied_at TEXT,
  UNIQUE(source, external_id)
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT, finished_at TEXT, fetched INTEGER, new_jobs INTEGER,
  prepared INTEGER, applied INTEGER, errors TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS resumes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, filename TEXT, path TEXT, text TEXT,
  is_default INTEGER DEFAULT 0, created_at TEXT
);
CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT NOT NULL, job_key TEXT NOT NULL,
  title TEXT, company TEXT, location TEXT, url TEXT,
  status TEXT, match_score REAL, resume_id INTEGER, notes TEXT,
  created_at TEXT, updated_at TEXT,
  UNIQUE(platform, job_key)
);
CREATE TABLE IF NOT EXISTS questions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  normalized TEXT UNIQUE, question TEXT, field_type TEXT, options TEXT,
  answer TEXT, source TEXT, times_seen INTEGER DEFAULT 1, last_seen TEXT
);
"""

# new -> needs_jd (alert jobs w/o description; paste JD) | filtered | scored -> ready -> applied | needs_review | failed | skipped -> interview | offer


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


class DB:
    def __init__(self, path: str | Path = "data/jobpilot.db"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # jobs ---------------------------------------------------------------
    def upsert_job(self, j: Job) -> bool:
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO jobs
               (source, external_id, title, company, location, url, apply_url,
                description, posted_at, remote, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (j.source, j.external_id, j.title, j.company, j.location, j.url,
             j.apply_url or j.url, j.description, j.posted_at, int(j.remote), now()),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def find_id(self, source: str, external_id: str) -> int | None:
        r = self.conn.execute("SELECT id FROM jobs WHERE source=? AND external_id=?", (source, external_id)).fetchone()
        return r["id"] if r else None

    def update(self, job_id: int, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))
        self.conn.commit()

    def get(self, job_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()

    def list_jobs(self, status: str | list[str] | None = None, limit: int = 1000, order: str = "score DESC"):
        q, args = "SELECT * FROM jobs", []
        if status:
            statuses = [status] if isinstance(status, str) else list(status)
            q += f" WHERE status IN ({','.join('?' * len(statuses))})"
            args += statuses
        q += f" ORDER BY {order} LIMIT ?"
        return self.conn.execute(q, (*args, limit)).fetchall()

    def processed_today(self) -> int:
        today = dt.date.today().isoformat()
        return self.conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE substr(processed_at,1,10)=?", (today,)
        ).fetchone()[0]

    def counts_by_status(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT status, COUNT(*) c FROM jobs GROUP BY status").fetchall()
        return {r["status"]: r["c"] for r in rows}

    def per_day(self):
        return self.conn.execute(
            """SELECT substr(processed_at,1,10) day, COUNT(*) n FROM jobs
               WHERE processed_at IS NOT NULL GROUP BY day ORDER BY day"""
        ).fetchall()

    # resumes ------------------------------------------------------------
    def add_resume(self, name: str, filename: str, path: str, text: str) -> int:
        first = self.conn.execute("SELECT COUNT(*) FROM resumes").fetchone()[0] == 0
        cur = self.conn.execute(
            "INSERT INTO resumes (name, filename, path, text, is_default, created_at) VALUES (?,?,?,?,?,?)",
            (name, filename, path, text, int(first), now()))
        self.conn.commit()
        return cur.lastrowid

    def list_resumes(self):
        return self.conn.execute("SELECT * FROM resumes ORDER BY is_default DESC, id").fetchall()

    def get_resume(self, rid: int):
        return self.conn.execute("SELECT * FROM resumes WHERE id=?", (rid,)).fetchone()

    def default_resume(self):
        return self.conn.execute("SELECT * FROM resumes ORDER BY is_default DESC, id LIMIT 1").fetchone()

    def set_default_resume(self, rid: int) -> None:
        self.conn.execute("UPDATE resumes SET is_default=(id=?)", (rid,))
        self.conn.commit()

    def delete_resume(self, rid: int) -> None:
        was_default = (self.get_resume(rid) or {"is_default": 0})["is_default"]
        self.conn.execute("DELETE FROM resumes WHERE id=?", (rid,))
        if was_default:
            self.conn.execute("UPDATE resumes SET is_default=1 WHERE id=(SELECT MIN(id) FROM resumes)")
        self.conn.commit()

    # applications (extension tracker) -----------------------------------
    def log_application(self, platform: str, job_key: str, **f) -> int:
        existing = self.conn.execute("SELECT id FROM applications WHERE platform=? AND job_key=?", (platform, job_key)).fetchone()
        if existing:
            sets = ", ".join(f"{k}=?" for k in f) + ", updated_at=?"
            self.conn.execute(f"UPDATE applications SET {sets} WHERE id=?", (*f.values(), now(), existing["id"]))
            self.conn.commit()
            return existing["id"]
        cols = ["platform", "job_key", *f.keys(), "created_at", "updated_at"]
        cur = self.conn.execute(f"INSERT INTO applications ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                                (platform, job_key, *f.values(), now(), now()))
        self.conn.commit()
        return cur.lastrowid

    def application_status(self, platform: str, job_key: str) -> str | None:
        r = self.conn.execute("SELECT status FROM applications WHERE platform=? AND job_key=?", (platform, job_key)).fetchone()
        return r["status"] if r else None

    def list_applications(self, status: str | None = None, limit: int = 500):
        q, args = "SELECT * FROM applications", []
        if status:
            q += " WHERE status=?"
            args.append(status)
        return self.conn.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()

    def update_application(self, app_id: int, **f) -> None:
        sets = ", ".join(f"{k}=?" for k in f) + ", updated_at=?"
        self.conn.execute(f"UPDATE applications SET {sets} WHERE id=?", (*f.values(), now(), app_id))
        self.conn.commit()

    def applied_today_by_platform(self) -> dict[str, int]:
        today = dt.date.today().isoformat()
        rows = self.conn.execute(
            "SELECT platform, COUNT(*) c FROM applications WHERE status='applied' AND substr(updated_at,1,10)=? GROUP BY platform",
            (today,)).fetchall()
        return {r["platform"]: r["c"] for r in rows}

    # question bank ------------------------------------------------------
    def get_question(self, normalized: str):
        return self.conn.execute("SELECT * FROM questions WHERE normalized=?", (normalized,)).fetchone()

    def see_question(self, normalized: str, question: str, field_type: str, options: str) -> None:
        self.conn.execute(
            """INSERT INTO questions (normalized, question, field_type, options, source, last_seen)
               VALUES (?,?,?,?, 'unanswered', ?)
               ON CONFLICT(normalized) DO UPDATE SET times_seen=times_seen+1, last_seen=excluded.last_seen""",
            (normalized, question, field_type, options, now()))
        self.conn.commit()

    def save_answer(self, normalized: str, answer: str, source: str) -> None:
        self.conn.execute("UPDATE questions SET answer=?, source=? WHERE normalized=?", (answer, source, normalized))
        self.conn.commit()

    def list_questions(self, unanswered_only: bool = False):
        q = "SELECT * FROM questions"
        if unanswered_only:
            q += " WHERE answer IS NULL OR answer=''"
        return self.conn.execute(q + " ORDER BY times_seen DESC, id DESC").fetchall()

    def delete_question(self, qid: int) -> None:
        self.conn.execute("DELETE FROM questions WHERE id=?", (qid,))
        self.conn.commit()

    # settings -----------------------------------------------------------
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        r = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, value))
        self.conn.commit()

    # runs ---------------------------------------------------------------
    def log_run(self, **f) -> None:
        self.conn.execute(
            """INSERT INTO runs (started_at, finished_at, fetched, new_jobs, prepared, applied, errors)
               VALUES (:started_at,:finished_at,:fetched,:new_jobs,:prepared,:applied,:errors)""",
            f,
        )
        self.conn.commit()

    def recent_runs(self, n: int = 20):
        return self.conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (n,)).fetchall()
