"""Visual layer for the dashboard: CSS + small HTML builders (strings only, no Streamlit imports)."""
from __future__ import annotations

import base64
import html
import os
from pathlib import Path
from datetime import datetime

BRAND_DIR = Path(__file__).resolve().parent.parent / "assets" / "brand"
BRANDS = {"landed": ("Landed", "apply until you're hired"), "hirewing": ("Hirewing", "your job search, airborne"),
          "careerlift": ("Careerlift", "climb faster"), "applyloop": ("Applyloop", "apply. tailor. repeat."),
          "jobnest": ("Jobnest", "where your applications live"), "offerly": ("Offerly", "from application to offer")}
BRAND_SLUG = os.environ.get("JOBBOARD_BRAND", "hirewing")  # change this one value to rename the whole dashboard
NAME, TAGLINE = BRANDS.get(BRAND_SLUG, BRANDS["hirewing"])
BG, PANEL, PANEL2, BORDER = "#f6f7f3", "#ffffff", "#f1f4ef", "#dfe5de"
TEXT, MUTED, UP, DOWN, ACCENT, AMBER = "#1f2d27", "#66756e", "#1f9d74", "#d64545", "#24a47f", "#e8a317"
DARK_GREEN = "#12372c"
PLATFORM_COLORS = {"linkedin": "#12372c", "indeed": "#24a47f", "career-site": "#e8a317", "greenhouse": "#7fcfb2",
                   "lever": "#9aa8a1", "glassdoor": "#5fb88f", "handshake": "#c9743a", "other": "#b8c4bd"}
STATUS_KIND = {"applied": "up", "interview": "accent", "offer": "up", "ready": "accent", "needs_review": "amber",
               "needs_jd": "amber", "failed": "down", "skipped": "mut"}

