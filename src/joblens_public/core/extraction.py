from __future__ import annotations

import re
from collections.abc import Iterable

from .models import JobPosting

SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "python": ("python",),
    "sql": ("sql",),
    "c++": ("c++", "cpp"),
    "pandas": ("pandas",),
    "numpy": ("numpy",),
    "scikit-learn": ("scikit-learn", "sklearn"),
    "machine learning": ("machine learning", "ml"),
    "deep learning": ("deep learning",),
    "statistics": ("statistics", "statistical"),
    "probability": ("probability",),
    "optimization": ("optimization", "optimisation"),
    "spark": ("spark", "pyspark"),
    "airflow": ("airflow",),
    "dbt": ("dbt",),
    "databricks": ("databricks",),
    "aws": ("aws", "amazon web services"),
    "azure": ("azure",),
    "gcp": ("gcp", "google cloud"),
    "docker": ("docker",),
    "kubernetes": ("kubernetes", "k8s"),
    "git": ("git",),
    "tensorflow": ("tensorflow",),
    "pytorch": ("pytorch",),
    "llm": ("llm", "large language model", "large language models"),
    "nlp": ("nlp", "natural language processing"),
    "rag": ("rag", "retrieval-augmented generation"),
    "classification": ("classification", "classifier"),
    "sentiment analysis": ("sentiment analysis", "sentiment classification"),
    "forecasting": ("forecasting", "forecast", "demand prediction"),
}

PREFERRED_CUES = (
    "nice to have",
    "nice-to-have",
    "preferred",
    "bonus",
    "desirable",
    "a plus",
    "optional",
)
REQUIRED_CUES = ("required", "must have", "must-have", "mandatory", "essential")

BENEFIT_HEADING_RE = re.compile(
    r"^(?:benefits?(?:\s+(?:include|includes|including))?"
    r"(?:\s*(?:&|and)\s*perks?)?|"
    r"perks?(?:\s+(?:include|includes|including))?|what we offer|we offer|"
    r"compensation(?: and benefits)?|training(?: and development)?|"
    r"professional development|learning and development|why join us)"
    r"\s*(?::\s*(.*))?$",
    re.IGNORECASE,
)
BENEFIT_CUE_RE = re.compile(
    r"\b(?:we (?:offer|provide|fund|cover|support)|"
    r"you(?:'ll| will) (?:receive|get|have access to)|"
    r"(?:employer|company)[- ](?:provided|sponsored|funded|paid)|"
    r"(?:on[- ]the[- ]job|paid|internal) training|"
    r"training (?:budget|stipend|program|allowance)|"
    r"learning (?:budget|stipend|allowance)|"
    r"tuition (?:reimbursement|assistance|support)|"
    r"professional development (?:budget|stipend|allowance|funding)|"
    r"(?:benefits?|perks?) (?:include|package|offered|provided|available))\b|"
    r"\b(?:training|learning|development)\b[^.\n]{0,80}"
    r"\b(?:provided|offered|available|covered|funded|reimbursed)\b",
    re.IGNORECASE,
)

PREFERRED_SECTION_RE = re.compile(
    r"^(?:nice[- ]to[- ]have|preferred(?:\s+(?:skills|qualifications))?|bonus|"
    r"desirable(?:\s+(?:skills|qualifications))?|optional(?:\s+skills)?)"
    r"\s*(?::\s*(.*))?$",
    re.IGNORECASE,
)
REQUIRED_SECTION_RE = re.compile(
    r"^(?:requirements?|required(?:\s+(?:skills|qualifications))?|must[- ]have|"
    r"essential(?:\s+(?:skills|qualifications))?|minimum qualifications|"
    r"responsibilities|about the role)\s*(?::\s*(.*))?$",
    re.IGNORECASE,
)

# Check role words as complete words, not substrings of "international",
# "internal", "headquarters" or "leadership".
SENIORITY_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bsenior\b", "senior"),
    (r"\blead\b", "lead"),
    (r"\bprincipal\b", "principal"),
    (r"\bstaff\b", "staff"),
    (r"\bmanager\b", "manager"),
    (r"\bhead\b", "head"),
    (r"\b(?:intern|internship)\b", "intern"),
    (r"\bgraduate\b", "graduate"),
    (r"\bjunior\b", "junior"),
    (r"\bentry(?:[- ]level)?\b", "entry"),
    (r"\bearly[- ]career\b", "entry"),
)

