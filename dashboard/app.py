"""JobPilot dashboard:  streamlit run dashboard/app.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

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

st.set_page_config(page_title="JobPilot", page_icon="🧭", layout="wide")


@st.cache_resource
def get_db() -> DB:
    return DB(data_dir() / "jobpilot.db")


db, cfg = get_db(), load_config()
STATUSES = ["ready", "needs_review", "needs_jd", "applied", "interview", "offer", "skipped", "failed", "scored", "filtered"]

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.title("🧭 JobPilot")
    landed = db.get_setting("landed") == "1"
    if landed:
        st.success("Marked as landed - daily runs are paused.")
        if st.button("Resume job search"):
            db.set_setting("landed", "0")
            st.rerun()
    else:
        if st.button("🎉 I landed a job - stop runs"):
            db.set_setting("landed", "1")
            st.rerun()
    st.divider()
    st.metric("Processed today", f"{db.processed_today()} / {cfg['apply']['daily_limit']}")
    if st.button("▶ Run pipeline now", type="primary", disabled=landed):
        with st.spinner("Fetching, scoring, tailoring..."):
            stats = run_daily(cfg, db)
        st.success(f"Fetched {stats['fetched']}, new {stats['new_jobs']}, prepared {stats['prepared']}, applied {stats['applied']}")
        if stats["errors"]:
            st.warning(stats["errors"])
    st.caption(f"Mode: **{cfg['apply']['mode']}** · runs daily at {cfg['apply']['run_time']} via `jobpilot schedule`")

tab_over, tab_apps, tab_resume, tab_lib, tab_q, tab_jobs, tab_add, tab_set = st.tabs(
    ["Overview", "Applications", "Tailor & ATS", "Resumes", "Questions", "Job search", "Add jobs", "Settings"])

# ------------------------------------------------------------------ overview
with tab_over:
    counts = db.counts_by_status()
    cols = st.columns(6)
    for c, (label, key) in zip(cols, [("Ready to apply", "ready"), ("Needs review", "needs_review"), ("Need JD pasted", "needs_jd"), ("Applied", "applied"),
                                      ("Interviews", "interview"), ("Offers", "offer")]):
        c.metric(label, counts.get(key, 0))
    left, right = st.columns(2)
    with left:
        st.subheader("Jobs processed per day")
        days = db.per_day()
        if days:
            st.bar_chart(pd.DataFrame([dict(r) for r in days]).set_index("day"))
        else:
            st.info("No runs yet. Add sources in Settings, then press Run pipeline now.")
    with right:
        st.subheader("Recent runs")
        runs = db.recent_runs(10)
        if runs:
            st.dataframe(pd.DataFrame([dict(r) for r in runs]).drop(columns=["id"]), hide_index=True, use_container_width=True)

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
        st.dataframe(df, hide_index=True, use_container_width=True, height=260)
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
            st.dataframe(pd.DataFrame([{"Component": k, "Points": p, "Max": m} for k, (p, m) in o.after.breakdown.items()]), hide_index=True, use_container_width=True)
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
    st.subheader("Applications logged by the browser extension")
    by = db.applied_today_by_platform()
    c1, c2, c3 = st.columns(3)
    caps = cfg.get("extension", {}).get("daily_cap", {})
    for col, plat in zip((c1, c2, c3), ("linkedin", "indeed", "career-site")):
        col.metric(f"{plat} today", f"{by.get(plat, 0)} / {caps.get(plat, '-')}")
    rows_ = db.list_applications(limit=2000)
    if rows_:
        adf = pd.DataFrame([dict(r) for r in rows_])[["id", "platform", "title", "company", "status", "match_score", "notes", "url", "updated_at"]]
        pick_s = st.multiselect("Status", sorted(adf["status"].dropna().unique()), default=[x for x in ("applied", "needs_review") if x in set(adf["status"])])
        view = adf[adf["status"].isin(pick_s)] if pick_s else adf
        st.dataframe(view, hide_index=True, use_container_width=True)
        st.download_button("Export CSV", view.to_csv(index=False), file_name="applications.csv")
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
