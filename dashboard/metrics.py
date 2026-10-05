"""Pure data functions behind the dashboard (no Streamlit imports, so they are unit-testable)."""
from __future__ import annotations

import datetime as dt
from collections import Counter

import pandas as pd

FUNNEL = ["found", "scored", "ready", "applied", "interview", "offer"]
BOARD = ["ready", "needs_review", "applied", "interview", "offer"]


def _day(s) -> str | None:
    return str(s)[:10] if s else None


def frames(db) -> tuple[pd.DataFrame, pd.DataFrame]:
    jobs = pd.DataFrame([dict(r) for r in db.list_jobs(None, limit=100000, order="id DESC")])
    apps = pd.DataFrame([dict(r) for r in db.list_applications(limit=100000)])
    for df, cols in ((jobs, ["id", "source", "title", "company", "location", "status", "score", "missing", "matched",
                             "created_at", "processed_at", "applied_at", "url", "apply_url"]),
                     (apps, ["id", "platform", "title", "company", "location", "status", "match_score", "notes", "url",
                             "created_at", "updated_at"])):
        for c in cols:
            if c not in df:
                df[c] = None
    return jobs, apps


def applied_events(jobs: pd.DataFrame, apps: pd.DataFrame) -> pd.DataFrame:
    """One row per application sent: columns day, platform. Extension applications + jobs marked applied by hand."""
    out = []
    for _, r in apps[apps["status"] == "applied"].iterrows():
        out.append({"day": _day(r["updated_at"]), "platform": r["platform"] or "other"})
    for _, r in jobs[jobs["status"].isin(["applied", "interview", "offer"])].iterrows():
        out.append({"day": _day(r["applied_at"] or r["processed_at"]), "platform": r["source"] or "other"})
    return pd.DataFrame(out, columns=["day", "platform"]).dropna()


def daily_applied(events: pd.DataFrame, days: int = 30, today: dt.date | None = None) -> pd.DataFrame:
    """Zero-filled day x platform table for the last `days` days."""
    today = today or dt.date.today()
    idx = [(today - dt.timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    if events.empty:
        return pd.DataFrame(0, index=idx, columns=["applied"])
    t = events.groupby(["day", "platform"]).size().unstack(fill_value=0)
    return t.reindex(idx, fill_value=0)


def funnel_counts(jobs: pd.DataFrame, apps: pd.DataFrame) -> dict[str, int]:
    st = Counter(jobs["status"].dropna())
    applied_apps = int((apps["status"] == "applied").sum())
    scored = len(jobs) - st["needs_jd"] - st["new"]
    ready = st["ready"] + st["applied"] + st["interview"] + st["offer"] + st["needs_review"]
    applied = st["applied"] + st["interview"] + st["offer"] + applied_apps
    return {"found": len(jobs) + len(apps), "scored": max(scored, 0) + len(apps), "ready": ready + len(apps),
            "applied": applied, "interview": st["interview"], "offer": st["offer"]}


def rate(num: int, den: int) -> float | None:
    return None if not den else round(100.0 * num / den, 1)


def top_gaps(jobs: pd.DataFrame, n: int = 12) -> list[tuple[str, int]]:
    c: Counter = Counter()
    for m in jobs["missing"].dropna():
        c.update(x.strip() for x in str(m).split(",") if x.strip())
    return c.most_common(n)


def board(jobs: pd.DataFrame, apps: pd.DataFrame, limit: int = 12) -> tuple[dict[str, list[dict]], dict[str, int]]:
    """Kanban columns of unified cards. kind='job' or 'app' tells the mover which table to update."""
    cols: dict[str, list[dict]] = {s: [] for s in BOARD}
    for _, r in jobs.iterrows():
        if r["status"] in cols:
            cols[r["status"]].append({"kind": "job", "id": int(r["id"]), "title": r["title"], "company": r["company"],
                                      "score": r["score"], "src": r["source"], "when": r["processed_at"] or r["created_at"]})
    for _, r in apps.iterrows():
        if r["status"] in cols:
            cols[r["status"]].append({"kind": "app", "id": int(r["id"]), "title": r["title"], "company": r["company"],
                                      "score": None if pd.isna(r["match_score"]) else round(float(r["match_score"]) * 100)
                                      if r["match_score"] is not None and r["match_score"] <= 1 else r["match_score"],
                                      "src": r["platform"], "when": r["updated_at"]})
    for s in cols:
        cols[s].sort(key=lambda c: str(c["when"] or ""), reverse=True)
    return {s: v[:limit] for s, v in cols.items()}, {s: len(v) for s, v in cols.items()}


def activity(jobs: pd.DataFrame, apps: pd.DataFrame, n: int = 25) -> list[dict]:
    items = []
    for _, r in apps.iterrows():
        items.append({"t": r["updated_at"], "status": r["status"], "title": r["title"], "company": r["company"], "src": r["platform"]})
    for _, r in jobs.iterrows():
        items.append({"t": r["processed_at"] or r["created_at"], "status": r["status"], "title": r["title"], "company": r["company"], "src": r["source"]})
    items = [i for i in items if i["t"]]
    return sorted(items, key=lambda i: str(i["t"]), reverse=True)[:n]
