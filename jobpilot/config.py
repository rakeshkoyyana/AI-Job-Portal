from __future__ import annotations

import copy
from pathlib import Path

import yaml

try:  # optional
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "config.yaml"


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


DEFAULTS: dict = {
    "profile": {"years_experience": 5},
    "extension": {
        "daily_cap": {"linkedin": 25, "indeed": 25, "career-site": 25},   # applications per platform per day
        "min_probability": 0.30,           # skip jobs whose estimated match is below this
        "pace_seconds": [4, 9],            # random pause between jobs (rate limiting, not stealth)
        "auto_submit": True,               # False = fill everything, stop before the final Submit
        "accept_consent_checkboxes": True, # tick privacy/"I certify" boxes; legal waivers/marketing are never ticked
    },
    "resume": {"base_path": "data/resume.md", "max_bullets_per_role": 7},
    "search": {
        "keywords": [],
        "title_include": [],
        "title_exclude": [],
        "locations": [],
        "remote_ok": True,
        "min_score": 55,
    },
    "sources": {"greenhouse": [], "lever": [], "workday": [], "remotive": False, "adzuna": False,
                "adzuna_country": "us", "email_alerts": {"enabled": False, "days_back": 3}},
    "apply": {"daily_limit": 10, "mode": "prepare", "run_time": "09:00", "timezone": "America/Chicago", "headless": True},
    "answers": {},
    "llm": {"enabled": True, "model": "claude-sonnet-5-5"},
}


def load_config(path: str | Path = DEFAULT_PATH) -> dict:
    p = Path(path)
    data = yaml.safe_load(p.read_text()) if p.exists() else {}
    return _merge(DEFAULTS, data or {})


def save_config(cfg: dict, path: str | Path = DEFAULT_PATH) -> None:
    Path(path).write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))


def data_dir() -> Path:
    d = ROOT / "data"
    d.mkdir(exist_ok=True)
    (d / "out").mkdir(exist_ok=True)
    return d
