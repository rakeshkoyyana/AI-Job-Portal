"""Job-vs-resume analysis: skill extraction, match score, filters. Fully offline/deterministic."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .resume_io import Resume
from .sources.base import Job

# Skill vocabulary (multi-word terms kept intact). Extend freely.
VOCAB: list[str] = sorted(set("""
python,sql,pyspark,spark,scala,java,javascript,typescript,golang,rust,bash,shell scripting,
pandas,numpy,scikit-learn,tensorflow,pytorch,keras,xgboost,lightgbm,hugging face,transformers,
llm,nlp,rag,langchain,openai,prompt engineering,mlops,machine learning,deep learning,
computer vision,statistics,a/b testing,forecasting,feature engineering,
aws,gcp,azure,s3,glue,lambda,iam,redshift,athena,emr,kinesis,sagemaker,bigquery,dataflow,pub/sub,
databricks,snowflake,delta lake,iceberg,hudi,dbt,airflow,dagster,prefect,kafka,flink,nifi,fivetran,
etl,elt,data warehousing,data warehouse,data lake,data modeling,dimensional modeling,data pipelines,
data quality,data governance,data lineage,orchestration,streaming,batch processing,
postgresql,mysql,oracle,sql server,mongodb,dynamodb,cassandra,redis,elasticsearch,neo4j,
docker,kubernetes,terraform,ci/cd,github actions,jenkins,git,linux,rest api,graphql,fastapi,flask,django,
tableau,power bi,looker,superset,streamlit,excel,
pytest,great expectations,observability,datadog,agile,scrum,jira
""".replace("\n", "").split(",")) - {""})

ALIASES = {
    "postgres": "postgresql", "k8s": "kubernetes", "amazon web services": "aws",
    "google cloud": "gcp", "large language model": "llm", "large language models": "llm",
    "llms": "llm", "ml": "machine learning", "natural language processing": "nlp",
    "scikit learn": "scikit-learn", "sklearn": "scikit-learn", "powerbi": "power bi",
    "apache spark": "spark", "apache airflow": "airflow", "apache kafka": "kafka",
    "retrieval augmented generation": "rag", "retrieval-augmented generation": "rag",
    "data pipeline": "data pipelines", "ci cd": "ci/cd", "node": "node.js",
}

_PATTERNS = {t: re.compile(rf"(?<![\w+#.]){re.escape(t)}(?![\w+#])", re.I) for t in VOCAB}
_ALIAS_PATTERNS = {a: (re.compile(rf"(?<![\w+#.]){re.escape(a)}(?![\w+#])", re.I), c) for a, c in ALIASES.items() if c in _PATTERNS}


def find_skills(text: str) -> set[str]:
    found = {t for t, p in _PATTERNS.items() if p.search(text)}
    found |= {canon for p, canon in _ALIAS_PATTERNS.values() if p.search(text)}
    return found


@dataclass
class Analysis:
    score: float
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    required_years: int | None = None
    eligible: bool = True


def required_years(text: str) -> int | None:
    m = re.search(r"(\d{1,2})\s*\+?\s*(?:-\s*\d+\s*)?years?", text, re.I)
    if m and int(m.group(1)) <= 15:
        return int(m.group(1))
    return None


def passes_filters(job: Job, search: dict) -> tuple[bool, str]:
    title = job.title.lower()
    inc, exc = search.get("title_include", []), search.get("title_exclude", [])
    if any(x.lower() in title for x in exc):
        return False, "title excluded"
    if inc and not any(x.lower() in title for x in inc):
        return False, "title not relevant"
    locs = [l.lower() for l in search.get("locations", [])]
    if locs:
        loc = (job.location or "").lower()
        if job.remote and search.get("remote_ok", True):
            return True, "ok"
        if not any(l in loc for l in locs):
            return False, "location mismatch"
    return True, "ok"


def job_from_row(row) -> Job:
    return Job(row["source"], row["external_id"], row["title"] or "", row["company"] or "",
               row["location"] or "", row["url"] or "", row["description"] or "",
               row["posted_at"] or "", bool(row["remote"]), row["apply_url"] or "")


def analyze(job: Job, resume: Resume, search: dict, years: float = 5) -> Analysis:
    jd_skills, cv_skills = find_skills(f"{job.title}\n{job.description}"), find_skills(resume.text)
    matched, missing = sorted(jd_skills & cv_skills), sorted(jd_skills - cv_skills)

    skill_part = (len(matched) / len(jd_skills)) if jd_skills else 0.5
    inc = search.get("title_include") or []
    title_part = 1.0 if (not inc or any(x.lower() in job.title.lower() for x in inc)) else 0.0
    locs = [l.lower() for l in search.get("locations", [])]
    loc_part = 1.0 if (not locs or (job.remote and search.get("remote_ok", True))
                       or any(l in (job.location or "").lower() for l in locs)) else 0.0
    req = required_years(job.description)
    exp_part = 0.8 if req is None else (1.0 if req <= years + 1 else max(0.0, 1 - (req - years) / 5))

    score = round(100 * (0.60 * skill_part + 0.15 * title_part + 0.10 * loc_part + 0.15 * exp_part), 1)
    ok, why = passes_filters(job, search)
    reasons = [f"{len(matched)}/{len(jd_skills)} JD skills on resume"]
    if req:
        reasons.append(f"asks {req}+ yrs (you: {years:g})")
    if not ok:
        reasons.append(f"filtered: {why}")
    return Analysis(score, matched, missing, reasons, req, ok)


# ---------------------------------------------------------------------------
# Requirement extraction beyond the fixed vocabulary + "supported" skills
# ---------------------------------------------------------------------------
# If the resume shows X, these related skills are legitimately evidenced too.
IMPLIES: dict[str, set[str]] = {
    "pyspark": {"spark", "python"}, "databricks": {"spark"}, "glue": {"etl", "aws"}, "s3": {"aws"},
    "lambda": {"aws"}, "iam": {"aws"}, "redshift": {"aws", "data warehousing"}, "athena": {"aws", "sql"},
    "snowflake": {"data warehousing", "sql"}, "bigquery": {"gcp", "sql", "data warehousing"},
    "dbt": {"sql", "elt", "data modeling"}, "airflow": {"orchestration", "data pipelines"},
    "kafka": {"streaming"}, "kinesis": {"streaming", "aws"}, "flink": {"streaming"},
    "pytorch": {"deep learning", "machine learning"}, "tensorflow": {"deep learning", "machine learning"},
    "scikit-learn": {"machine learning"}, "xgboost": {"machine learning"}, "langchain": {"llm"},
    "rag": {"llm", "nlp"}, "transformers": {"nlp", "deep learning"}, "github actions": {"ci/cd", "git"},
    "jenkins": {"ci/cd"}, "terraform": {"ci/cd"}, "etl": {"data pipelines"}, "elt": {"data pipelines"},
    "data warehouse": {"data warehousing"}, "data warehousing": {"data warehouse"},
    "postgresql": {"sql"}, "mysql": {"sql"}, "oracle": {"sql"}, "sql server": {"sql"},
}


def supported_skills(text: str) -> set[str]:
    """Skills present in the text plus skills that are directly implied by what is present."""
    base = find_skills(text)
    out = set(base)
    for s in base:
        out |= IMPLIES.get(s, set())
    return out


_CUES = re.compile(r"(?:experience|proficien\w*|knowledge|familiarity|expertise|skills?|background)\s+(?:with|in|of|using|on)\s+([^.\n;:]{3,160})", re.I)
_LEAD = re.compile(r"^(?:and|or|the|a|an|our|your|strong|solid|deep|good|excellent|proven|hands-on|working|related|similar|other|various|including|such as|e\.g\.?|using)\s+", re.I)
_STOP = {"etc", "more", "years", "year", "a plus", "plus", "related field", "the following", "us", "you", "it", "this", "that"}


def extract_extra_terms(text: str, cap: int = 25) -> set[str]:
    """Skills named in 'experience with X, Y and Z' style requirement sentences (beyond VOCAB)."""
    out: set[str] = set()
    for m in _CUES.finditer(text):
        for part in re.split(r",|/|;| and | or |&|\bsuch as\b|\bincluding\b", m.group(1)):
            t = _LEAD.sub("", part.strip(" ()-:\"'"))
            t = _LEAD.sub("", t).strip().lower()
            t = ALIASES.get(t, t)
            words = t.split()
            if t in _PATTERNS:
                continue                      # already covered by the vocabulary matcher
            if 1 <= len(words) <= 3 and len(t) >= 2 and t not in _STOP and re.search(r"[a-z]", t) and not t.endswith("years"):
                out.add(t)
        if len(out) >= cap:
            break
    return set(sorted(out)[:cap])


_PREF_SPLIT = re.compile(r"(?im)^\W*(preferred|nice[- ]to[- ]have|bonus|good to have|pluses?|desired)\b.*$")


def jd_requirements(text: str) -> tuple[set[str], set[str]]:
    """(required terms, preferred terms) from a job description."""
    m = _PREF_SPLIT.search(text)
    req_text, pref_text = (text[:m.start()], text[m.start():]) if m else (text, "")
    req = find_skills(req_text) | extract_extra_terms(req_text)
    pref = (find_skills(pref_text) | extract_extra_terms(pref_text)) - req
    return req, pref


def has_term(text: str, term: str) -> bool:
    """Is `term` evidenced in `text` (word-boundary match, or implied by a related skill)?"""
    if term in supported_skills(text):
        return True
    return re.search(rf"(?<![\w+#.]){re.escape(term)}(?![\w+#])", text, re.I) is not None


def estimate_years(text: str) -> float | None:
    """Rough total experience from the span of 4-digit years in the text (labelled an estimate everywhere)."""
    import datetime as _dt

    years = [int(y) for y in re.findall(r"\b(19[9]\d|20[0-3]\d)\b", text)]
    years = [y for y in years if y <= _dt.date.today().year]
    if not years:
        return None
    end = _dt.date.today().year if re.search(r"(?i)present|current", text) else max(years)
    return float(max(0, end - min(years)))
