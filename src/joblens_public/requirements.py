"""Typed, alias-aware assessment of job requirements against approved evidence.

The old gap report asked whether *any* token of a requirement appeared anywhere
in the evidence. A generic word such as "experience" therefore made an
unrelated requirement look covered, while a canonical alias such as
``Postgres`` did not count for ``PostgreSQL``.

This module decomposes each requirement into distinctive elements:

* a technology, matched through the closed vocabulary and its aliases;
* an explicit tenure claim, matched only against an explicitly stated number
  of years or months (never derived from employment dates);
* the qualifier ``production``;
* the remaining content terms.

Each element must be stated by the evidence. The state is ``covered`` when
every element is evidenced, ``partial`` when some are, and ``uncovered`` when
none are. The same function drives the draft's gap list and the decision
report, so the two cannot disagree.

Nothing here reads a job posting as a source of candidate facts. A posting can
only create requirements; evidence always comes from approved facts or
source-backed provisional facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable, Mapping, Sequence

from joblens_public.profile.lexicon import SKILL_TERMS

#: Coverage states.
COVERED = "covered"
PARTIAL = "partial"
UNCOVERED = "uncovered"

#: Requirement importance, derived from the posting section it came from.
REQUIRED = "required"
PREFERRED = "preferred"
RESPONSIBILITY = "responsibility"
TECHNOLOGY = "technology"

#: Importance values that belong in the user-facing gap list. A responsibility
#: is context for ranking, not a qualification the candidate must hold.
_GAP_IMPORTANCE = frozenset({REQUIRED, PREFERRED, TECHNOLOGY})

#: Words that say nothing about whether a distinctive element is held. They are
#: removed before content terms are compared. "Experience" is the word that
#: caused the original false-coverage defect.
_STOPWORDS = frozenset(
    {
        "a",
        "ability",
        "able",
        "about",
        "above",
        "advanced",
        "an",
        "and",
        "applicant",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "bonus",
        "by",
        "can",
        "candidate",
        "could",
        "deep",
        "demonstrated",
        "desired",
        "do",
        "does",
        "e",
        "etc",
        "excellent",
        "experience",
        "experienced",
        "extensive",
        "familiar",
        "familiarity",
        "for",
        "from",
        "good",
        "great",
        "had",
        "has",
        "have",
        "ideal",
        "in",
        "including",
        "is",
        "it",
        "its",
        "job",
        "knowledge",
        "may",
        "might",
        "month",
        "months",
        "must",
        "of",
        "on",
        "or",
        "our",
        "plus",
        "position",
        "practical",
        "preferred",
        "proficiency",
        "proficient",
        "proven",
        "related",
        "relevant",
        "required",
        "role",
        "should",
        "skill",
        "skilled",
        "skills",
        "solid",
        "strong",
        "successful",
        "that",
        "the",
        "their",
        "these",
        "they",
        "this",
        "those",
        "to",
        "understanding",
        "us",
        "use",
        "used",
        "using",
        "we",
        "will",
        "with",
        "work",
        "worked",
        "working",
        "would",
        "year",
        "years",
        "you",
        "your",
    }
)

#: Irregular verb forms that appear in resume wording. They are mapped to the
#: base form so "built" matches "build" without a general stemmer.
_IRREGULAR = {
    "began": "begin",
    "bought": "buy",
    "brought": "bring",
    "built": "build",
    "came": "come",
    "chose": "choose",
    "cut": "cut",
    "drove": "drive",
    "found": "find",
    "gave": "give",
    "got": "get",
    "grew": "grow",
    "held": "hold",
    "kept": "keep",
    "led": "lead",
    "lost": "lose",
    "made": "make",
    "meant": "mean",
    "met": "meet",
    "paid": "pay",
    "ran": "run",
    "rose": "rise",
    "said": "say",
    "sat": "sit",
    "saw": "see",
    "sent": "send",
    "set": "set",
    "sold": "sell",
    "spent": "spend",
    "stood": "stand",
    "took": "take",
    "told": "tell",
    "understood": "understand",
    "went": "go",
    "won": "win",
    "wrote": "write",
    "written": "write",
}

#: Requirement-side technologies that are not part of the profile proposal
#: vocabulary (adding them there would let a stray "go live" become a skill).
_REQUIREMENT_TECHNOLOGIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("golang", ("golang", "go")),
    ("dbt", ("dbt",)),
    ("kafka", ("kafka",)),
    ("apache spark", ("apache spark", "spark", "pyspark")),
)

_TENURE_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s*\+?\s*(years?|yrs?|months?|mos?)\b", re.IGNORECASE
)
_PRODUCTION_RE = re.compile(r"\bproduction\b", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-z0-9]+")
_SHORT_ALPHA_LIMIT = 3


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _alias_table() -> dict[str, tuple[str, ...]]:
    aliases: dict[str, list[str]] = {}
    for canonical, surface, _unambiguous in SKILL_TERMS:
        aliases.setdefault(canonical, [])
        if surface not in aliases[canonical]:
            aliases[canonical].append(surface)
    for canonical, surfaces in _REQUIREMENT_TECHNOLOGIES:
        aliases.setdefault(canonical, [])
        for surface in surfaces:
            if surface not in aliases[canonical]:
                aliases[canonical].append(surface)
    return {
        canonical: tuple(sorted(set(surfaces), key=lambda item: (-len(item), item)))
        for canonical, surfaces in aliases.items()
    }


_ALIASES = _alias_table()
_SURFACES = tuple(
    sorted(
        (
            (canonical, surface)
            for canonical, surfaces in _ALIASES.items()
            for surface in surfaces
        ),
        key=lambda item: (-len(item[1]), item[1], item[0]),
    )
)


@lru_cache(maxsize=None)
def _surface_pattern(surface: str) -> re.Pattern[str]:
    """Match a technology surface as a token, never as a substring.

    A short alphabetic alias such as ``go`` must not match inside
    ``go-to-market``. Longer surfaces keep ordinary token boundaries so a
    genuinely hyphenated term such as ``scikit-learn`` still works.
    """
    plural = (
        "s?"
        if surface[-1:].isalnum() and not surface.casefold().endswith("s")
        else ""
    )
    if len(surface) <= _SHORT_ALPHA_LIMIT and surface.isalpha():
        tail = r"(?![A-Za-z0-9]|-[A-Za-z])"
    else:
        tail = r"(?![A-Za-z0-9])"
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(surface) + plural + tail, re.I)


def _technology_spans(text: str) -> list[tuple[int, int, str]]:
    """Return non-overlapping (start, end, canonical) technology mentions."""
    found: list[tuple[int, int, str]] = []
    for canonical, surface in _SURFACES:
        for match in _surface_pattern(surface).finditer(text):
            start, end = match.span()
            if any(start < other_end and other_start < end for other_start, other_end, _ in found):
                continue
            found.append((start, end, canonical))
    return sorted(found)


def _strip_spans(text: str, spans: Iterable[tuple[int, int, str]]) -> str:
    characters = list(text)
    for start, end, _ in spans:
        for index in range(start, end):
            characters[index] = " "
    return "".join(characters)


def technologies_in(text: str) -> tuple[str, ...]:
    """Canonical technologies named in ``text``, in first-appearance order."""
    return tuple(dict.fromkeys(canonical for _, _, canonical in _technology_spans(text)))


def _mentions_technology(text: str, canonical: str) -> bool:
    return any(
        _surface_pattern(surface).search(text) is not None
        for surface in _ALIASES.get(canonical, (canonical,))
    )


def _stem(token: str) -> str:
    token = token.casefold()
    if token in _IRREGULAR:
        token = _IRREGULAR[token]
    if len(token) > 4 and token.endswith("ies"):
        token = token[:-3] + "y"
    elif len(token) > 4 and token.endswith(("ches", "shes", "sses", "xes", "zes")):
        token = token[:-2]
    elif len(token) > 4 and token.endswith("ing"):
        token = token[:-3]
    elif len(token) > 4 and token.endswith("ed"):
        token = token[:-2]
    elif len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        token = token[:-1]
    if len(token) > 3 and token.endswith("e"):
        token = token[:-1]
    return token


_STOPWORD_STEMS = frozenset(_stem(word) for word in _STOPWORDS) | _STOPWORDS


def _content_tokens(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for raw in _WORD_RE.findall(text.casefold()):
        if len(raw) < 2 or raw.isdigit():
            continue
        stem = _stem(raw)
        if len(stem) < 2 or stem in _STOPWORD_STEMS:
            continue
        if stem not in tokens:
            tokens.append(stem)
    return tuple(tokens)


_DISPLAY_ACRONYMS = frozenset({"sql", "aws", "gcp", "api", "ml", "ai", "nlp", "etl", "ci", "cd"})


def _display_technology(canonical: str) -> str:
    special = {
        "postgresql": "PostgreSQL",
        "dbt": "dbt",
        "javascript": "JavaScript",
        "typescript": "TypeScript",
        "node.js": "Node.js",
        "rest api": "REST API",
        "ci/cd": "CI/CD",
        "c++": "C++",
        "c#": "C#",
        "scikit-learn": "scikit-learn",
        "graphql": "GraphQL",
        "grpc": "gRPC",
        "mysql": "MySQL",
        "mongodb": "MongoDB",
        "sqlite": "SQLite",
        "bigquery": "BigQuery",
        "power bi": "Power BI",
        "tailwind css": "Tailwind CSS",
        "github actions": "GitHub Actions",
        "apache spark": "Apache Spark",
        "pytorch": "PyTorch",
        "tensorflow": "TensorFlow",
    }
    if canonical in special:
        return special[canonical]
    return " ".join(
        word.upper() if word in _DISPLAY_ACRONYMS else word[:1].upper() + word[1:]
        for word in canonical.split()
    )


@dataclass(frozen=True)
class Element:
    """One distinctive piece of a requirement."""

    kind: str
    key: str
    label: str


@dataclass(frozen=True)
class Requirement:
    """A requirement decomposed into independently checkable elements."""

    requirement_id: str
    text: str
    importance: str
    elements: tuple[Element, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "requirement": self.text,
            "importance": self.importance,
            "elements": [
                {"kind": element.kind, "key": element.key, "label": element.label}
                for element in self.elements
            ],
        }


@dataclass(frozen=True)
class RequirementAssessment:
    """The coverage state of one requirement against a set of evidence."""

    requirement: Requirement
    state: str
    evidenced: tuple[Element, ...] = ()
    missing: tuple[Element, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement.requirement_id,
            "requirement": self.requirement.text,
            "importance": self.requirement.importance,
            "state": self.state,
            "elements": [
                {"kind": element.kind, "key": element.key, "label": element.label}
                for element in self.requirement.elements
            ],
            "evidenced": [element.label for element in self.evidenced],
            "missing": [element.label for element in self.missing],
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "RequirementAssessment":
        if not isinstance(payload, Mapping):
            raise ValueError("a requirement assessment must be an object")
        text = str(payload.get("requirement", ""))
        importance = str(payload.get("importance", TECHNOLOGY))
        state = str(payload.get("state", UNCOVERED))
        if state not in (COVERED, PARTIAL, UNCOVERED):
            raise ValueError("invalid coverage state")
        elements = payload.get("elements", ())
        parsed: list[Element] = []
        if isinstance(elements, Sequence) and not isinstance(elements, (str, bytes)):
            for item in elements:
                if isinstance(item, Mapping):
                    parsed.append(
                        Element(
                            str(item.get("kind", "content")),
                            str(item.get("key", "")),
                            str(item.get("label", "")),
                        )
                    )
        evidenced_labels = set()
        raw_evidenced = payload.get("evidenced", ())
        if isinstance(raw_evidenced, Sequence) and not isinstance(raw_evidenced, (str, bytes)):
            evidenced_labels = {str(item) for item in raw_evidenced}
        requirement = Requirement(
            requirement_id=str(payload.get("requirement_id", "")),
            text=text,
            importance=importance,
            elements=tuple(parsed),
        )
        evidenced = tuple(element for element in parsed if element.label in evidenced_labels)
        missing = tuple(element for element in parsed if element.label not in evidenced_labels)
        return cls(requirement=requirement, state=state, evidenced=evidenced, missing=missing)


def _tenure_months(match: re.Match[str]) -> int:
    amount = int(match.group(1))
    unit = match.group(2).casefold()
    if unit.startswith("year") or unit.startswith("yr"):
        return amount * 12
    return amount


def _elements(text: str) -> tuple[Element, ...]:
    spans = _technology_spans(text)
    elements: list[Element] = []
    for canonical in dict.fromkeys(canonical for _, _, canonical in spans):
        elements.append(Element("technology", canonical, _display_technology(canonical)))

    remainder = _strip_spans(text, spans)

    for match in _TENURE_RE.finditer(remainder):
        months = _tenure_months(match)
        elements.append(Element("tenure", f"months:{months}", match.group(0).strip()))
    remainder = _TENURE_RE.sub(" ", remainder)

    if _PRODUCTION_RE.search(remainder):
        elements.append(Element("qualifier", "production", "production"))
    remainder = _PRODUCTION_RE.sub(" ", remainder)

    for token in _content_tokens(remainder):
        elements.append(Element("content", token, token))

    # Keep the first occurrence only; a repeated word is one element.
    unique: list[Element] = []
    seen: set[tuple[str, str]] = set()
    for element in elements:
        key = (element.kind, element.key)
        if key in seen:
            continue
        seen.add(key)
        unique.append(element)
    return tuple(unique)


def _requirement(text: str, importance: str, index: int) -> Requirement | None:
    cleaned = " ".join(str(text).split()).strip()
    if not cleaned:
        return None
    elements = _elements(cleaned)
    if not elements:
        return None
    return Requirement(
        requirement_id=f"req_{index:03d}",
        text=cleaned,
        importance=importance,
        elements=elements,
    )


def extract_requirements(job: Any) -> tuple[Requirement, ...]:
    """Extract typed requirements from a parsed (untrusted) job posting.

    Section lines keep their own importance. Technologies that appear only in
    the posting's broader technology list become ``technology`` requirements
    with unknown importance, so an absence is still reported without claiming
    the posting made them essential.
    """
    requirements: list[Requirement] = []
    seen: set[str] = set()

    def add(text: Any, importance: str) -> None:
        key = _normalise(str(text))
        if not key or key in seen:
            return
        requirement = _requirement(str(text), importance, len(requirements) + 1)
        if requirement is None:
            return
        seen.add(key)
        requirements.append(requirement)

    for importance, attribute in (
        (REQUIRED, "required"),
        (PREFERRED, "preferred"),
        (RESPONSIBILITY, "responsibilities"),
    ):
        for line in getattr(job, attribute, ()) or ():
            add(line, importance)

    for technology in getattr(job, "technologies", ()) or ():
        canonical = str(technology).casefold().strip()
        if not canonical:
            continue
        if any(_mentions_technology(requirement.text, canonical) for requirement in requirements):
            continue
        add(canonical, TECHNOLOGY)

    return tuple(requirements)


def _evidence_tokens(evidence_texts: Sequence[str]) -> set[str]:
    tokens: set[str] = set()
    for text in evidence_texts:
        for raw in _WORD_RE.findall(str(text).casefold()):
            if len(raw) >= 2 and not raw.isdigit():
                tokens.add(_stem(raw))
    return tokens


def _element_evidenced(
    element: Element,
    evidence_texts: Sequence[str],
    evidence_tokens: set[str],
    evidence_tenure_months: int,
) -> bool:
    if element.kind == "technology":
        return any(
            _mentions_technology(text, element.key) for text in evidence_texts
        )
    if element.kind == "tenure":
        return evidence_tenure_months >= int(element.key.split(":", 1)[1])
    # Qualifiers and content terms are token matches.
    return element.key in evidence_tokens


def assess_requirement(
    requirement: Requirement, evidence_texts: Sequence[str]
) -> RequirementAssessment:
    """Assess one requirement against a list of evidence strings.

    Each string is a source-backed statement: an approved fact label, a quoted
    span, or a provisional fact's evidence. Evidence strings are never joined
    into a candidate fact; they are only searched.
    """
    texts = [str(text) for text in evidence_texts if str(text).strip()]
    tokens = _evidence_tokens(texts)
    tenure = max((_tenure_months(match) for text in texts for match in _TENURE_RE.finditer(text)), default=0)
    evidenced: list[Element] = []
    missing: list[Element] = []
    for element in requirement.elements:
        if _element_evidenced(element, texts, tokens, tenure):
            evidenced.append(element)
        else:
            missing.append(element)
    if not missing:
        state = COVERED
    elif not evidenced:
        state = UNCOVERED
    else:
        state = PARTIAL
    return RequirementAssessment(
        requirement=requirement,
        state=state,
        evidenced=tuple(evidenced),
        missing=tuple(missing),
    )


def assess_requirements(
    job: Any, evidence_texts: Sequence[str]
) -> tuple[RequirementAssessment, ...]:
    """Assess every extracted requirement against the same evidence."""
    return tuple(
        assess_requirement(requirement, evidence_texts)
        for requirement in extract_requirements(job)
    )


def is_gap(assessment: RequirementAssessment) -> bool:
    """True when the requirement is not fully met and belongs in the gap list."""
    return (
        assessment.state != COVERED
        and assessment.requirement.importance in _GAP_IMPORTANCE
    )


def gap_requirements(
    assessments: Sequence[RequirementAssessment],
) -> tuple[str, ...]:
    """Requirement texts that are partly or wholly unsupported."""
    return tuple(
        assessment.requirement.text for assessment in assessments if is_gap(assessment)
    )


def coverage_states(
    assessments: Sequence[RequirementAssessment],
) -> dict[str, str]:
    """Map a requirement identifier to its aggregate state."""
    return {
        assessment.requirement.requirement_id: assessment.state
        for assessment in assessments
    }


__all__ = [
    "COVERED",
    "PARTIAL",
    "PREFERRED",
    "REQUIRED",
    "RESPONSIBILITY",
    "TECHNOLOGY",
    "UNCOVERED",
    "Element",
    "Requirement",
    "RequirementAssessment",
    "assess_requirement",
    "assess_requirements",
    "coverage_states",
    "extract_requirements",
    "gap_requirements",
    "is_gap",
    "technologies_in",
]