CSS = f"""
<style>
:root {{ --bg:{BG}; --panel:{PANEL}; --border:{BORDER}; --text:{TEXT}; --muted:{MUTED}; --up:{UP}; --down:{DOWN}; --accent:{ACCENT}; --amber:{AMBER}; }}
[data-testid="stToolbarActions"], [data-testid="stMainMenu"], .stAppDeployButton, [data-testid="stDecoration"], [data-testid="stStatusWidget"], #MainMenu, footer {{ display:none !important; }}
[data-testid="stHeader"] {{ background:transparent !important; height:2.2rem; }}
[data-testid="stExpandSidebarButton"], [data-testid="stSidebarCollapsedControl"], [data-testid="stSidebarCollapseButton"] {{ color:{DARK_GREEN} !important; }}
[data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"] {{ background:{PANEL}; border:1px solid {BORDER}; border-radius:8px; box-shadow:0 1px 3px rgba(18,55,44,.1); }}
.stApp {{ background: linear-gradient(180deg, #eef5f0 0%, {BG} 340px) fixed; }}
.block-container {{ padding: 2.6rem 1.2rem 2rem 1.2rem !important; max-width: 100% !important; }}
[data-testid="stSidebar"] {{ background:{PANEL}; border-right:1px solid {BORDER}; }}
[data-testid="stSidebar"] > div:first-child {{ padding-top:0; }}
.sb-brand {{ display:flex; align-items:center; gap:11px; padding:6px 2px 14px; border-bottom:1px solid {BORDER}; margin-bottom:14px; }}
.sb-brand .n {{ font-size:21px; font-weight:800; color:{DARK_GREEN}; line-height:1.1; }} .sb-brand .t {{ font-size:11.5px; color:{MUTED}; margin-top:2px; }}
.sb-card {{ background:{PANEL2}; border:1px solid {BORDER}; border-radius:10px; padding:12px; margin-bottom:12px; }}
.sb-card .l {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.8px; color:{MUTED}; }}
.sb-ring {{ display:flex; align-items:center; gap:12px; }} .sb-ring .v {{ font-size:22px; font-weight:800; color:{DARK_GREEN}; }} .sb-ring .s {{ font-size:11.5px; color:{MUTED}; }}
.sb-row {{ display:flex; justify-content:space-between; align-items:center; padding:7px 0; border-bottom:1px solid #e8ede7; font-size:13px; }} .sb-row:last-child {{ border-bottom:0; }}
.sb-row b {{ font-variant-numeric:tabular-nums; }}
.sb-foot {{ font-size:11.5px; color:{MUTED}; line-height:1.5; margin-top:6px; }}
.tp-top {{ box-shadow:0 1px 3px rgba(18,55,44,.06); display:flex; align-items:center; gap:12px; padding:10px 14px; background:{PANEL}; border:1px solid {BORDER}; border-radius:10px; margin-bottom:8px; flex-wrap:wrap; }}
.tp-logo {{ font-weight:800; font-size:18px; letter-spacing:.4px; }} .tp-logo span {{ color:{ACCENT}; }} .tp-logo {{ color:{DARK_GREEN}; }}
.tp-spacer {{ flex:1; }} .tp-meta {{ color:{MUTED}; font-size:12px; }}
.pill {{ display:inline-flex; align-items:center; gap:6px; padding:3px 10px; border-radius:999px; font-size:11.5px; font-weight:600; border:1px solid {BORDER}; background:{BG}; color:{MUTED}; white-space:nowrap; }}
.pill.up {{ color:{UP}; border-color:rgba(31,157,116,.45); background:rgba(31,157,116,.10); }}
.pill.down {{ color:{DOWN}; border-color:rgba(214,69,69,.45); background:rgba(214,69,69,.10); }}
.pill.amber {{ color:{AMBER}; border-color:rgba(232,163,23,.45); background:rgba(232,163,23,.10); }}
.pill.accent {{ color:{ACCENT}; border-color:rgba(36,164,127,.45); background:rgba(36,164,127,.10); }}
.dot {{ width:7px; height:7px; border-radius:50%; background:currentColor; display:inline-block; }}
.dot.live {{ animation: pulse 1.6s infinite; }}
@keyframes pulse {{ 0%{{opacity:1}} 50%{{opacity:.25}} 100%{{opacity:1}} }}
.tape {{ overflow:hidden; background:{PANEL}; border:1px solid {BORDER}; border-radius:8px; margin-bottom:10px; position:relative; }}
.tape::before, .tape::after {{ content:""; position:absolute; top:0; bottom:0; width:42px; z-index:2; pointer-events:none; }}
.tape::before {{ left:0; background:linear-gradient(90deg,{PANEL},transparent); }}
.tape::after {{ right:0; background:linear-gradient(270deg,{PANEL},transparent); }}
.tape-track {{ display:flex; width:max-content; animation: tape var(--dur,70s) linear infinite; padding:9px 0; }}
.tape:hover .tape-track {{ animation-play-state: paused; }}
@keyframes tape {{ from {{ transform: translateX(0); }} to {{ transform: translateX(-50%); }} }}
.ti {{ display:inline-flex; align-items:center; gap:7px; padding:0 22px; border-right:1px solid {BORDER}; font-size:12.5px; white-space:nowrap; }}
.up {{ color:{UP}; }} .down {{ color:{DOWN}; }} .mut {{ color:{MUTED}; }} .amber {{ color:{AMBER}; }} .accent {{ color:{ACCENT}; }}
.kpis {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap:10px; margin-bottom:10px; }}
.kpi {{ background:{PANEL}; border:1px solid {BORDER}; border-radius:10px; padding:11px 13px 9px 13px; position:relative; overflow:hidden; transition:border-color .15s, transform .15s; }}
.kpi:hover {{ border-color:{ACCENT}; box-shadow:0 2px 10px rgba(18,55,44,.08); }}
.kpi .l {{ color:{MUTED}; font-size:11px; text-transform:uppercase; letter-spacing:.7px; }}
.kpi .v {{ font-size:24px; font-weight:700; margin-top:2px; font-variant-numeric: tabular-nums; }}
.kpi .s {{ color:{MUTED}; font-size:11px; margin-top:1px; }}
.kpi img {{ position:absolute; right:8px; bottom:8px; opacity:.9; }}
.bar {{ height:5px; background:{BG}; border-radius:5px; margin-top:7px; overflow:hidden; }} .bar i {{ display:block; height:100%; background:{ACCENT}; border-radius:5px; }}
.panel {{ background:{PANEL}; border:1px solid {BORDER}; border-radius:10px; padding:10px 12px; margin-bottom:10px; }}
.panel h4 {{ margin:0 0 8px 0; font-size:12px; text-transform:uppercase; letter-spacing:.8px; color:{MUTED}; font-weight:600; display:flex; justify-content:space-between; align-items:center; }}
.scroll {{ overflow-y:auto; padding-right:4px; }}
.scroll::-webkit-scrollbar {{ width:6px; }} .scroll::-webkit-scrollbar-thumb {{ background:{BORDER}; border-radius:6px; }}
.chip {{ padding:1px 7px; border-radius:6px; font-size:10.5px; font-weight:700; display:inline-block; }}
.chip.up {{ background:rgba(31,157,116,.16); color:{UP}; }} .chip.down {{ background:rgba(214,69,69,.16); color:{DOWN}; }}
.chip.mut {{ background:rgba(102,117,110,.16); color:{MUTED}; }} .chip.accent {{ background:rgba(36,164,127,.16); color:{ACCENT}; }}
.chip.amber {{ background:rgba(232,163,23,.16); color:{AMBER}; }}
.feed {{ padding:8px 2px; border-bottom:1px solid #e8ede7; font-size:12.5px; }} .feed:last-child {{ border-bottom:0; }}
.feed .t {{ color:{MUTED}; font-size:10.5px; margin-top:2px; }}
.empty {{ color:{MUTED}; font-size:12.5px; padding:10px 2px; }}
.board {{ display:grid; grid-template-columns: repeat(5, minmax(190px, 1fr)); gap:10px; }}
.col {{ background:{PANEL}; border:1px solid {BORDER}; border-radius:10px; padding:8px; min-height:140px; max-height:640px; overflow-y:auto; }}
.col h5 {{ margin:2px 4px 8px; font-size:11.5px; text-transform:uppercase; letter-spacing:.7px; color:{MUTED}; display:flex; justify-content:space-between; }}
.card {{ background:{PANEL2}; border:1px solid {BORDER}; border-radius:10px; padding:8px 10px; margin-bottom:7px; font-size:12.5px; transition:border-color .15s; }}
.card:hover {{ border-color:{ACCENT}; }} .card b {{ display:block; line-height:1.3; }} .card .m {{ color:{MUTED}; font-size:11px; margin-top:3px; display:flex; gap:6px; align-items:center; flex-wrap:wrap; }}
.banner {{ border-radius:8px; padding:10px 14px; border:1px solid {BORDER}; margin-bottom:10px; font-size:13px; }}
.banner.warn {{ border-color:rgba(232,163,23,.5); background:rgba(232,163,23,.08); }}
.banner.good {{ border-color:rgba(31,157,116,.5); background:rgba(31,157,116,.08); }}
button[data-baseweb="tab"] {{ font-weight:600; }}
.stButton > button[kind="primary"], .stDownloadButton > button {{ background:{ACCENT}; border-color:{ACCENT}; color:#fff; border-radius:8px; font-weight:600; }}
.stButton > button[kind="primary"]:hover {{ background:#1d8c6c; border-color:#1d8c6c; }}
.stButton > button, .stDownloadButton > button {{ border-radius:8px; }}
h1,h2,h3,h4 {{ color:{DARK_GREEN}; }}
[data-testid="stMetric"] {{ background:{PANEL}; border:1px solid {BORDER}; border-radius:8px; padding:10px 12px; }}
[data-testid="stDataFrame"] {{ border:1px solid {BORDER}; border-radius:8px; overflow:hidden; }}
</style>
"""

