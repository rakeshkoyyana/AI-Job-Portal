from __future__ import annotations

import argparse
import logging
import subprocess
import sys

from .config import ROOT, data_dir, load_config
from .db import DB
from .pipeline import run_daily


def _db() -> DB:
    return DB(data_dir() / "jobpilot.db")


def cmd_run(args):
    print(run_daily(load_config(), _db(), fetch=not args.no_fetch))


def cmd_schedule(_):
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    cfg = load_config()
    hh, mm = cfg["apply"]["run_time"].split(":")
    sched = BlockingScheduler(timezone=cfg["apply"]["timezone"])
    sched.add_job(lambda: print(run_daily(load_config(), _db())), CronTrigger(hour=int(hh), minute=int(mm)),
                  misfire_grace_time=3600, coalesce=True)
    print(f"Scheduled daily at {cfg['apply']['run_time']} {cfg['apply']['timezone']}. Ctrl+C to stop.")
    sched.start()


def cmd_dashboard(_):
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(ROOT / "dashboard" / "app.py")], check=False)


def cmd_serve(args):
    from .api import main as api_main

    api_main(port=args.port)


def cmd_assist(_):
    from .applier import assist_one
    from .db import now

    cfg, db = load_config(), _db()
    for row in db.list_jobs(["ready", "needs_review"], order="score DESC"):
        print(f"\n[{row['id']}] {row['title']} @ {row['company']}  (score {row['score']})\n{row['url']}")
        choice = input("Open & pre-fill? [y = yes, s = skip, q = quit] ").strip().lower()
        if choice == "q":
            break
        if choice != "y":
            continue
        assist_one(row["url"], row["apply_url"], cfg["profile"], row["resume_path"])
        if input("Did you submit? [y/N] ").strip().lower() == "y":
            db.update(row["id"], status="applied", applied_at=now())


def cmd_api(args):
    from .api import main as api_main

    api_main(port=args.port)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser("jobpilot")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the daily pipeline now")
    r.add_argument("--no-fetch", action="store_true")
    r.set_defaults(fn=cmd_run)
    sub.add_parser("schedule", help="run the pipeline every day at apply.run_time").set_defaults(fn=cmd_schedule)
    sub.add_parser("dashboard", help="open the Streamlit dashboard").set_defaults(fn=cmd_dashboard)
    for name, fn in (("api", cmd_api), ("serve", cmd_serve)):      # `serve` kept as an alias
        sp = sub.add_parser(name, help="local API for the browser extension (prints the access token)")
        sp.add_argument("--port", type=int, default=8765)
        sp.set_defaults(fn=fn)
    sub.add_parser("assist", help="visible-browser assisted apply for queued jobs").set_defaults(fn=cmd_assist)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