YEARS_RE = re.compile(
    r"(?P<years>\d+)\s*\+?\s*(?:years?|yrs?)\b"
    r"(?:\s+of|['’])?"
    r"(?:\s+[\w/-]+){0,3}\s+experience\b",
    re.IGNORECASE,
)


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def is_benefit_text(text: str) -> bool:
    """True for employer-provided training, perks or benefit statements."""
    return BENEFIT_CUE_RE.search(text) is not None


def _contains_alias(text: str, aliases: Iterable[str]) -> bool:
    lowered = _normalise(text)
    for alias in aliases:
        # Boundaries also prevent "spark" from matching "sparkling".
        pattern = rf"(?<![a-z0-9]){re.escape(alias.lower())}(?![a-z0-9])"
        if re.search(pattern, lowered):
            return True
    return False


def _skill_chunks(description: str) -> list[tuple[str, bool]]:
    """Keep heading context while classifying mixed required/preferred clauses."""
    chunks: list[tuple[str, bool]] = []
    preferred_section = False
    benefit_section = False

    for raw_line in re.split(r"[\n•]+", description):
        line = raw_line.strip().lstrip("-* ").strip()
        if not line:
            continue

        for pattern, section in (
            (BENEFIT_HEADING_RE, "benefit"),
            (PREFERRED_SECTION_RE, "preferred"),
            (REQUIRED_SECTION_RE, "required"),
        ):
            match = pattern.fullmatch(line)
            if match is not None:
                benefit_section = section == "benefit"
                preferred_section = section == "preferred"
                line = (match.group(1) or "").strip()
                break

        if not line:
            continue

        for clause in re.split(r"(?<=[.!?])\s+|[;,]", line):
            chunk = clause.strip()
            if not chunk:
                continue
            # Skills named in an employer benefit or training offer are
            # context, never a candidate requirement.
            if benefit_section or is_benefit_text(chunk):
                continue

            lowered = chunk.lower()
            if any(cue in lowered for cue in PREFERRED_CUES):
                preferred = True
            elif any(cue in lowered for cue in REQUIRED_CUES):
                preferred = False
            else:
                preferred = preferred_section
            chunks.append((chunk, preferred))

    return chunks


def extract_skills(description: str) -> tuple[frozenset[str], frozenset[str]]:
    required: set[str] = set()
    preferred: set[str] = set()

    for chunk, is_preferred in _skill_chunks(description):
        target = preferred if is_preferred else required
        for canonical, aliases in SKILL_ALIASES.items():
            if _contains_alias(chunk, aliases):
                target.add(canonical)

    # If an employer lists a skill in both sections, the mandatory mention wins.
    preferred -= required
    return frozenset(required), frozenset(preferred)


def extract_years_required(description: str) -> int | None:
    matches = [int(match.group("years")) for match in YEARS_RE.finditer(description)]
    return max(matches) if matches else None


def infer_seniority(title: str, description: str = "") -> str | None:
    # Title is more reliable than body text, which often mentions other roles.
    for source in (title, description[:500]):
        for pattern, label in SENIORITY_PATTERNS:
            if re.search(pattern, source, re.IGNORECASE):
                return label
    return None


def extract_job_posting(
    *,
    title: str,
    company: str,
    location: str,
    description: str,
    source_url: str | None = None,
    remote: bool | None = None,
) -> JobPosting:
    required, preferred = extract_skills(description)
    years_required = extract_years_required(description)
    seniority = infer_seniority(title, description)
    is_remote = remote if remote is not None else "remote" in location.lower()

    return JobPosting.build(
        title=title,
        company=company,
        location=location,
        description=description,
        required_skills=required,
        preferred_skills=preferred,
        years_required=years_required,
        seniority=seniority,
        remote=is_remote,
        source_url=source_url,
    )
