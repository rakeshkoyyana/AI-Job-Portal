# JobPilot

A local-first job-application autopilot: a Chrome extension that applies on **LinkedIn (Easy Apply), Indeed and company career sites** (Greenhouse, Lever, Ashby, Workday, iCIMS, SmartRecruiters, Workable, BambooHR, ...), filling forms from your profile, plus a **resume tailoring + ATS + match-probability engine** and a Streamlit dashboard. Everything runs on your machine.

## Architecture
- `jobpilot/api.py` - FastAPI on `127.0.0.1:8765`, token-protected (`X-JobPilot-Token`, stored in `data/api_token.txt`).
- `extension/` - Chrome MV3 extension. Content scripts drive the pages; the service worker proxies API calls so the token never reaches web pages.
- `dashboard/app.py` - interactive Streamlit command center (dark theme, live status bar, activity ticker, KPI cards, funnel / per-day / score / source / skill-gap charts, kanban pipeline board, applications table with gauges, Tailor & ATS, resumes, question bank, settings). Auto-refreshes every 10s while the extension works.
- `jobpilot/engine.py` - tailoring: rewrites your **original .docx in place** (same format/styles) for a job description.
- `jobpilot/ats.py` - ATS keyword score, match probability, interview prep, suggestions.
- `jobpilot/answers.py` - screening-question answers: question bank -> config answers -> sensitive guard -> LLM (validated).
- SQLite storage (`data/jobpilot.db`).

## Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # ANTHROPIC_API_KEY optional (AI answers/rewrites); rules mode works without it
python -m jobpilot api        # prints the access token
python -m jobpilot dashboard  # in a second terminal
```
1. Fill `profile` and `extension` in `config.yaml` (or Dashboard -> Settings).
2. Upload your resume(s) (.docx preferred) in Dashboard -> Resumes.
3. Load the extension (see `extension/README.md`) and paste the token.

## Resume tailor + ATS (Dashboard -> Tailor & ATS)
Give a resume and a job description; you get:
- the **rewritten resume in your original format** (.docx) ready to submit,
- **ATS score** before/after with a breakdown and missing keywords,
- **match probability** (heuristic model, not a guarantee), interview prep and concrete suggestions.

Honesty guardrail: only skills your resume supports (or you explicitly confirm) are added; new numbers, dates, headers and education are never changed. An edit that fails verification is rejected.

## Extension behavior
Daily caps per platform, randomized pacing, minimum match probability (`extension.min_probability`), auto-submit toggle. It stops on captchas, unanswerable required questions, and stuck steps, and logs them as needs-review. Sensitive questions (demographics, legal status, etc.) are never guessed. No captcha solving, no stealth, no stored site passwords: you stay logged in yourself.

## Tests
```bash
python -m pytest -q
cd extension && npm install && node --test "test/*.test.js"
```

## Caveats
- Automating LinkedIn/Indeed likely violates their terms and can get your account restricted. Use at your own risk.
- Site selectors change; the LinkedIn/Indeed controllers were not exercised against live sites in development (only unit/jsdom tests). Expect to adjust them.
- Workday source, IMAP alert ingestion and live job sources are untested.
- Built from public feature descriptions of similar tools, not from any vendor's code.
