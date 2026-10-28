"""Deterministic, evidence-grounded candidate fact proposals.

The engine reads the canonical CV parser response (schema 1.1) as it is
returned by the HTTP transport, and proposes reviewable facts. It never
infers: every proposal points at an exact quotation, and the quotation is
always located by Python string indices inside the source segment.

The engine is conservative by construction:

* Only closed vocabularies are matched. A word that is not listed is never
  proposed.
* Only explicit statements become facts. A keyword mention in free text is
  evidence of a mention, not of a claim, and is labelled as such.
* Years of experience, proficiency, employment history, dates, employers,
  degrees and achievements are never derived from a keyword mention.
* An ambiguous document produces no proposals at all.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from .lexicon import (
    ARTIFACT_KINDS,
    CEFR_LEVELS,
    CERTIFICATION_MARKERS,
    CERTIFICATION_TERMS,
    DEGREE_LEVELS,
    EDUCATION_EXPLICIT_MARKERS,
    EXPLICIT_CLAIM_MARKERS,
    LANGUAGE_LEVELS,
    LANGUAGE_TERMS,
    ROLE_TITLES,
    SECTION_HEADINGS,
    SKILL_TERMS,
)
from .models import (
    PARSER_SCHEMA_VERSION,
    PROFILE_SCHEMA_VERSION,
    Category,
    Conflict,
    DocumentReference,
    EvidenceReference,
    ProfileEnvelope,
    ProfileError,
    Proposal,
    ProposalStatus,
    ResolutionHint,
    Support,
)

#: Document statuses whose text may be quoted as evidence.
USABLE_DOCUMENT_STATUSES = frozenset({"extracted", "partial"})

#: The parser contract accepts at most five documents per batch.
MAX_DOCUMENTS = 5

SKILLS_SECTION = "skills"
EXPERIENCE_SECTION = "experience"
EDUCATION_SECTION = "education"
PROJECTS_SECTION = "projects"
LANGUAGES_SECTION = "languages"
CERTIFICATIONS_SECTION = "certifications"

#: Separators between the leading title of a line and the rest of the line.
TITLE_SEPARATORS = (" — ", " – ", " - ", " | ", ": ", " · ")

#: Bullets that may start a line.
BULLET_PREFIXES = ("•", "▪", "‣", "-", "–", "—", "*", "·")

#: Words that end a degree subject because they introduce an institution.
INSTITUTION_WORDS = frozenset(
    {
        "academy",
        "college",
        "hochschule",
        "institute",
        "politecnico",
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

_MAX_TITLE_LENGTH = 80
_MAX_FIELD_WORDS = 4


@dataclass(frozen=True)
class _Segment:
    document_id: str
    index: int
    locator: Mapping[str, Any]
    text: str


@dataclass(frozen=True)
class _Document:
    document_id: str
    index: int
    filename: str
    status: str
    format: str
    segments: tuple[_Segment, ...]
    text_length: int


@dataclass(frozen=True)
class _Line:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class _Candidate:
    category: Category
    key: tuple[str, ...]
    value: Mapping[str, Any]
    evidence: EvidenceReference
    order: tuple[int, int, int]
    date: str | None = None


# ---------------------------------------------------------------------------
# Compiled vocabularies
# ---------------------------------------------------------------------------


def _term_regex(surfaces: Sequence[str]) -> re.Pattern[str]:
    ordered = sorted(set(surfaces), key=lambda value: (-len(value), value))
    alternatives = "|".join(re.escape(surface) for surface in ordered)
    return re.compile(
        rf"(?<![A-Za-z0-9+#.])(?:{alternatives})(?![A-Za-z0-9+#])",
        re.IGNORECASE,
    )


def _group_terms(
    terms: Sequence[tuple[str, str]],
) -> tuple[dict[str, list[str]], dict[str, str]]:
    surfaces: dict[str, list[str]] = {}
    lookup: dict[str, str] = {}
    for canonical, surface in terms:
        surfaces.setdefault(canonical, []).append(surface)
        lookup[surface.casefold()] = canonical
    return surfaces, lookup


_SKILL_SURFACES, _SKILL_LOOKUP = _group_terms(
    (canonical, surface) for canonical, surface, _ in SKILL_TERMS
)
#: The flag belongs to the surface form, not to the canonical name: "ts" is
#: ambiguous in free text while "typescript" is not.
_SKILL_UNAMBIGUOUS_SURFACE: dict[str, bool] = {
    surface.casefold(): unambiguous
    for _canonical, surface, unambiguous in SKILL_TERMS
}

_SKILL_PATTERNS: dict[str, re.Pattern[str]] = {
    canonical: _term_regex(surfaces) for canonical, surfaces in _SKILL_SURFACES.items()
}

_LANGUAGE_SURFACES, _LANGUAGE_LOOKUP = _group_terms(LANGUAGE_TERMS)
_LANGUAGE_PATTERNS: dict[str, re.Pattern[str]] = {
    canonical: _term_regex(surfaces) for canonical, surfaces in _LANGUAGE_SURFACES.items()
}

_DEGREE_SURFACE_LEVEL: dict[str, str] = {}
for _level, _surfaces in DEGREE_LEVELS.items():
    for _surface in _surfaces:
        _DEGREE_SURFACE_LEVEL[_surface.casefold()] = _level
        _DEGREE_SURFACE_LEVEL[_surface.replace(".", "").casefold()] = _level

_DEGREE_ALTERNATION = "|".join(
    re.escape(surface)
    for surface in sorted(_DEGREE_SURFACE_LEVEL, key=lambda value: (-len(value), value))
)

#: Only unambiguous academic abbreviations may state a degree without an
#: explicit connector, so job titles such as "Master Data Manager" are not
#: read as a degree.
_DEGREE_ABBREVIATIONS = ("bsc", "msc", "phd", "b.sc", "m.sc", "b.s", "m.s")
_DEGREE_ABBREVIATION_ALTERNATION = "|".join(
    re.escape(value) for value in sorted(_DEGREE_ABBREVIATIONS, key=lambda v: (-len(v), v))
)

_FIELD_WORD = r"[A-Za-z][A-Za-z&/'\-]*"
_EDUCATION_AFTER_DEGREE = re.compile(
    rf"(?P<level>{_DEGREE_ALTERNATION})\s+(?:degree\s+)?(?:in|of)\s+"
    rf"(?P<field>{_FIELD_WORD}(?:\s+{_FIELD_WORD}){{0,5}})",
    re.IGNORECASE,
)
_EDUCATION_DEGREE_THEN_FIELD = re.compile(
    rf"(?P<level>{_DEGREE_ABBREVIATION_ALTERNATION})\s+(?:degree\s+)?"
    rf"(?P<field>{_FIELD_WORD}(?:\s+{_FIELD_WORD}){{0,3}})",
    re.IGNORECASE,
)
_EDUCATION_BEFORE_DEGREE = re.compile(
    rf"(?P<field>{_FIELD_WORD}(?:\s+{_FIELD_WORD}){{0,3}})\s*[,;]\s*"
    rf"(?P<level>{_DEGREE_ALTERNATION})\b",
    re.IGNORECASE,
)
_EDUCATION_FIELD_FIRST = re.compile(
    rf"(?P<field>{_FIELD_WORD}(?:\s+{_FIELD_WORD}){{0,3}})\s+"
    rf"(?P<level>{_DEGREE_ABBREVIATION_ALTERNATION}|mba)\b",
    re.IGNORECASE,
)

_LANGUAGE_PAREN_LEVEL = re.compile(r"^\s*\(\s*([A-Za-z0-9 +/]{1,20})\s*\)")
_LANGUAGE_DASH_LEVEL = re.compile(r"^\s*[–—-]\s*([A-Za-z][A-Za-z ]{0,19})")

_ARTIFACT_KIND_PATTERNS: dict[str, re.Pattern[str]] = {
    kind: re.compile(
        r"(?<![A-Za-z0-9])(?:"
        + "|".join(re.escape(surface) for surface in sorted(surfaces, key=len, reverse=True))
        + r")(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    for kind, surfaces in ARTIFACT_KINDS.items()
}

#: The recognised CEFR levels, in ascending order.
CEFR_LEVELS_ORDER: dict[str, int] = {
    level: index + 1 for index, level in enumerate(sorted(CEFR_LEVELS))
}

#: A date stated right after a claim. Only the text of the claim is read, so
#: a date can never be invented, and the upload order and the file name are
#: never used as a chronology.
_CLAIM_DATE = re.compile(
    r"^\s*[,;–—-]\s*"
    r"((?:19|20)\d{2}(?:-\d{2}(?:-\d{2})?|\s*[-–]\s*(?:19|20)\d{2})?)(?![0-9])"
)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProfileError(f"{label} must be an object")
    return value


def _parse_documents(response: Mapping[str, Any]) -> list[_Document]:
    """Validate the parser response and return its documents."""
    schema_version = response.get("schema_version")
    if schema_version != PARSER_SCHEMA_VERSION:
        raise ProfileError(
            f"unsupported parser schema {schema_version!r}; "
            f"expected {PARSER_SCHEMA_VERSION!r}"
        )
    raw_documents = response.get("documents")
    if not isinstance(raw_documents, list):
        raise ProfileError("documents must be an array")
    if len(raw_documents) > MAX_DOCUMENTS:
        raise ProfileError(
            f"at most {MAX_DOCUMENTS} documents are supported, "
            f"got {len(raw_documents)}"
        )

    documents: list[_Document] = []
    for position, raw_document in enumerate(raw_documents):
        document = _require_mapping(raw_document, f"documents[{position}]")
        document_id = document.get("document_id")
        if not isinstance(document_id, str) or not document_id.strip():
            raise ProfileError(
                f"documents[{position}] has no document_id; provenance is never invented"
            )
        raw_segments = document.get("segments")
        if not isinstance(raw_segments, list):
            raise ProfileError(f"documents[{position}].segments must be an array")

        segments: list[_Segment] = []
        for segment_index, raw_segment in enumerate(raw_segments):
            segment = _require_mapping(
                raw_segment, f"documents[{position}].segments[{segment_index}]"
            )
            text = segment.get("text")
            if not isinstance(text, str):
                raise ProfileError(
                    f"documents[{position}].segments[{segment_index}].text must be a string"
                )
            locator = segment.get("locator")
            if not isinstance(locator, Mapping):
                raise ProfileError(
                    f"documents[{position}].segments[{segment_index}].locator "
                    "must be an object"
                )
            segments.append(
                _Segment(
                    document_id=document_id,
                    index=segment_index,
                    locator=dict(locator),
                    text=text,
                )
            )

        filename = document.get("filename")
        status = document.get("status")
        document_format = document.get("format")
        documents.append(
            _Document(
                document_id=document_id,
                index=position,
                filename=filename if isinstance(filename, str) else "",
                status=status if isinstance(status, str) else "",
                format=document_format if isinstance(document_format, str) else "",
                segments=tuple(segments),
                text_length=sum(len(segment.text) for segment in segments),
            )
        )
    return documents


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _iter_lines(text: str) -> list[_Line]:
    """Split a segment into lines, keeping the offsets of each line."""
    lines: list[_Line] = []
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        stripped = raw_line.rstrip("\r\n")
        lines.append(_Line(start=offset, end=offset + len(stripped), text=stripped))
        offset += len(raw_line)
    if not lines and text:
        lines.append(_Line(start=0, end=len(text), text=text))
    return lines


def _normalize_heading(text: str) -> str:
    cleaned = text.strip().strip("*•▪‣-–— ")
    cleaned = cleaned.replace("&", " and ")
    cleaned = cleaned.rstrip(":").strip()
    return " ".join(cleaned.split()).casefold()


def match_section_heading(text: str) -> str | None:
    """Return the canonical section name for a heading line, or ``None``."""
    normalized = _normalize_heading(text)
    if not normalized or len(normalized) > 40:
        return None
    return SECTION_HEADINGS.get(normalized)


def _strip_bullet(text: str) -> tuple[str, int]:
    """Remove a leading bullet marker and report where the text starts."""
    leading = len(text) - len(text.lstrip())
    stripped = text[leading:]
    for bullet in BULLET_PREFIXES:
        if stripped.startswith(bullet):
            remainder = stripped[len(bullet):]
            if remainder[:1] in {" ", ""}:
                trimmed = remainder.lstrip()
                return trimmed, leading + len(bullet) + (len(remainder) - len(trimmed))
    return stripped, leading


def _split_title(text: str) -> tuple[str, str] | None:
    """Split a line into its leading title and the remainder."""
    cleaned, _ = _strip_bullet(text)
    if not cleaned:
        return None
    position = -1
    separator = ""
    for candidate in TITLE_SEPARATORS:
        found = cleaned.find(candidate)
        if found >= 0 and (position < 0 or found < position):
            position = found
            separator = candidate
    if position < 0:
        return cleaned.strip(), ""
    return cleaned[:position].strip(), cleaned[position + len(separator):].strip()


def _normalize_value(text: str) -> str:
    return " ".join(text.split()).casefold()


def _clean_field(text: str) -> str:
    """Keep the subject of a degree, stopping before an institution name."""
    kept: list[str] = []
    for word in _normalize_value(text).split():
        if word in INSTITUTION_WORDS:
            break
        kept.append(word)
        if len(kept) >= _MAX_FIELD_WORDS:
            break
    return " ".join(kept).strip(" ,;:-")


def _is_date_like(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return True
    if re.fullmatch(r"[\d\s./-]+", cleaned):
        return True
    return bool(re.search(r"\b(19|20)\d{2}\b", cleaned))


def _is_letter_word(text: str) -> bool:
    return any(character.isalpha() for character in text)


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------


def _explicit_marker_before(line: str, position: int) -> bool:
    lookback = line[max(0, position - 80):position].casefold()
    return any(marker in lookback for marker in EXPLICIT_CLAIM_MARKERS)


def _skill_support(section: str, line: str, position: int) -> Support:
    if section == SKILLS_SECTION:
        return Support.EXPLICIT_CLAIM
    if _explicit_marker_before(line, position):
        return Support.EXPLICIT_CLAIM
    return Support.KEYWORD_MENTION


def _candidate(
    document: _Document,
    segment: _Segment,
    category: Category,
    key: tuple[str, ...],
    value: Mapping[str, Any],
    start: int,
    end: int,
    support: Support,
) -> _Candidate:
    return _Candidate(
        category=category,
        key=key,
        value=value,
        evidence=EvidenceReference(
            document_id=document.document_id,
            segment_index=segment.index,
            locator=segment.locator,
            quote=segment.text[start:end],
            start=start,
            end=end,
            support=support,
        ),
        order=(document.index, segment.index, start),
    )


def _extract_skills(
    document: _Document,
    segment: _Segment,
    line: _Line,
    section: str,
) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for canonical, pattern in _SKILL_PATTERNS.items():
        for match in pattern.finditer(line.text):
            surface = match.group(0)
            canonical_name = _SKILL_LOOKUP.get(surface.casefold(), canonical)
            support = _skill_support(section, line.text, match.start())
            if not _SKILL_UNAMBIGUOUS_SURFACE.get(surface.casefold(), True) and (
                support is not Support.EXPLICIT_CLAIM
            ):
                continue
            start = line.start + match.start()
            end = line.start + match.end()
            candidates.append(
                _candidate(
                    document,
                    segment,
                    Category.SKILL,
                    (canonical_name,),
                    {"name": canonical_name},
                    start,
                    end,
                    support,
                )
            )
    return candidates


def _extract_languages(
    document: _Document,
    segment: _Segment,
    line: _Line,
    section: str,
) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for canonical, pattern in _LANGUAGE_PATTERNS.items():
        for match in pattern.finditer(line.text):
            surface = match.group(0)
            canonical_name = _LANGUAGE_LOOKUP.get(surface.casefold(), canonical)
            end = match.end()
            stated_level: str | None = None
            tail = line.text[end:]
            paren = _LANGUAGE_PAREN_LEVEL.match(tail)
            dash = None if paren is not None else _LANGUAGE_DASH_LEVEL.match(tail)
            if paren is not None:
                level_text = paren.group(1).strip().casefold()
                if level_text in LANGUAGE_LEVELS:
                    stated_level = level_text
                    end += paren.end()
            elif dash is not None:
                level_text = dash.group(1).strip().casefold()
                if level_text in LANGUAGE_LEVELS:
                    stated_level = level_text
                    end += dash.end()
            start = line.start + match.start()
            absolute_end = line.start + end
            support = (
                Support.EXPLICIT_CLAIM
                if section == LANGUAGES_SECTION
                else Support.KEYWORD_MENTION
            )
            # A date stated right after the claim belongs to it. It is read
            # from the text, never from the upload order or the file name.
            claimed_date: str | None = None
            dated = _CLAIM_DATE.match(line.text[end:])
            if dated is not None:
                claimed_date = dated.group(1)
                absolute_end = line.start + end + dated.end()
            candidate = _candidate(
                document,
                segment,
                Category.LANGUAGE,
                (canonical_name, stated_level or ""),
                {"language": canonical_name, "stated_level": stated_level},
                start,
                absolute_end,
                support,
            )
            candidates.append(
                replace(candidate, date=claimed_date) if claimed_date else candidate
            )
    return candidates


def _education_marker_before(line: str, position: int) -> bool:
    lookback = line[max(0, position - 80):position].casefold()
    return any(marker in lookback for marker in EDUCATION_EXPLICIT_MARKERS)


def _extract_education(
    document: _Document,
    segment: _Segment,
    line: _Line,
    section: str,
) -> list[_Candidate]:
    cleaned, bullet_offset = _strip_bullet(line.text)
    if not cleaned:
        return []
    in_education_section = section == EDUCATION_SECTION
    candidates: list[_Candidate] = []
    seen: set[tuple[str, str]] = set()
    for pattern in (
        _EDUCATION_AFTER_DEGREE,
        _EDUCATION_DEGREE_THEN_FIELD,
        _EDUCATION_BEFORE_DEGREE,
        _EDUCATION_FIELD_FIRST,
    ):
        anchor = "level" if pattern in (_EDUCATION_AFTER_DEGREE, _EDUCATION_DEGREE_THEN_FIELD) else "field"
        for match in pattern.finditer(cleaned):
            explicit = (
                in_education_section
                or match.start(anchor) == 0
                or _education_marker_before(cleaned, match.start())
            )
            if not explicit:
                continue
            level_surface = match.group("level").casefold()
            level = _DEGREE_SURFACE_LEVEL.get(level_surface) or _DEGREE_SURFACE_LEVEL.get(
                level_surface.replace(".", "")
            )
            if level is None:
                continue
            field = _clean_field(match.group("field"))
            if not field or field.split()[0] in {"of", "in", "at", "and", "the"}:
                continue
            if (level, field) in seen:
                continue
            seen.add((level, field))
            start = line.start + bullet_offset + match.start()
            end = line.start + bullet_offset + match.end()
            candidates.append(
                _candidate(
                    document,
                    segment,
                    Category.EDUCATION,
                    (level, field),
                    {"level": level, "field": field},
                    start,
                    end,
                    Support.EXPLICIT_CLAIM,
                )
            )
    return candidates


def _title_candidate(
    document: _Document,
    segment: _Segment,
    line: _Line,
    category: Category,
    key: tuple[str, ...],
    value: Mapping[str, Any],
    *,
    whole_entry: bool = False,
) -> list[_Candidate]:
    split = _split_title(line.text)
    if split is None:
        return []
    title, _ = split
    if not (2 <= len(title) <= _MAX_TITLE_LENGTH):
        return []
    if _is_date_like(title) or not _is_letter_word(title):
        return []
    cleaned, bullet_offset = _strip_bullet(line.text)
    position = cleaned.find(title)
    if position < 0:
        position = 0
    start = line.start + bullet_offset + position
    end = start + len(title)
    if whole_entry:
        # Keep the whole entry, so the original description stays in the
        # evidence with an exact span.
        end = line.end
    return [
        _candidate(
            document,
            segment,
            category,
            key,
            value,
            start,
            end,
            Support.EXPLICIT_CLAIM,
        )
    ]


def _extract_project(
    document: _Document,
    segment: _Segment,
    line: _Line,
) -> list[_Candidate]:
    split = _split_title(line.text)
    if split is None:
        return []
    title, description = split
    if not (2 <= len(title) <= _MAX_TITLE_LENGTH):
        return []
    if _is_date_like(title) or not _is_letter_word(title):
        return []
    name = _normalize_value(title)
    if not name:
        return []
    return _title_candidate(
        document,
        segment,
        line,
        Category.PROJECT,
        (name, _normalize_value(description)),
        {"name": name},
        whole_entry=True,
    )


_DATE_RANGE = re.compile(
    r"\b(?:19|20)\d{2}\b\s*(?:-|\u2013|\u2014|to)\s*"
    r"(?:(?:19|20)\d{2}|present|current)\b",
    re.IGNORECASE,
)

#: Hard cap on lines attached to one entry, so a malformed document cannot
#: turn an entire page into one proposal.
_MAX_CONTRIBUTION_LINES = 12


def _looks_like_entry_header(text: str) -> bool:
    """True for a line that starts a new entry rather than continuing one."""
    if _DATE_RANGE.search(text):
        return True
    split = _split_title(text)
    if split is None:
        return False
    title, _ = split
    return any(word in ROLE_TITLES for word in _normalize_value(title).split())


def contribution_lines(
    document: _Document,
    segment: _Segment,
    line: _Line,
) -> list[tuple[_Segment, _Line]]:
    """Return the source lines that belong to the entry starting at ``line``.

    The rule is structural, not lexical: keep reading until a known section
    heading, a new entry header, or the line cap. No verb list is involved, so
    an achievement is never dropped because of the word it starts with.

    DOCX extraction may place every paragraph in its own segment, so the walk
    continues into later segments instead of stopping at the segment boundary.
    """
    segments = [segment] + [
        item for item in document.segments if item.index > segment.index
    ]
    collected: list[tuple[_Segment, _Line]] = []
    for segment_index, current in enumerate(segments):
        lines = _iter_lines(current.text)
        if segment_index == 0:
            index = next(
                (
                    position
                    for position, item in enumerate(lines)
                    if item.start == line.start
                ),
                None,
            )
            if index is None:
                return []
            lines = lines[index + 1:]
        for candidate in lines:
            text = candidate.text.strip()
            if not text:
                continue
            if match_section_heading(text) is not None:
                return collected
            if _looks_like_entry_header(text):
                return collected
            if text.isupper() and len(text.split()) <= 4:
                # A short all-caps line is a heading even when the vocabulary
                # does not know it (for example "VOLUNTEERING").
                return collected
            if _is_date_like(text) and len(text) <= 24:
                # A standalone date or location line is entry metadata, not an
                # achievement.
                continue
            collected.append((current, candidate))
            if len(collected) >= _MAX_CONTRIBUTION_LINES:
                return collected
    return collected


def _extract_role(
    document: _Document,
    segment: _Segment,
    line: _Line,
) -> list[_Candidate]:
    split = _split_title(line.text)
    if split is None:
        return []
    title, _ = split
    words = _normalize_value(title).split()
    if not any(word in ROLE_TITLES for word in words):
        return []
    key = (_normalize_value(title),)
    value = {"role": _normalize_value(title)}
    candidates = list(
        _title_candidate(
            document,
            segment,
            line,
            Category.EXPERIENCE,
            key,
            value,
            whole_entry=True,
        )
    )
    # An experience entry is the role line *and* the source-backed lines that
    # belong to it. Keeping those lines as exact evidence is what lets the
    # draft preserve achievements; omitting them silently dropped every
    # contribution whose first word was outside a small verb list.
    for source_segment, contribution in contribution_lines(document, segment, line):
        start = contribution.start + (
            len(contribution.text) - len(contribution.text.lstrip())
        )
        end = contribution.start + len(contribution.text.rstrip())
        if end <= start:
            continue
        candidates.append(
            _candidate(
                document,
                source_segment,
                Category.EXPERIENCE,
                key,
                value,
                start,
                end,
                Support.EXPLICIT_CLAIM,
            )
        )
    return candidates


def _extract_certification(
    document: _Document,
    segment: _Segment,
    line: _Line,
) -> list[_Candidate]:
    split = _split_title(line.text)
    if split is None:
        return []
    title, _ = split
    normalized = _normalize_value(title)
    has_marker = any(marker in normalized for marker in CERTIFICATION_MARKERS)
    has_term = any(term in normalized for term in CERTIFICATION_TERMS)
    if not (has_marker or has_term):
        return []
    return _title_candidate(
        document,
        segment,
        line,
        Category.CERTIFICATION,
        (normalized,),
        {"name": normalized},
    )


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _stable_id(prefix: str, parts: Sequence[str]) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:16]}"


def _artifact_kinds(text: str) -> frozenset[str]:
    """Return the kinds of software artifact a description names.

    The vocabulary is closed and small. Only a difference of *kind* is
    treated as a contradiction: a project described with a different wording,
    or with a different technology, is not a contradiction.
    """
    matches: list[tuple[int, int, str]] = []
    for kind, pattern in _ARTIFACT_KIND_PATTERNS.items():
        for match in pattern.finditer(text):
            matches.append((match.start(), match.end(), kind))
    matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    kept: list[tuple[int, int, str]] = []
    for start, end, kind in matches:
        if any(start < other_end and other_start < end for other_start, other_end, _ in kept):
            continue
        kept.append((start, end, kind))
    return frozenset(kind for _, _, kind in kept)


def _descriptions_conflict(left: str, right: str) -> bool:
    """True when two descriptions name different kinds of artifact.

    A difference of wording, or a difference of technology, is not a
    contradiction: those descriptions are complementary and are merged.
    """
    left_kinds = _artifact_kinds(left)
    right_kinds = _artifact_kinds(right)
    if not left_kinds or not right_kinds:
        return False
    return left_kinds.isdisjoint(right_kinds)


def _cluster_project_entries(
    entries: Sequence[tuple[str, str]],
) -> list[list[int]]:
    """Cluster the entries of one project name into compatible groups."""
    clusters: list[list[int]] = []
    for index, (description, _raw) in enumerate(entries):
        placed = False
        for cluster in clusters:
            representative = entries[cluster[0]][0]
            if not _descriptions_conflict(representative, description):
                cluster.append(index)
                placed = True
                break
        if not placed:
            clusters.append([index])
    return clusters


def _cefr_order(level: str) -> int:
    return CEFR_LEVELS_ORDER.get(level.casefold(), -1)


def _date_order(text: str) -> int:
    """Return a comparable number for a date stated in the source text."""
    years = re.findall(r"(?:19|20)\d{2}", text)
    if not years:
        return -1
    base = int(years[-1])
    month = re.search(r"-(0[1-9]|1[0-2])", text)
    return base * 100 + (int(month.group(1)) if month else 0)


def _language_resolution_hint(
    group: Sequence[Proposal],
    dates: Mapping[str, tuple[str, ...]],
) -> ResolutionHint | None:
    """Recommend which conflicting language claim to keep.

    The hint is only produced when the claims can be compared: every level
    must be a recognised CEFR level. It is a recommendation, never a proof and
    never an approval.

    The rule is:

    * a claim with a credible date in its own text is anchored in time, so the
      most recent dated claim wins, even when it is not the highest level;
    * without any date there is no reliable chronology, so the highest
      declared level is recommended.
    """
    levels = {
        proposal.proposal_id: str(proposal.value.get("stated_level") or "")
        for proposal in group
    }
    if not levels or not all(level in CEFR_LEVELS for level in levels.values()):
        return None
    if len(set(levels.values())) < 2:
        return None

    highest = max(
        group, key=lambda proposal: _cefr_order(str(proposal.value.get("stated_level")))
    )
    dated: list[tuple[Proposal, str]] = []
    for proposal in group:
        anchors = dates.get(proposal.proposal_id, ())
        if anchors:
            dated.append((proposal, max(anchors, key=_date_order)))
    if dated:
        latest = max(dated, key=lambda item: _date_order(item[1]))
        if latest[0].proposal_id != highest.proposal_id:
            if len(dated) > 1:
                explanation = (
                    f"The claim dated {latest[1]} is the most recent one stated with a "
                    "date, so it is preferred."
                )
            else:
                explanation = (
                    f"The claim dated {latest[1]} is the only one anchored in time, so it "
                    "is preferred over the undated claim."
                )
            return ResolutionHint(
                strategy="prefer_dated_claim",
                keep_proposal_ids=(latest[0].proposal_id,),
                explanation=explanation,
            )
    level = str(highest.value.get("stated_level"))
    return ResolutionHint(
        strategy="prefer_higher_cefr_claim",
        keep_proposal_ids=(highest.proposal_id,),
        explanation=(
            f"{level.upper()} is the highest explicitly stated level, but no reliable "
            "chronology is available."
        ),
    )


def _detect_conflicts(
    proposals: Sequence[Proposal],
    dates: Mapping[str, tuple[str, ...]],
) -> list[Conflict]:
    """Find conflicts the engine can state reliably.

    Two kinds are reported, and only when the documents state them
    explicitly:

    * the same language is claimed with two different stated levels;
    * the same project name describes two different kinds of artifact.

    A project whose descriptions differ only in wording is not a conflict:
    those descriptions are complementary and are merged into one proposal.
    """
    conflicts: list[Conflict] = []

    by_language: dict[str, list[Proposal]] = {}
    for proposal in proposals:
        if proposal.category is Category.LANGUAGE:
            by_language.setdefault(str(proposal.value.get("language")), []).append(proposal)
    for language, group in sorted(by_language.items()):
        levels = {
            str(proposal.value.get("stated_level"))
            for proposal in group
            if proposal.value.get("stated_level")
        }
        if len(levels) > 1:
            conflicts.append(
                Conflict(
                    conflict_id=_stable_id("conf", ["language", language, *sorted(levels)]),
                    kind="conflicting_stated_level",
                    category=Category.LANGUAGE,
                    proposal_ids=tuple(sorted(p.proposal_id for p in group)),
                    message=(
                        f"The documents state different levels for the language {language}."
                    ),
                    resolution_hint=_language_resolution_hint(group, dates),
                )
            )

    by_project: dict[str, list[Proposal]] = {}
    for proposal in proposals:
        if proposal.category is Category.PROJECT:
            by_project.setdefault(str(proposal.value.get("name")), []).append(proposal)
    for name, group in sorted(by_project.items()):
        if len(group) > 1:
            conflicts.append(
                Conflict(
                    conflict_id=_stable_id("conf", ["project", name]),
                    kind="conflicting_description",
                    category=Category.PROJECT,
                    proposal_ids=tuple(sorted(p.proposal_id for p in group)),
                    message=(
                        f"The project {name} is described as different kinds of artifact; "
                        "the descriptions were not merged."
                    ),
                )
            )

    return conflicts


def _make_proposal(
    category: str,
    key: tuple[str, ...],
    group: Sequence[_Candidate],
) -> Proposal:
    """Build one proposal, keeping every individual source reference."""
    unique: dict[tuple[Any, ...], _Candidate] = {}
    for candidate in group:
        reference = candidate.evidence
        marker = (
            reference.document_id,
            reference.segment_index,
            reference.start,
            reference.end,
        )
        unique.setdefault(marker, candidate)
    ordered = sorted(unique.values(), key=lambda item: item.order)
    return Proposal(
        proposal_id=_stable_id("prop", [category, *key]),
        category=Category(category),
        value=ordered[0].value,
        status=ProposalStatus.PROPOSED,
        evidence=tuple(candidate.evidence for candidate in ordered),
        conflicts=(),
    )


def _collect_dates(
    proposal: Proposal,
    group: Sequence[_Candidate],
    dates: dict[str, tuple[str, ...]],
) -> None:
    found = {candidate.date for candidate in group if candidate.date}
    if found:
        dates[proposal.proposal_id] = tuple(sorted(found))


def _group(candidates: Sequence[_Candidate]) -> tuple[list[Proposal], list[Conflict]]:
    proposals: list[Proposal] = []
    dates: dict[str, tuple[str, ...]] = {}

    grouped: dict[tuple[str, tuple[str, ...]], list[_Candidate]] = {}
    projects: dict[str, list[_Candidate]] = {}
    for candidate in candidates:
        if candidate.category is Category.PROJECT:
            projects.setdefault(candidate.key[0], []).append(candidate)
            continue
        key = (candidate.category.value, candidate.key)
        grouped.setdefault(key, []).append(candidate)

    for (category, key), group in grouped.items():
        proposal = _make_proposal(category, key, group)
        proposals.append(proposal)
        _collect_dates(proposal, group, dates)

    for name, group in sorted(projects.items()):
        entries = [(candidate.key[1], candidate.evidence.quote) for candidate in group]
        clusters = _cluster_project_entries(entries)
        for cluster in clusters:
            members = [group[index] for index in cluster]
            if len(clusters) == 1:
                key = (name,)
            else:
                signature = _stable_id(
                    "sig", sorted(candidate.key[1] for candidate in members)
                )
                key = (name, signature)
            proposal = _make_proposal("project", key, members)
            proposals.append(proposal)
            _collect_dates(proposal, members, dates)

    proposals.sort(
        key=lambda proposal: (
            proposal.category.value,
            proposal.evidence[0].document_id,
            proposal.evidence[0].segment_index,
            proposal.evidence[0].start,
        )
    )

    conflicts = _detect_conflicts(proposals, dates)
    referenced: dict[str, list[str]] = {}
    for conflict in conflicts:
        for proposal_id in conflict.proposal_ids:
            referenced.setdefault(proposal_id, []).append(conflict.conflict_id)
    proposals = [
        Proposal(
            proposal_id=proposal.proposal_id,
            category=proposal.category,
            value=proposal.value,
            status=proposal.status,
            evidence=proposal.evidence,
            conflicts=tuple(sorted(referenced.get(proposal.proposal_id, []))),
        )
        for proposal in proposals
    ]
    return proposals, conflicts


def _document_reference(document: _Document) -> DocumentReference:
    return DocumentReference(
        document_id=document.document_id,
        index=document.index,
        filename=document.filename,
        status=document.status,
        format=document.format,
        segment_count=len(document.segments),
        text_length=document.text_length,
    )


def build_profile_proposals(response: Mapping[str, Any]) -> ProfileEnvelope:
    """Build the proposal envelope from a parser or transport response.

    The function is pure and deterministic: the same response always yields
    the same proposals, in the same order, with the same identifiers.
    """
    payload = _require_mapping(response, "response")
    documents = _parse_documents(payload)
    job_id = payload.get("job_id")
    warnings: list[str] = []

    candidates: list[_Candidate] = []
    for document in documents:
        if document.status not in USABLE_DOCUMENT_STATUSES:
            warnings.append(
                f"Document {document.index} was skipped because its status is "
                f"{document.status!r}."
            )
            continue
        section = ""
        for segment in document.segments:
            for line in _iter_lines(segment.text):
                if not line.text.strip():
                    continue
                heading = match_section_heading(line.text)
                if heading is not None:
                    section = heading
                    continue
                candidates.extend(_extract_skills(document, segment, line, section))
                candidates.extend(_extract_languages(document, segment, line, section))
                candidates.extend(_extract_education(document, segment, line, section))
                if section == PROJECTS_SECTION:
                    candidates.extend(_extract_project(document, segment, line))
                if section == EXPERIENCE_SECTION:
                    candidates.extend(_extract_role(document, segment, line))
                if section == CERTIFICATIONS_SECTION:
                    candidates.extend(_extract_certification(document, segment, line))

    proposals, conflicts = _group(candidates)
    return ProfileEnvelope(
        profile_schema_version=PROFILE_SCHEMA_VERSION,
        parser_schema_version=PARSER_SCHEMA_VERSION,
        job_id=job_id if isinstance(job_id, str) else None,
        documents=tuple(_document_reference(document) for document in documents),
        proposals=tuple(proposals),
        conflicts=tuple(conflicts),
        warnings=tuple(warnings),
    )


__all__ = [
    "USABLE_DOCUMENT_STATUSES",
    "build_profile_proposals",
]