PLOT = dict(template="plotly_white", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color=MUTED, size=11),
            margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h", y=1.12, x=0))
AXIS = dict(gridcolor="#e8ede7", zeroline=False)


def mark_img(size: int = 30) -> str:
    try:
        b64 = base64.b64encode((BRAND_DIR / f"{BRAND_SLUG}-mark.svg").read_bytes()).decode()
    except OSError:
        return ""
    return f'<img alt="{NAME}" width="{size}" height="{size}" style="display:block" src="data:image/svg+xml;base64,{b64}">'


def esc(s) -> str:
    return html.escape("" if s is None else str(s))


def ago(ts, now: datetime | None = None) -> str:
    if not ts:
        return "—"
    try:
        t = datetime.fromisoformat(str(ts)[:19])
    except ValueError:
        return str(ts)[:10]
    s = max(((now or datetime.now()) - t).total_seconds(), 0)
    return f"{int(s)}s ago" if s < 90 else f"{int(s // 60)}m ago" if s < 5400 else f"{int(s // 3600)}h ago" if s < 172800 else f"{int(s // 86400)}d ago"


def _img(svg: str, w: int, h: int) -> str:
    """Inline <svg> gets stripped by Streamlit's HTML sanitiser; a data-URI <img> survives."""
    return f'<img width="{w}" height="{h}" style="display:block" src="data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}">'


