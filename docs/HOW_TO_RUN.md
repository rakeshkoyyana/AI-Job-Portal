# Hirewing: How to Run It (daily checklist)

Use this every day you want to apply. Everything runs on your own computer. Replace `~/AI-Job-Portal` with wherever you cloned the project.

## A. Start (about 1 minute)

**Terminal 1: the server (keep it open)**
```bash
cd ~/AI-Job-Portal
source .venv/bin/activate
python -m jobpilot api
```

**Terminal 2: the dashboard**
```bash
cd ~/AI-Job-Portal
source .venv/bin/activate
python -m jobpilot dashboard
```
Opens in your browser, usually http://localhost:8501.

**Terminal 3 (optional): the daily scheduler**
```bash
cd ~/AI-Job-Portal
source .venv/bin/activate
python -m jobpilot schedule
```
Runs the email-and-resume-prep pipeline every day at the "Auto-run time" in Dashboard -> Settings (default 09:00 Central). Leave it open. Skip it if you don't want the automatic morning run; the extension doesn't need it.

**Check:** click the Hirewing extension icon in Chrome. The header should say "connected". If not, Terminal 1 isn't running.

## B. Apply

Stay logged in to each site yourself.

| Where | Open | Press |
| --- | --- | --- |
| LinkedIn | Jobs search with the **Easy Apply** filter | Extension icon -> **Start** (LinkedIn) |
| Indeed | A search results page | Extension icon -> **Start** (Indeed) |
| Career sites | The job's application page | It auto-fills, or press **Fill + submit** / **Fill only** |

- Press **Stop** in the popup any time.
- First runs: set `auto_submit: false` in `config.yaml` (restart Terminal 1) so it fills but doesn't submit.
- It stops and marks **Needs review** on captchas, questions it can't answer, or stuck steps. Finish those by hand.
- Daily caps per site are in `config.yaml` (default 25 each).

## C. Check results (dashboard)
- **Command center:** live totals and charts.
- **Applications:** filter, export, open Needs review rows and finish them.
- **Questions:** answer anything the extension couldn't (it reuses your answer).
- **Tailor & ATS:** paste a job description to get a rewritten resume, ATS score, match probability and interview prep.
- Sidebar: **Run pipeline now** (on demand) and **I landed a job** (pauses everything).

## D. Stop
Ctrl+C in each terminal.

## E. Update to the latest version
```bash
cd ~/AI-Job-Portal
git pull
source .venv/bin/activate
pip install -r requirements.txt
```
Then restart the terminals, and reload the extension at `chrome://extensions` (circular arrow). It should show "Hirewing 0.3.0" or newer.

## F. Troubleshooting

| Problem | Fix |
| --- | --- |
| `command not found: python` | Activate the venv: `source .venv/bin/activate` (or use `python3`) |
| `No module named ...` | `pip install -r requirements.txt` with the venv active |
| Extension "not connected" | Start Terminal 1; re-paste the token in the extension Settings if needed |
| Dashboard says "API not started" | Start Terminal 1 |
| LinkedIn/Indeed step stalls | Not tested on the live sites. Open DevTools (Cmd+Option+J), copy the red errors, send them with the step where it stuck |
| Sidebar disappeared | Click the `>>` button at top-left, or hard-refresh |
| New token wanted | Delete `data/api_token.txt`, restart Terminal 1, paste the new one in the extension |
| Extension still shows old name | `git pull`, then check Details -> "Loaded from" is your `AI-Job-Portal/extension` folder, then reload |

## G. One-time setup (already done)
1. `git clone https://github.com/rakeshkoyyana/AI-Job-Portal`
2. `python3 -m venv .venv` and `source .venv/bin/activate`
3. `pip install -r requirements.txt` and `cp .env.example .env`
4. Fill your profile in `config.yaml` (or Dashboard -> Settings)
5. Upload your resume in Dashboard -> Resumes and set it as default
6. Chrome -> `chrome://extensions` -> Developer mode -> Load unpacked -> `extension/`; paste the token (in `data/api_token.txt`) in its Settings

Note: automating LinkedIn and Indeed can violate their terms and risk your account.
