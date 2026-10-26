"""Text utilities for the reconciliation layer.

These helpers read the extracted text of a segment and locate the pieces the
claim extractors need. They never invent a value: a pattern that is not
present simply produces nothing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from joblens_public.profile.lexicon import (
    DEGREE_LEVELS,
    LANGUAGE_TERMS,
    SECTION_HEADINGS,
    SKILL_TERMS,
)

__all__ = [
    "Line",
    "iter_lines",
    "language_mentions",
    "match_heading",
    "normalise",
    "normalise_heading",
    "StatementValues",
    "parse_date_range",
    "parse_degree",
    "parse_duration",
    "parse_statement",
    "role_titles",
    "role_variants",
    "skill_mentions",
    "split_title",
    "strip_bullet",
]

#: Prefixes that express a level of seniority, not a different role.
SENIORITY_PREFIXES = ("senior ", "lead ", "principal ", "staff ", "junior ", "associate ")

#: Role nouns used to recognise a job title inside a sentence.
ROLE_NOUNS = (
    "administrator",
    "analyst",
    "architect",
    "consultant",
    "coordinator",
    "designer",
    "developer",
    "director",
    "engineer",
    "executive",
    "founder",
    "manager",
    "officer",
    "operator",
    "partner",
    "researcher",
    "scientist",
    "specialist",
    "supervisor",
    "technician",
)

#: Verbs that open a responsibility or an achievement.
ACTION_VERBS = (
    "automated",
    "built",
    "created",
    "cut",
    "designed",
    "developed",
    "doubled",
    "grew",
    "implemented",
    "improved",
    "increased",
    "launched",
    "led",
    "maintained",
    "managed",
    "migrated",
    "reduced",
    "refactored",
    "scaled",
    "shipped",
    "wrote",
)

_BULLETS = ("•", "▪", "‣", "-", "–", "—", "*", "·")
_TITLE_SEPARATORS = (" — ", " – ", " - ", " | ", ": ", " · ")

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_SKILL_SURFACES: dict[str, list[str]] = {}
_SKILL_LOOKUP: dict[str, str] = {}
for _canonical, _surface, _unambiguous in SKILL_TERMS:
    _SKILL_SURFACES.setdefault(_canonical, []).append(_surface)
    _SKILL_LOOKUP[_surface.casefold()] = _canonical

_SKILL_PATTERNS: dict[str, re.Pattern[str]] = {
    canonical: re.compile(
        r"(?<![A-Za-z0-9+#.])(?:"
        + "|".join(
            re.escape(surface)
            for surface in sorted(set(surfaces), key=len, reverse=True)
        )
        + r")(?![A-Za-z0-9+#])",
        re.IGNORECASE,
    )
    for canonical, surfaces in _SKILL_SURFACES.items()
}

_LANGUAGE_SURFACES: dict[str, list[str]] = {}
_LANGUAGE_LOOKUP: dict[str, str] = {}
for _canonical, _surface in LANGUAGE_TERMS:
    _LANGUAGE_SURFACES.setdefault(_canonical, []).append(_surface)
    _LANGUAGE_LOOKUP[_surface.casefold()] = _canonical

_LANGUAGE_PATTERNS: dict[str, re.Pattern[str]] = {
    canonical: re.compile(
        r"(?<![A-Za-z0-9])(?:"
        + "|".join(
            re.escape(surface)
            for surface in sorted(set(surfaces), key=len, reverse=True)
        )
        + r")(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    for canonical, surfaces in _LANGUAGE_SURFACES.items()
}

_DATE_TOKEN = r"(?:19|20)\d{2}"
_MONTH_YEAR = r"(?:" + "|".join(sorted(_MONTHS)) + r")\.?\s+" + _DATE_TOKEN
_YEAR_MONTH = _DATE_TOKEN + r"\s*(?:" + "|".join(sorted(_MONTHS)) + r")\.?"

_RANGE_PATTERNS = (
    re.compile(
        rf"(?P<start>{_MONTH_YEAR}|{_YEAR_MONTH}|{_DATE_TOKEN})\s*"
        rf"(?:-|–|—|to|until)\s*"
        rf"(?P<end>{_MONTH_YEAR}|{_YEAR_MONTH}|{_DATE_TOKEN}|present|current|now)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?P<start>{_MONTH_YEAR}|{_YEAR_MONTH}|{_DATE_TOKEN})\s+"
        rf"(?P<end>{_MONTH_YEAR}|{_YEAR_MONTH}|{_DATE_TOKEN})",
        re.IGNORECASE,
    ),
)

_DURATION_PATTERN = re.compile(
    r"(?P<years>\d+)\s*(?:\+\s*)?years?"
    r"(?:\s*(?P<months>\d+)\s*months?)?"
    r"|(?P<only_months>\d+)\s*months?",
    re.IGNORECASE,
)

_QUANTITY_PATTERN = re.compile(
    r"\d[\d,.]*\s*(?:%|percent|percentage points?|k|m|bn|x)?",
    re.IGNORECASE,
)

_ROLE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    + "|".join(sorted(ROLE_NOUNS, key=len, reverse=True))
    + r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)

_DEGREE_SURFACE_LEVEL: dict[str, str] = {}
for _level, _surfaces in DEGREE_LEVELS.items():
    for _surface in _surfaces:
        _DEGREE_SURFACE_LEVEL[_surface.casefold()] = _level
        _DEGREE_SURFACE_LEVEL[_surface.replace(".", "").casefold()] = _level

_DEGREE_ALTERNATION = "|".join(
    re.escape(surface)
    for surface in sorted(_DEGREE_SURFACE_LEVEL, key=lambda value: (-len(value), value))
)

_FIELD_WORD = r"[A-Za-z][A-Za-z&/'\-]*"
_DEGREE_AFTER = re.compile(
    rf"(?P<level>{_DEGREE_ALTERNATION})\s+(?:degree\s+)?(?:in|of)\s+"
    rf"(?P<field>{_FIELD_WORD}(?:\s+{_FIELD_WORD}){{0,5}})",
    re.IGNORECASE,
)
_DEGREE_BEFORE = re.compile(
    rf"(?P<field>{_FIELD_WORD}(?:\s+{_FIELD_WORD}){{0,3}})\s*[,;]\s*"
    rf"(?P<level>{_DEGREE_ALTERNATION})\b",
    re.IGNORECASE,
)

_INSTITUTION_WORDS = frozenset(
    {
        "academy",
        "college",
        "institute",
        "school",
        "universidad",
        "universidade",
        "universita",
        "universitat",
        "universite",
        "universität",
        "university",
    }
)


@dataclass(frozen=True)
class Line:
    """A line of a segment, with the offsets of the line in the segment."""

    start: int
    end: int
    text: str


def iter_lines(text: str) -> list[Line]:
    """Split a segment into lines, keeping the offsets of each line."""
    lines: list[Line] = []
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        stripped = raw_line.rstrip("\r\n")
        lines.append(Line(start=offset, end=offset + len(stripped), text=stripped))
        offset += len(raw_line)
    if not lines and text:
        lines.append(Line(start=0, end=len(text), text=text))
    return lines


def normalise(text: str) -> str:
    """Lower case, single spaces, trimmed."""
    return " ".join(text.split()).casefold()


def normalise_heading(text: str) -> str:
    cleaned = text.strip().strip("*•▪‣-–— ")
    cleaned = cleaned.replace("&", " and ")
    cleaned = cleaned.rstrip(":").strip()
    return " ".join(cleaned.split()).casefold()


def match_heading(text: str) -> str | None:
    """Return the section kind a line opens, if it is a known heading."""
    normalized = normalise_heading(text)
    if not normalized or len(normalized) > 40:
        return None
    return SECTION_HEADINGS.get(normalized)


def strip_bullet(text: str) -> tuple[str, int]:
    """Remove a leading bullet marker and report where the text starts."""
    leading = len(text) - len(text.lstrip())
    stripped = text[leading:]
    for bullet in _BULLETS:
        if stripped.startswith(bullet):
            remainder = stripped[len(bullet):]
            if remainder[:1] in {" ", ""}:
                trimmed = remainder.lstrip()
                return trimmed, leading + len(bullet) + (len(remainder) - len(trimmed))
    return stripped, leading


def split_title(text: str) -> tuple[str, str] | None:
    """Split a line into its leading title and the remainder."""
    cleaned, _ = strip_bullet(text)
    if not cleaned:
        return None
    position = -1
    separator = ""
    for candidate in _TITLE_SEPARATORS:
        found = cleaned.find(candidate)
        if found >= 0 and (position < 0 or found < position):
            position = found
            separator = candidate
    if position < 0:
        return cleaned.strip(), ""
    return cleaned[:position].strip(), cleaned[position + len(separator):].strip()


def _normalise_date(text: str) -> str:
    """Normalise a date token to ``YYYY`` or ``YYYY-MM``."""
    cleaned = text.strip().rstrip(".")
    month_match = re.match(rf"^({_DATE_TOKEN})\s*([A-Za-z]+)$", cleaned)
    if month_match:
        month = _MONTHS.get(month_match.group(2).casefold())
        if month:
            return f"{month_match.group(1)}-{month:02d}"
    name_match = re.match(rf"^([A-Za-z]+)\.?\s+({_DATE_TOKEN})$", cleaned)
    if name_match:
        month = _MONTHS.get(name_match.group(1).casefold())
        if month:
            return f"{name_match.group(2)}-{month:02d}"
    year_match = re.match(rf"^({_DATE_TOKEN})$", cleaned)
    if year_match:
        return year_match.group(1)
    return normalise(cleaned)


def parse_date_range(text: str) -> tuple[str | None, str | None]:
    """Return the normalised start and end of a period stated in the text."""
    for pattern in _RANGE_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        start = _normalise_date(match.group("start"))
        end_token = match.group("end")
        if end_token.casefold() in {"present", "current", "now"}:
            return start, "present"
        return start, _normalise_date(end_token)
    single = re.search(rf"\b({_MONTH_YEAR}|{_YEAR_MONTH}|{_DATE_TOKEN})\b", text)
    if single is not None:
        return _normalise_date(single.group(1)), None
    return None, None


def parse_duration(text: str) -> tuple[int, bool] | None:
    """Return a duration in months and whether it is an exact figure.

    A figure written as "5+ years" is a lower bound, so it is not exact.
    """
    match = _DURATION_PATTERN.search(text)
    if match is None:
        return None
    exact = "+" not in match.group(0)
    if match.group("only_months"):
        return int(match.group("only_months")), exact
    years = int(match.group("years"))
    months = int(match.group("months") or 0)
    return years * 12 + months, exact


@dataclass(frozen=True)
class StatementValues:
    """The template of a statement and the values it states.

    ``template`` keeps the wording and replaces every numeric quantity and
    every named technology with a placeholder, so two statements with the same
    template state the same thing with different values. ``quantities`` holds
    only genuine numeric quantities; ``technologies`` holds the technologies
    the statement names. The two are never mixed: a technology is not a
    measurement, and a measurement is not a technology.
    """

    template: str
    quantities: tuple[str, ...]
    technologies: tuple[str, ...]


def parse_statement(text: str) -> StatementValues:
    """Split a statement into its template, quantities and technologies.

    Overlapping matches keep the longest one, so ``python3`` is read as the
    technology ``python3`` and never as the quantity ``3``.
    """
    matches: list[tuple[int, int, str, str]] = []
    for match in _QUANTITY_PATTERN.finditer(text):
        matches.append((match.start(), match.end(), "quantity", normalise(match.group(0))))
    for name, pattern in _SKILL_PATTERNS.items():
        for match in pattern.finditer(text):
            canonical = _SKILL_LOOKUP.get(match.group(0).casefold(), name)
            matches.append((match.start(), match.end(), "technology", canonical))
    matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))

    parts: list[str] = []
    quantities: list[str] = []
    technologies: list[str] = []
    cursor = 0
    for start, end, kind, value in matches:
        if start < cursor:
            continue
        parts.append(text[cursor:start])
        parts.append("#")
        if kind == "quantity":
            quantities.append(value)
        elif value not in technologies:
            technologies.append(value)
        cursor = end
    parts.append(text[cursor:])
    return StatementValues(
        template=normalise("".join(parts)),
        quantities=tuple(quantities),
        technologies=tuple(technologies),
    )


def role_variants(role: str) -> set[str]:
    """Return the base role and its variants with a seniority prefix."""
    normalized = normalise(role)
    variants = {normalized}
    for prefix in SENIORITY_PREFIXES:
        if normalized.startswith(prefix):
            variants.add(normalized[len(prefix):])
            variants.add(prefix.strip() + " " + normalized[len(prefix):])
    return variants


def role_titles(text: str) -> list[str]:
    """Return the role titles a text names, in order of appearance."""
    titles: list[str] = []
    for match in _ROLE_PATTERN.finditer(text):
        title = normalise(match.group(0))
        if title not in titles:
            titles.append(title)
    return titles


def skill_mentions(text: str) -> list[tuple[str, int, int]]:
    """Return the skills a text names, with the offsets of every mention."""
    found: list[tuple[str, int, int]] = []
    for canonical, pattern in _SKILL_PATTERNS.items():
        for match in pattern.finditer(text):
            name = _SKILL_LOOKUP.get(match.group(0).casefold(), canonical)
            found.append((name, match.start(), match.end()))
    found.sort(key=lambda item: (item[1], item[2]))
    return found


def language_mentions(text: str) -> list[tuple[str, int, int]]:
    """Return the languages a text names, with the offsets of every mention."""
    found: list[tuple[str, int, int]] = []
    for canonical, pattern in _LANGUAGE_PATTERNS.items():
        for match in pattern.finditer(text):
            name = _LANGUAGE_LOOKUP.get(match.group(0).casefold(), canonical)
            found.append((name, match.start(), match.end()))
    found.sort(key=lambda item: (item[1], item[2]))
    return found


def parse_degree(text: str) -> tuple[str, str] | None:
    """Return the degree level and the subject a text states.

    Only an explicit degree statement is read. The subject stops before an
    institution name.
    """
    for pattern in (_DEGREE_AFTER, _DEGREE_BEFORE):
        match = pattern.search(text)
        if match is None:
            continue
        surface = match.group("level").casefold()
        level = _DEGREE_SURFACE_LEVEL.get(surface) or _DEGREE_SURFACE_LEVEL.get(
            surface.replace(".", "")
        )
        if level is None:
            continue
        kept: list[str] = []
        for word in normalise(match.group("field")).split():
            if word in _INSTITUTION_WORDS:
                break
            kept.append(word)
            if len(kept) >= 4:
                break
        field = " ".join(kept).strip(" ,;:-")
        if not field or field.split()[0] in {"of", "in", "at", "and", "the"}:
            continue
        return level, field
    return None