def spark_svg(values, color=ACCENT, w=74, h=26) -> str:
    v = [float(x) for x in values if x is not None]
    if len(v) < 2 or max(v) == min(v) == 0:
        return ""
    lo, hi = min(v), max(v)
    rng = (hi - lo) or 1.0
    pts = " ".join(f"{i * (w - 2) / (len(v) - 1) + 1:.1f},{h - 2 - (x - lo) / rng * (h - 4):.1f}" for i, x in enumerate(v))
    return _img(f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg"><polygon points="1,{h} {pts} {w - 1},{h}" fill="{color}" opacity=".13"/>'
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/></svg>', w, h)


def pill(text, kind="", live=False) -> str:
    dot = '<span class="dot live"></span>' if live else ""
    return f'<span class="pill {kind}">{dot}{esc(text)}</span>'


def chip(text, kind="mut") -> str:
    return f'<span class="chip {kind}">{esc(text)}</span>'


def topbar(pills: list[str], as_of: str) -> str:
    return ('<div class="tp-top"><div class="tp-logo" style="display:flex;align-items:center;gap:9px">' + mark_img(30) + esc(NAME) + '</div>' + "".join(pills) +
            f'<span class="tp-spacer"></span><span class="tp-meta">Updated {esc(as_of)}</span></div>')


def tape(items: list[dict]) -> str:
    if not items:
        return '<div class="tape"><div class="tape-track"><span class="ti mut">No activity yet. Press Run pipeline or start the extension.</span></div></div>'
    cells = "".join(f'<span class="ti">{chip(i["status"].replace("_", " ").upper(), STATUS_KIND.get(i["status"], "mut"))}'
                    f'<b>{esc(i["title"])}</b><span class="mut">@ {esc(i["company"])}</span><span class="mut">· {esc(i["src"])}</span></span>' for i in items[:20])
    return f'<div class="tape"><div class="tape-track" style="--dur:{max(40, len(items) * 5)}s">{cells}{cells}</div></div>'


def kpi(label: str, value: str, sub: str = "", spark=None, color=ACCENT, cls: str = "", progress: float | None = None) -> str:
    bar = f'<div class="bar"><i style="width:{max(0, min(progress, 1)) * 100:.0f}%"></i></div>' if progress is not None else ""
    return f'<div class="kpi"><div class="l">{esc(label)}</div><div class="v {cls}">{value}</div><div class="s">{sub}</div>{bar}{spark_svg(spark, color) if spark else ""}</div>'


def panel(title: str, body: str, sub: str = "", height: int | None = None) -> str:
    style = f' style="max-height:{height}px"' if height else ""
    return f'<div class="panel"><h4>{esc(title)}<span class="mut" style="text-transform:none;letter-spacing:0">{esc(sub)}</span></h4><div class="scroll"{style}>{body}</div></div>'


def feed(items: list[dict]) -> str:
    if not items:
        return '<div class="empty">Nothing yet.</div>'
    return "".join(f'<div class="feed">{chip(i["status"].replace("_", " "), STATUS_KIND.get(i["status"], "mut"))} <b>{esc(i["title"])}</b> '
                   f'<span class="mut">@ {esc(i["company"])}</span><div class="t">{esc(i["src"])} · {ago(i["t"])}</div></div>' for i in items)


def _score_chip(score) -> str:
    if isinstance(score, (int, float)) and score == score:
        return chip(f"{score:.0f}%", "up")
    return ""


def board(cols: dict[str, list[dict]], totals: dict[str, int]) -> str:
    labels = {"ready": "Ready", "needs_review": "Needs review", "applied": "Applied", "interview": "Interview", "offer": "Offer"}
    out = []
    for s, cards in cols.items():
        parts = []
        for c in cards:
            parts.append(
                '<div class="card"><b>' + esc(c["title"]) + '</b><div class="mut">' + esc(c["company"]) + '</div><div class="m">'
                + chip(c["src"] or "-", "accent") + _score_chip(c["score"])
                + "<span>#" + c["kind"][0] + str(c["id"]) + " · " + ago(c["when"]) + "</span></div></div>")
        body = "".join(parts) or '<div class="empty">Empty</div>'
        more = ""
        if totals[s] > len(cards):
            more = '<div class="mut" style="font-size:11px;text-align:center">+' + str(totals[s] - len(cards)) + " more</div>"
        out.append('<div class="col"><h5><span>' + labels[s] + "</span><span>" + str(totals[s]) + "</span></h5>" + body + more + "</div>")
    return '<div class="board">' + "".join(out) + "</div>"


def sb_brand() -> str:
    return f'<div class="sb-brand">{mark_img(40)}<div><div class="n">{esc(NAME)}</div><div class="t">{esc(TAGLINE)}</div></div></div>'


def ring_svg(frac: float, size: int = 54, color: str = ACCENT) -> str:
    r, c = 21, 2 * 3.14159 * 21
    frac = max(0.0, min(frac, 1.0))
    return _img(f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 54 54"><circle cx="27" cy="27" r="{r}" fill="none" stroke="{BORDER}" stroke-width="6"/>'
            f'<circle cx="27" cy="27" r="{r}" fill="none" stroke="{color}" stroke-width="6" stroke-linecap="round" stroke-dasharray="{c * frac:.1f} {c:.1f}" transform="rotate(-90 27 27)"/></svg>', size, size)


def sb_today(done: int, limit: int) -> str:
    frac = done / limit if limit else 0
    return (f'<div class="sb-card"><div class="l">Today</div><div class="sb-ring">{ring_svg(frac)}<div><div class="v">{done}<span class="mut" style="font-size:14px"> / {limit}</span></div>'
            f'<div class="s">jobs processed</div></div></div></div>')


def sb_stats(rows: list[tuple[str, str, str]]) -> str:
    body = "".join(f'<div class="sb-row"><span>{esc(lbl)}</span><b class="{cls}">{esc(val)}</b></div>' for lbl, val, cls in rows)
    return f'<div class="sb-card"><div class="l" style="margin-bottom:4px">Pipeline</div>{body}</div>'
