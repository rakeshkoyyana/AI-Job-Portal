"""JobPilot dashboard:  streamlit run dashboard/app.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import datetime as dt

import inspect as _insp

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

from dashboard import metrics as M
from dashboard import theme as T

from jobpilot.analyzer import analyze, job_from_row
from jobpilot.config import ROOT, data_dir, load_config, save_config
from jobpilot.db import DB, now
from jobpilot.pipeline import add_job, base_resume, prepare_job, run_daily, set_description
from jobpilot.sources.base import Job
from jobpilot.sources.importer import import_url, is_portal
from jobpilot.analyzer import has_term, jd_requirements
from jobpilot.answers import normalize
from jobpilot.engine import report_markdown, tailor as engine_tailor
from jobpilot.resume_io import load_resume

st.set_page_config(page_title=T.NAME, page_icon="🪽", layout="wide", initial_sidebar_state="expanded")
st.html(T.CSS)


@st.cache_resource
def get_db() -> DB:
    return DB(data_dir() / "jobpilot.db")


db, cfg = get_db(), load_config()
_WB = {"width": "stretch"} if "width" in _insp.signature(st.button).parameters else {"use_container_width": True}
STATUSES = ["ready", "needs_review", "needs_jd", "applied", "interview", "offer", "skipped", "failed", "scored", "filtered"]

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.html(T.sb_brand())
    landed = db.get_setting("landed") == "1"
    st.html(T.sb_today(db.processed_today(), cfg["apply"]["daily_limit"]))
    _c = db.counts_by_status()
    _nr = _c.get("needs_review", 0) + sum(1 for r in db.list_applications("needs_review", limit=100000))
    st.html(T.sb_stats([("Ready to apply", str(_c.get("ready", 0)), "accent"), ("Needs review", str(_nr), "amber" if _nr else ""),
                        ("Applied", str(_c.get("applied", 0)), "up"), ("Interviews", str(_c.get("interview", 0)), "accent"), ("Offers", str(_c.get("offer", 0)), "up")]))
    if st.button("▶  Run pipeline now", type="primary", disabled=landed, **_WB):
        with st.spinner("Fetching, scoring, tailoring..."):
            stats = run_daily(cfg, db)
        st.success(f"Fetched {stats['fetched']}, new {stats['new_jobs']}, prepared {stats['prepared']}, applied {stats['applied']}")
        if stats["errors"]:
            st.warning(stats["errors"])
    if landed:
        st.success("Landed! Daily runs are paused.")
        if st.button("Resume job search"):
            db.set_setting("landed", "0")
            st.rerun()
    elif st.button("🎉  I landed a job"):
        db.set_setting("landed", "1")
        st.rerun()
    st.html(f'<div class="sb-foot">Mode: <b>{cfg["apply"]["mode"]}</b> · daily run {cfg["apply"]["run_time"]}<br>Run <code>python -m jobpilot schedule</code> to automate.</div>')

REFRESH = st.sidebar.toggle("Live refresh (10s)", value=True, help="Re-reads the database so activity from the extension shows up.")
RUN_EVERY = "10s" if REFRESH else None


def _api_state() -> tuple[str, str]:
    tok = data_dir() / "api_token.txt"
    if not tok.exists():
        return "API not started", "down"
    try:
        r = requests.get("http://127.0.0.1:8765/api/health", headers={"X-JobPilot-Token": tok.read_text().strip()}, timeout=0.6)
        return ("API online · AI on" if r.ok and r.json().get("llm") else "API online · rules mode") if r.ok else "API token mismatch", "up" if r.ok else "amber"
    except requests.RequestException:
        return "API offline (run: python -m jobpilot api)", "down"


import inspect as _inspect

_W = {"width": "stretch"} if "width" in _inspect.signature(st.plotly_chart).parameters else {"use_container_width": True}
_WD = {"width": "stretch"} if "width" in _inspect.signature(st.dataframe).parameters else {"use_container_width": True}


def _plot(fig, height=300):
    fig.update_layout(height=height, **T.PLOT)
    fig.update_xaxes(**T.AXIS)
    fig.update_yaxes(**T.AXIS)
    return fig


@st.fragment(run_every=RUN_EVERY)
def header_and_tape():
    jobs, apps = M.frames(db)
    label, kind = _api_state()
    by = db.applied_today_by_platform()
    caps = cfg.get("extension", {}).get("daily_cap", {})
    applied_today = sum(by.values())
    cap_total = sum(v for v in caps.values() if isinstance(v, int))
    landed_now = db.get_setting("landed") == "1"
    pills = [T.pill(label, kind, live=kind == "up"),
             T.pill("Landed - paused" if landed_now else "Searching", "up" if landed_now else "accent", live=not landed_now),
             T.pill(f"Mode: {cfg['apply']['mode']}", "accent"),
             T.pill("Auto-submit ON" if cfg.get("extension", {}).get("auto_submit") else "Fill-only (safe)", "amber" if cfg.get("extension", {}).get("auto_submit") else "up"),
             T.pill(f"Today {applied_today}/{cap_total or '-'}", "accent")]
    st.html(T.topbar(pills, dt.datetime.now().strftime("%a %b %d  %H:%M:%S")))
    st.html(T.tape(M.activity(jobs, apps)))


header_and_tape()

tab_over, tab_board, tab_apps, tab_resume, tab_lib, tab_q, tab_jobs, tab_add, tab_set = st.tabs(
    ["Command center", "Pipeline board", "Applications", "Tailor & ATS", "Resumes", "Questions", "Job search", "Add jobs", "Settings"])

# ------------------------------------------------------------------ command center
with tab_over:
    @st.fragment(run_every=RUN_EVERY)
    def command_center():
        jobs, apps = M.frames(db)
        ev = M.applied_events(jobs, apps)
        daily = M.daily_applied(ev, 30)
        total_series = daily.sum(axis=1).tolist()
        fun = M.funnel_counts(jobs, apps)
        st_ = jobs["status"].value_counts().to_dict()
        by = db.applied_today_by_platform()
        caps = cfg.get("extension", {}).get("daily_cap", {})
        cap_total = sum(v for v in caps.values() if isinstance(v, int))
        today = sum(by.values())
        review = st_.get("needs_review", 0) + int((apps["status"] == "needs_review").sum())
        scores = pd.to_numeric(jobs["score"], errors="coerce").dropna()
        iv_rate = M.rate(fun["interview"], fun["applied"])
        cards = [
            T.kpi("Applied (total)", str(fun["applied"]), f"last 7d: {int(sum(total_series[-7:]))}", total_series, T.UP),
            T.kpi("Today", f"{today}<span class='mut' style='font-size:14px'> / {cap_total or '-'}</span>", "daily cap, all sites", progress=(today / cap_total) if cap_total else None),
            T.kpi("Ready to apply", str(st_.get("ready", 0)), "tailored, waiting", color=T.ACCENT),
            T.kpi("Needs review", str(review), "stopped: captcha / question", cls="amber" if review else ""),
            T.kpi("Need JD pasted", str(st_.get("needs_jd", 0)), "from alert emails"),
            T.kpi("Interviews", str(fun["interview"]), f"{iv_rate}% of applied" if iv_rate is not None else "-", cls="accent"),
            T.kpi("Offers", str(fun["offer"]), "", cls="up" if fun["offer"] else ""),
            T.kpi("Avg match", f"{scores.mean():.0f}" if len(scores) else "-", f"{len(scores)} scored jobs"),
        ]
        st.html('<div class="kpis">' + "".join(cards) + "</div>")
        if not len(jobs) and not len(apps):
            st.html('<div class="banner warn">Nothing tracked yet. Start the extension on a LinkedIn / Indeed search, add jobs in <b>Add jobs</b>, or press <b>Run pipeline now</b>.</div>')
        left, right = st.columns([3, 1.2], gap="small")
        with left:
            c1, c2 = st.columns(2)
            with c1:
                fig = go.Figure(go.Funnel(y=["Found", "Scored", "Ready", "Applied", "Interview", "Offer"], x=[fun[k] for k in M.FUNNEL],
                                          textinfo="value+percent initial", marker=dict(color=["#b8c4bd", "#7fcfb2", T.ACCENT, T.DARK_GREEN, T.AMBER, "#c9743a"])))
                st.markdown("**Application funnel**")
                st.plotly_chart(_plot(fig, 320), **_W, key="fun")
            with c2:
                st.markdown("**Applications per day (30d)**")
                fig = go.Figure()
                for col in daily.columns:
                    fig.add_bar(x=daily.index, y=daily[col], name=col, marker_color=T.PLATFORM_COLORS.get(col, T.ACCENT))
                fig.update_layout(barmode="stack")
                ymax = max(float(daily.sum(axis=1).max()), 3.0)
                if cap_total and cap_total <= ymax * 2:
                    fig.add_hline(y=cap_total, line_dash="dot", line_color=T.AMBER, annotation_text="daily cap")
                fig.update_yaxes(range=[0, max(ymax * 1.3, cap_total if cap_total and cap_total <= ymax * 2 else 0)])
                st.plotly_chart(_plot(fig, 320), **_W, key="perday")
            c3, c4, c5 = st.columns(3)
            with c3:
                st.markdown("**Match score distribution**")
                if len(scores):
                    fig = go.Figure(go.Histogram(x=scores, nbinsx=10, marker_color=T.ACCENT))
                    st.plotly_chart(_plot(fig, 260), **_W, key="hist")
                else:
                    st.caption("No scored jobs yet.")
            with c4:
                st.markdown("**Source mix**")
                src = pd.concat([jobs["source"].dropna(), apps["platform"].dropna()]).value_counts()
                if len(src):
                    fig = go.Figure(go.Pie(labels=src.index, values=src.values, hole=.6, marker=dict(colors=[T.PLATFORM_COLORS.get(x, T.ACCENT) for x in src.index])))
                    st.plotly_chart(_plot(fig, 260), **_W, key="mix")
                else:
                    st.caption("No data yet.")
            with c5:
                st.markdown("**Top skill gaps** (missing from your resume)")
                gaps = M.top_gaps(jobs, 8)
                if gaps:
                    fig = go.Figure(go.Bar(x=[g[1] for g in gaps][::-1], y=[g[0] for g in gaps][::-1], orientation="h", marker_color=T.AMBER))
                    st.plotly_chart(_plot(fig, 260), **_W, key="gaps")
                else:
                    st.caption("No gaps found yet.")
        with right:
            st.html(T.panel("Live activity", T.feed(M.activity(jobs, apps, 14)), "newest first", 430))
            runs = db.recent_runs(5)
            body = "".join(f'<div class="feed">{T.esc(str(r["started_at"])[:16])}<div class="t">fetched {r["fetched"]} · new {r["new_jobs"]} · prepared {r["prepared"]} · applied {r["applied"]}</div></div>' for r in runs) or '<div class="empty">No pipeline runs yet.</div>'
            st.html(T.panel("Pipeline runs", body, "", 220))

    command_center()

# ------------------------------------------------------------------ pipeline board
with tab_board:
    @st.fragment(run_every=RUN_EVERY)
    def pipeline_board():
        jobs, apps = M.frames(db)
        cols, totals = M.board(jobs, apps)
        st.html(T.board(cols, totals))
        with st.expander("Move a card"):
            opts = [(c["kind"], c["id"], f"{c['title']} @ {c['company']} ({s})") for s, cs in cols.items() for c in cs]
            if opts:
                m1, m2, m3 = st.columns([4, 2, 1])
                pick = m1.selectbox("Card", opts, format_func=lambda o: o[2], key="mv_card")
                dest = m2.selectbox("Move to", M.BOARD + ["skipped", "failed"], key="mv_to")
                if m3.button("Move", type="primary", key="mv_go"):
                    if pick[0] == "job":
                        db.update(pick[1], status=dest, **({"applied_at": now()} if dest == "applied" else {}))
                    else:
                        db.update_application(pick[1], status=dest)
                    st.rerun()
            else:
                st.caption("No cards yet.")

    pipeline_board()

# ------------------------------------------------------------------ jobs
with tab_jobs:
    f1, f2, f3 = st.columns([2, 2, 3])
    pick = f1.multiselect("Status", STATUSES, default=["ready", "needs_review", "needs_jd"])
    min_s = f2.slider("Min score", 0, 100, 0)
    q = f3.text_input("Search title/company")
    rows = [r for r in db.list_jobs(pick or None, limit=500)
            if (r["score"] or 0) >= min_s and q.lower() in f"{r['title']} {r['company']}".lower()]
    if not rows:
        st.info("No jobs match.")
    else:
        df = pd.DataFrame([{"id": r["id"], "score": r["score"], "title": r["title"], "company": r["company"],
                            "location": r["location"], "status": r["status"], "source": r["source"]} for r in rows])
        st.dataframe(df, hide_index=True, **_WD, height=260)
        jid = st.selectbox("Open job", [r["id"] for r in rows],
                           format_func=lambda i: next(f"#{r['id']} · {r['title']} @ {r['company']}" for r in rows if r["id"] == i))
        job = db.get(jid)
        a, b = st.columns([3, 2])
        with a:
            st.subheader(f"{job['title']} - {job['company']}")
            st.link_button("Open posting / apply page", job["apply_url"] or job["url"])
            with st.expander("Job description", expanded=False):
                st.text(job["description"])
        with b:
            st.metric("Match score", job["score"])
            st.write("**Matched:**", job["matched"] or "-")
            st.write("**Gaps (not on your resume):**", job["missing"] or "-")
            st.caption(job["notes"] or "")
        if job["status"] == "needs_jd":
            st.warning("This job came from an alert email, so it has no description yet. Open the posting, copy the "
                       "description, and paste it here to score it and tailor your resume.")
            pasted = st.text_area("Paste job description", key=f"jd{jid}", height=180)
            if st.button("Save description & score", disabled=len(pasted.strip()) < 200):
                set_description(db, cfg, jid, pasted)
                st.rerun()
        c1, c2, c3, c4 = st.columns(4)
        if c1.button("Re-tailor resume", disabled=job["status"] == "needs_jd"):
            with st.spinner("Tailoring..."):
                info = prepare_job(db, cfg, base_resume(cfg), jid)
                if job["status"] == "scored":
                    db.update(jid, status="ready")
            st.success(f"Tailored via {info['engine']}")
            st.rerun()
        if c2.button("✅ Mark applied"):
            db.update(jid, status="applied", applied_at=now())
            st.rerun()
        if c3.button("⏭ Skip"):
            db.update(jid, status="skipped")
            st.rerun()
        new_status = c4.selectbox("Set status", STATUSES, index=STATUSES.index(job["status"]) if job["status"] in STATUSES else 0,
                                  label_visibility="collapsed")
        if new_status != job["status"]:
            db.update(jid, status=new_status)
            st.rerun()
        for label, key in [("Tailored resume (.docx)", "resume_path"), ("Cover letter (.docx)", "cover_path")]:
            p = job[key]
            if p and Path(p).exists():
                st.download_button(label, Path(p).read_bytes(), file_name=Path(p).name, key=f"{key}{jid}")

# ------------------------------------------------------------------ add jobs
with tab_add:
    st.subheader("Jobs from LinkedIn / Indeed / Glassdoor / Handshake")
    st.markdown("Set up **saved searches with email alerts** on each site, enable `email_alerts` in Settings, and new jobs "
                "appear here automatically. Or add one right now by pasting its description:")
    with st.form("paste_jd", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        title = c1.text_input("Job title")
        company = c2.text_input("Company")
        src = c3.selectbox("Found on", ["linkedin", "indeed", "glassdoor", "handshake", "other"])
        url = st.text_input("Posting URL (so you can open it later)")
        jd = st.text_area("Job description", height=200)
        if st.form_submit_button("Add & score", type="primary"):
            if not (title and company and len(jd) >= 200):
                st.error("Need a title, company and the full description (200+ characters).")
            else:
                ext = f"{company}|{title}|{url}"[:200]
                jid = add_job(db, cfg, Job(src, ext, title, company, "", url, jd, remote="remote" in jd.lower()[:3000]))
                row = db.get(jid)
                st.success(f"Added #{jid}: score {row['score']} ({row['status']}). Find it in the Jobs tab.")
    st.divider()
    st.subheader("Company career-site job (any employer)")
    st.caption("Paste a link to a job on a company's own careers site (Workday, iCIMS, SmartRecruiters, Greenhouse, custom...). "
               "I read the page's structured job data. LinkedIn/Indeed/Glassdoor/Handshake links can't be fetched automatically.")
    curl = st.text_input("Career-site job URL")
    if st.button("Import") and curl:
        if is_portal(curl):
            st.error("That's a job-board link - use the paste form above with the description.")
        else:
            try:
                with st.spinner("Reading page..."):
                    jid = add_job(db, cfg, import_url(curl.strip()))
                row = db.get(jid)
                st.success(f"Imported \"{row['title']}\" at {row['company']}: score {row['score']} ({row['status']}).")
            except Exception as e:  # noqa: BLE001
                st.error(f"Couldn't import: {e}")

# ------------------------------------------------------------------ tailor & ATS
with tab_resume:
    st.subheader("Rewrite my resume for a job")
    st.caption("Your resume in its own format + a job description in. A tailored resume, ATS score, match probability, interview prep and suggestions out.")
    lib = db.list_resumes()
    mode = st.radio("Resume source", ["Upload a file", "From my library"] if lib else ["Upload a file"], horizontal=True)
    resume_path = None
    if mode == "Upload a file":
        up = st.file_uploader("Resume (.docx keeps your exact formatting; PDF/MD/TXT get a clean ATS layout)", type=["docx", "pdf", "md", "txt"], key="tailor_up")
        if up:
            udir = data_dir() / "uploads"
            udir.mkdir(exist_ok=True)
            resume_path = udir / up.name
            resume_path.write_bytes(up.getvalue())
            if st.button("Save to my resume library"):
                rdir = data_dir() / "resumes"
                rdir.mkdir(exist_ok=True)
                keep = rdir / up.name
                keep.write_bytes(up.getvalue())
                db.add_resume(Path(up.name).stem, up.name, str(keep), load_resume(keep).to_markdown())
                st.success("Saved. The browser extension can now use it.")
    else:
        row = st.selectbox("Library", lib, format_func=lambda r: f"{r['name']} ({r['filename']})")
        resume_path = Path(row["path"])

    t1, t2 = st.columns(2)
    title = t1.text_input("Job title", key="t_title")
    company = t2.text_input("Company", key="t_company")
    jd = st.text_area("Job description", height=220, key="t_jd")

    if resume_path and len(jd.strip()) >= 100:
        base_r = load_resume(resume_path)
        req, pref = jd_requirements(jd)
        gaps = sorted(t for t in (req | pref) if not has_term(base_r.text, t))
        confirmed = st.multiselect(
            "Skills this job wants that are NOT on your resume. Select only the ones you genuinely have and they will be added:",
            gaps, help="Anything you leave unselected is never added; it will show up as a gap to prepare for instead.")
        if st.button("Rewrite my resume & score it", type="primary"):
            with st.spinner("Rewriting in your format..."):
                outp = data_dir() / "out" / f"tailored_{normalize(company or 'job').replace(' ', '_')[:30]}.docx"
                try:
                    st.session_state["tailor_out"] = (engine_tailor(resume_path, jd, title, company, confirmed, cfg, out_path=outp), title, company)
                except Exception as e:  # noqa: BLE001
                    st.error(f"Could not tailor: {e}")
    elif resume_path or jd:
        st.info("Add a resume and a job description (100+ characters) to continue.")

    res = st.session_state.get("tailor_out")
    if res:
        o, rt, rc = res
        st.divider()
        m1, m2, m3 = st.columns(3)
        m1.metric("ATS score", f"{o.after.score:.0f} / 100", f"{o.after.score - o.before.score:+.0f} vs original")
        m2.metric("Match probability", f"{o.match_after['probability']:.0%}", f"{(o.match_after['probability'] - o.match_before['probability']) * 100:+.0f} pts")
        m3.metric("Verdict", o.match_after["label"], help="Heuristic estimate of recruiter-response likelihood, not a guarantee.")
        for w in o.warnings:
            st.warning(w)
        st.download_button("Download tailored resume (.docx)", o.docx_path.read_bytes(), file_name=f"{Path(resume_path).stem if resume_path else 'resume'}_tailored.docx", type="primary")
        st.download_button("Download full report (.md)", report_markdown(o, rt, rc), file_name="resume_report.md")

        k1, k2 = st.columns(2)
        with k1:
            st.markdown("**ATS score breakdown**")
            st.dataframe(pd.DataFrame([{"Component": k, "Points": p, "Max": m} for k, (p, m) in o.after.breakdown.items()]), hide_index=True, **_WD)
        with k2:
            st.markdown("**Keywords**")
            st.write("Matched required:", ", ".join(o.after.matched_required) or "-")
            st.write("Added to your skills section:", ", ".join(o.added_skills) or "-")
            st.write("Required but not on your resume (not added):", ", ".join(o.not_added) or "-")

        with st.expander(f"What changed ({len(o.changes)} edits, formatting untouched)"):
            for before, after in o.changes:
                st.markdown(f"~~{before[:160]}~~  \n**{after[:260]}**")
        st.markdown("**Suggestions**")
        for sug in o.suggestions:
            st.markdown(f"- {sug}")
        with st.expander("Interview prep", expanded=True):
            pr = o.prep
            st.markdown("**Likely technical questions**")
            for q in pr["likely_questions"]:
                st.markdown(f"- *{q['topic']}*: {q['question']}")
            if pr["gap_study_plan"]:
                st.markdown("**Gaps to prepare for**")
                for g_ in pr["gap_study_plan"]:
                    st.markdown(f"- *{g_['topic']}*: {g_['plan']}")
            st.markdown("**Behavioral**")
            for q in pr["behavioral"]:
                st.markdown(f"- {q}")
            if pr["story_anchors_from_your_resume"]:
                st.markdown("**Stories to tell (from your own resume)**")
                for q in pr["story_anchors_from_your_resume"]:
                    st.markdown(f"- {q}")
            st.markdown("**Questions to ask them**")
            for q in pr["questions_to_ask_them"]:
                st.markdown(f"- {q}")

# ------------------------------------------------------------------ applications (browser extension tracker)
with tab_apps:
    by = db.applied_today_by_platform()
    caps = cfg.get("extension", {}).get("daily_cap", {})
    gcols = st.columns(3)
    for col, plat in zip(gcols, ("linkedin", "indeed", "career-site")):
        n, cap = by.get(plat, 0), caps.get(plat, 0) or 0
        fig = go.Figure(go.Indicator(mode="gauge+number", value=n, title={"text": plat}, gauge={
            "axis": {"range": [0, max(cap, 1)]}, "bar": {"color": T.PLATFORM_COLORS.get(plat, T.ACCENT)}, "bgcolor": T.PANEL2, "borderwidth": 0}))
        fig.update_layout(margin=dict(l=20, r=20, t=50, b=10))
        col.plotly_chart(_plot(fig, 200).update_layout(margin=dict(l=20, r=20, t=50, b=10)), **_W, key=f"g_{plat}")
    rows_ = db.list_applications(limit=5000)
    if rows_:
        adf = pd.DataFrame([dict(r) for r in rows_])
        f1, f2, f3 = st.columns([2, 2, 3])
        sel_s = f1.multiselect("Status", sorted(adf["status"].dropna().unique()), default=[x for x in ("applied", "needs_review") if x in set(adf["status"])])
        sel_p = f2.multiselect("Platform", sorted(adf["platform"].dropna().unique()))
        qtxt = f3.text_input("Search title / company", key="app_q")
        view = adf
        if sel_s:
            view = view[view["status"].isin(sel_s)]
        if sel_p:
            view = view[view["platform"].isin(sel_p)]
        if qtxt:
            view = view[(view["title"].fillna("") + " " + view["company"].fillna("")).str.lower().str.contains(qtxt.lower())]
        show = view[["id", "platform", "title", "company", "status", "match_score", "notes", "url", "updated_at"]].copy()
        show["match_score"] = pd.to_numeric(show["match_score"], errors="coerce").apply(lambda x: x * 100 if pd.notna(x) and x <= 1 else x)
        st.dataframe(show, hide_index=True, height=380, **_WD, column_config={
            "match_score": st.column_config.ProgressColumn("match %", min_value=0, max_value=100, format="%.0f"),
            "url": st.column_config.LinkColumn("link", display_text="open")})
        d1, d2, d3 = st.columns([1, 2, 1])
        d1.download_button("Export CSV", show.to_csv(index=False), file_name="applications.csv")
        aid = d2.selectbox("Update a row", view["id"].tolist(), format_func=lambda i: f"#{i} · {view.loc[view['id'] == i, 'title'].iloc[0]}", key="upd_row")
        new = d3.selectbox("Status", ["applied", "needs_review", "interview", "offer", "rejected", "skipped"], key="upd_status")
        if st.button("Save status"):
            db.update_application(int(aid), status=new)
            st.rerun()
        st.caption("needs_review = the extension stopped (captcha, a question it won't guess, or an external site). Open the link and finish it yourself.")
    else:
        st.info("Nothing yet. Install the extension (extension/README.md) and press Start on a LinkedIn or Indeed search.")

# ------------------------------------------------------------------ resume library
with tab_lib:
    st.subheader("Resume library")
    st.caption("The extension picks the best resume for each job from this list, then rewrites it for that job.")
    upl = st.file_uploader("Add a resume", type=["docx", "pdf", "md", "txt"], key="lib_up")
    nm = st.text_input("Name (e.g. 'Data Engineer', 'ML Engineer')")
    if upl and st.button("Add to library"):
        rdir = data_dir() / "resumes"
        rdir.mkdir(exist_ok=True)
        dest = rdir / upl.name
        dest.write_bytes(upl.getvalue())
        try:
            db.add_resume(nm or Path(upl.name).stem, upl.name, str(dest), load_resume(dest).to_markdown())
            st.rerun()
        except Exception as e:  # noqa: BLE001
            dest.unlink(missing_ok=True)
            st.error(f"Could not read that file: {e}")
    for r in db.list_resumes():
        a, b, c = st.columns([5, 2, 2])
        a.write(f"**{r['name']}**  ·  {r['filename']}" + ("  ·  default" if r["is_default"] else ""))
        if not r["is_default"] and b.button("Make default", key=f"def{r['id']}"):
            db.set_default_resume(r["id"])
            st.rerun()
        if c.button("Delete", key=f"del{r['id']}"):
            db.delete_resume(r["id"])
            st.rerun()

# ------------------------------------------------------------------ question bank
with tab_q:
    st.subheader("Application questions")
    st.caption("Questions the extension met. Answer once and it reuses your answer everywhere. Sensitive ones (EEO, salary, visa) are only ever answered from here, never guessed.")
    qs = db.list_questions()
    if not qs:
        st.info("No questions seen yet.")
    for q in qs[:100]:
        with st.container(border=True):
            st.write(f"**{q['question']}**  ·  seen {q['times_seen']}x  ·  {q['field_type']}")
            if q["options"] and q["options"] != "[]":
                st.caption("Options: " + q["options"])
            ans = st.text_input("Your answer", value=q["answer"] or "", key=f"qa{q['id']}")
            b1, b2 = st.columns(2)
            if b1.button("Save answer", key=f"qs{q['id']}"):
                db.save_answer(q["normalized"], ans, "user")
                st.rerun()
            if b2.button("Forget", key=f"qd{q['id']}"):
                db.delete_question(q["id"])
                st.rerun()

# ------------------------------------------------------------------ settings
with tab_set:
    with st.form("settings"):
        st.subheader("Profile (used to fill application forms)")
        p1, p2, p3 = st.columns(3)
        cfg["profile"]["full_name"] = p1.text_input("Full name", cfg["profile"].get("full_name", ""))
        cfg["profile"]["email"] = p2.text_input("Email", cfg["profile"].get("email", ""))
        cfg["profile"]["phone"] = p3.text_input("Phone", cfg["profile"].get("phone", ""))
        p4, p5, p6 = st.columns(3)
        cfg["profile"]["location"] = p4.text_input("Location", cfg["profile"].get("location", ""))
        cfg["profile"]["linkedin"] = p5.text_input("LinkedIn URL", cfg["profile"].get("linkedin", ""))
        cfg["profile"]["years_experience"] = p6.number_input("Years of experience", 0.0, 40.0, float(cfg["profile"].get("years_experience", 5)))

        st.subheader("What to look for")
        csv = lambda k, d: [x.strip() for x in st.session_state.get(k, d).split(",") if x.strip()]  # noqa: E731
        s = cfg["search"]
        kw = st.text_input("Search keywords (comma-separated)", ", ".join(s["keywords"]))
        ti = st.text_input("Title must contain one of", ", ".join(s["title_include"]))
        te = st.text_input("Title must NOT contain", ", ".join(s["title_exclude"]))
        lo = st.text_input("Locations (substring match)", ", ".join(s["locations"]))
        s["remote_ok"] = st.checkbox("Remote jobs always OK", s["remote_ok"])
        s["min_score"] = st.slider("Minimum match score", 0, 100, int(s["min_score"]))

        st.subheader("Sources")
        so = cfg["sources"]
        gh = st.text_input("Greenhouse board tokens", ", ".join(so["greenhouse"]), help="the slug in boards.greenhouse.io/<slug>")
        lv = st.text_input("Lever company slugs", ", ".join(so["lever"]), help="the slug in jobs.lever.co/<slug>")
        ea = so.setdefault("email_alerts", {"enabled": False, "days_back": 3})
        ea["enabled"] = st.checkbox("Read my job-alert emails (LinkedIn / Indeed / Glassdoor / Handshake) - needs IMAP_USER / IMAP_PASSWORD in .env", ea["enabled"])
        ea["days_back"] = st.number_input("Look back (days)", 1, 14, int(ea.get("days_back", 3)))
        st.caption("Workday career sites: add entries under `sources.workday` in config.yaml (see README).")
        so["remotive"] = st.checkbox("Remotive (remote jobs API)", so["remotive"])
        so["adzuna"] = st.checkbox("Adzuna (needs API keys in .env)", so["adzuna"])

        st.subheader("Daily run")
        ap = cfg["apply"]
        ap["daily_limit"] = st.number_input("Jobs per day", 1, 100, int(ap["daily_limit"]))
        ap["mode"] = st.radio("Mode", ["prepare", "auto"], index=["prepare", "auto"].index(ap["mode"]), horizontal=True,
                              help="prepare: tailor + queue for your approval. auto: also try to submit Greenhouse/Lever forms (never bypasses captchas).")
        ap["run_time"] = st.text_input("Run time (HH:MM)", ap["run_time"])
        if st.form_submit_button("Save settings", type="primary"):
            to_list = lambda t: [x.strip() for x in t.split(",") if x.strip()]  # noqa: E731
            s["keywords"], s["title_include"], s["title_exclude"], s["locations"] = map(to_list, (kw, ti, te, lo))
            so["greenhouse"], so["lever"] = to_list(gh), to_list(lv)
            save_config(cfg)
            st.success("Saved. Restart `jobpilot schedule` if you changed the run time.")
