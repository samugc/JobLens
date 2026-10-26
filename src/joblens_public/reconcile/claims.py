"""Extraction of typed professional claims from the extracted text.

The extractors are deliberately conservative. A claim is only produced when
the source states it, and every claim keeps the exact span it came from. A
missing attribute is absent, never guessed, and nothing is inferred from the
absence of a statement in another document.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from joblens_public.profile.lexicon import (
    CERTIFICATION_MARKERS,
    CERTIFICATION_TERMS,
    EXPLICIT_CLAIM_MARKERS,
    LANGUAGE_LEVELS,
    ROLE_TITLES,
)
from joblens_public.profile.models import EvidenceReference, Support

from .models import Claim, ClaimAttribute, ClaimCategory
from .text import (
    Line,
    iter_lines,
    language_mentions,
    match_heading,
    normalise,
    parse_date_range,
    parse_degree,
    parse_duration,
    parse_statement,
    role_variants,
    skill_mentions,
    split_title,
    strip_bullet,
)

__all__ = [
    "extract_claims",
    "parse_certification_line",
    "parse_education_line",
    "parse_employment_line",
    "parse_project_line",
]

SKILLS_SECTION = "skills"
EXPERIENCE_SECTION = "experience"
EDUCATION_SECTION = "education"
PROJECTS_SECTION = "projects"
LANGUAGES_SECTION = "languages"
CERTIFICATIONS_SECTION = "certifications"

#: Wording that states a proficiency instead of only mentioning a skill.
PROFICIENCY_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("expert", ("an expert in", "expert in", "expert with")),
    ("proficient", ("proficient in", "proficiency in", "proficient with")),
    ("advanced", ("advanced in", "advanced knowledge of")),
    ("strong", ("strong in", "strong knowledge of")),
    ("working knowledge", ("working knowledge of",)),
    ("basic", ("basic knowledge of",)),
    ("elementary", ("elementary knowledge of",)),
)

#: Verbs that open a responsibility or an achievement.
ACTION_VERBS = (
    "achieved",
    "analyzed",
    "analysed",
    "architected",
    "automated",
    "built",
    "created",
    "cut",
    "delivered",
    "deployed",
    "designed",
    "developed",
    "documented",
    "doubled",
    "generated",
    "grew",
    "handled",
    "implemented",
    "improved",
    "increased",
    "integrated",
    "launched",
    "led",
    "maintained",
    "managed",
    "mentored",
    "migrated",
    "optimized",
    "optimised",
    "owned",
    "processed",
    "reduced",
    "refactored",
    "saved",
    "scaled",
    "shipped",
    "streamlined",
    "supported",
    "tested",
    "trained",
    "wrote",
)

_ACTION_CLAUSE = re.compile(
    r"(?<![A-Za-z0-9])(?:" + "|".join(ACTION_VERBS) + r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)

_DATE_TOKEN = r"(?:19|20)\d{2}"
_DATE_EXPRESSION = re.compile(
    rf"{_DATE_TOKEN}(?:\s*(?:-|–|—|to)\s*(?:{_DATE_TOKEN}|present|current|now))?",
    re.IGNORECASE,
)
_DURATION_EXPRESSION = re.compile(r"\d+\s*(?:\+\s*)?(?:years?|months?)", re.IGNORECASE)


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


def _claim_id(
    category: ClaimCategory,
    subject: str,
    attributes: Sequence[ClaimAttribute],
    evidence: EvidenceReference,
) -> str:
    parts = [category.value, subject]
    parts.extend(f"{item.name}={item.normalized}" for item in attributes)
    parts.append(
        f"{evidence.document_id}:{evidence.segment_index}:{evidence.start}:{evidence.end}"
    )
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"claim_{digest[:16]}"


def _attribute(name: str, value: Any) -> ClaimAttribute:
    return ClaimAttribute(name=name, value=value, normalized=normalise(str(value)))


def _make_claim(
    document: _Document,
    segment: _Segment,
    category: ClaimCategory,
    subject: str,
    subject_label: str,
    attributes: Sequence[ClaimAttribute],
    start: int,
    end: int,
    support: Support,
) -> Claim:
    evidence = EvidenceReference(
        document_id=document.document_id,
        segment_index=segment.index,
        locator=segment.locator,
        quote=segment.text[start:end],
        start=start,
        end=end,
        support=support,
    )
    return Claim(
        claim_id=_claim_id(category, subject, attributes, evidence),
        category=category,
        subject=subject,
        subject_label=subject_label,
        attributes=tuple(attributes),
        evidence=(evidence,),
        qualifier=support.value,
    )


def _remove_span(text: str, start: int, end: int) -> str:
    return (text[:start] + " " + text[end:]).strip()


# ---------------------------------------------------------------------------
# Line parsers
# ---------------------------------------------------------------------------


def parse_employment_line(text: str) -> dict[str, Any] | None:
    """Read a position line: role, organisation, period and duration.

    Only what the line states is returned. A missing date stays missing.
    """
    cleaned, _ = strip_bullet(text)
    if not cleaned:
        return None
    remainder = cleaned

    duration: int | None = None
    duration_exact = True
    duration_match = _DURATION_EXPRESSION.search(remainder)
    if duration_match is not None:
        parsed = parse_duration(duration_match.group(0))
        if parsed is not None:
            duration, duration_exact = parsed
            remainder = _remove_span(remainder, duration_match.start(), duration_match.end())

    start_date: str | None = None
    end_date: str | None = None
    date_match = _DATE_EXPRESSION.search(remainder)
    if date_match is not None:
        start_date, end_date = parse_date_range(date_match.group(0))
        remainder = _remove_span(remainder, date_match.start(), date_match.end())

    remainder = remainder.strip(" \t|,;:-–—()")
    if not remainder:
        return None

    role = ""
    organization = ""
    split = split_title(remainder)
    if split is not None:
        role, organization = split
    if role and not organization:
        for connector in (" at ", " @ ", " with "):
            head, separator, tail = role.partition(connector)
            if separator and tail:
                role, organization = head, tail
                break
    role = role.strip(" \t|,;:-–—")
    organization = organization.strip(" \t|,;:-–—")
    if not role:
        return None
    if not any(word in ROLE_TITLES for word in normalise(role).split()):
        return None
    return {
        "role": role,
        "organization": organization,
        "start": start_date,
        "end": end_date,
        "duration_months": duration,
        "duration_exact": duration_exact,
    }


def parse_education_line(text: str) -> dict[str, Any] | None:
    """Read an education line: degree, subject, institution and period."""
    cleaned, _ = strip_bullet(text)
    if not cleaned:
        return None
    remainder = cleaned
    start_date: str | None = None
    end_date: str | None = None
    date_match = _DATE_EXPRESSION.search(remainder)
    if date_match is not None:
        start_date, end_date = parse_date_range(date_match.group(0))
        remainder = _remove_span(remainder, date_match.start(), date_match.end())
    remainder = remainder.strip(" \t|,;:-–—()")
    if not remainder:
        return None

    degree = parse_degree(remainder)
    if degree is None:
        return None
    level, field = degree
    institution = ""
    for separator in (",", ";", " at ", " from "):
        if separator not in remainder:
            continue
        head, _, tail = remainder.partition(separator)
        candidate = tail.strip(" \t|,;:-–—")
        if separator in {",", ";"}:
            if candidate and parse_degree(candidate) is None:
                institution = candidate
        else:
            institution = candidate
        break
    return {
        "level": level,
        "field": field,
        "institution": institution,
        "start": start_date,
        "end": end_date,
    }


def parse_project_line(text: str) -> dict[str, Any] | None:
    """Read a project line: the name and the description that follows it."""
    split = split_title(text)
    if split is None:
        return None
    title, description = split
    if not (2 <= len(title) <= 80):
        return None
    if re.fullmatch(r"[\d\s./-]+", title.strip()):
        return None
    return {"name": title.strip(), "description": description.strip()}


def parse_certification_line(text: str) -> dict[str, Any] | None:
    """Read a certification line: the name, the issuer and a date."""
    split = split_title(text)
    if split is None:
        return None
    title, remainder = split
    if not (2 <= len(title) <= 80):
        return None
    normalized = normalise(title)
    has_marker = any(marker in normalized for marker in CERTIFICATION_MARKERS)
    has_term = any(term in normalized for term in CERTIFICATION_TERMS)
    if not (has_marker or has_term):
        return None
    issuer = ""
    date = None
    if remainder:
        date_match = re.search(r"(?:19|20)\d{2}", remainder)
        if date_match is not None:
            date = date_match.group(0)
            remainder = _remove_span(remainder, date_match.start(), date_match.end())
        issuer = remainder.strip(" \t|,;:-–—")
    return {"name": title.strip(), "issuer": issuer, "date": date}


def _proficiency_before(text: str, position: int) -> str | None:
    lookback = text[max(0, position - 80):position].casefold()
    for level, markers in PROFICIENCY_MARKERS:
        if any(marker in lookback for marker in markers):
            return level
    return None


def _clauses(text: str) -> list[tuple[int, int, str]]:
    """Return the action clauses of a text with their offsets."""
    clauses: list[tuple[int, int, str]] = []
    for match in _ACTION_CLAUSE.finditer(text):
        start = match.start()
        end = len(text)
        for separator in (". ", "; ", " and ", " with "):
            found = text.find(separator, match.end())
            if found > 0:
                end = min(end, found)
        raw = text[start:end]
        clause = raw.strip(" .,;")
        if clause:
            clauses.append((start, start + len(clause), clause))
    return clauses


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------


def _explicit_marker_before(text: str, position: int) -> bool:
    """True when the text before a mention states an explicit claim."""
    lookback = text[max(0, position - 80):position].casefold()
    return any(marker in lookback for marker in EXPLICIT_CLAIM_MARKERS)


def _skill_claims(
    document: _Document,
    segment: _Segment,
    line: Line,
    section: str,
) -> list[Claim]:
    if section == CERTIFICATIONS_SECTION:
        # A technology named inside a credential title is part of the
        # credential, not a separate skill claim. The certification claim and
        # the cross-category comparator already relate it to a stated skill.
        return []
    claims: list[Claim] = []
    for name, start, end in skill_mentions(line.text):
        support = (
            Support.EXPLICIT_CLAIM
            if section == SKILLS_SECTION or _explicit_marker_before(line.text, start)
            else Support.KEYWORD_MENTION
        )
        attributes = [_attribute("name", name)]
        proficiency = _proficiency_before(line.text, start)
        if proficiency:
            attributes.append(_attribute("proficiency", proficiency))
        claims.append(
            _make_claim(
                document,
                segment,
                ClaimCategory.SKILL,
                name,
                line.text[start:end],
                attributes,
                line.start + start,
                line.start + end,
                support,
            )
        )
    return claims


def _language_claims(
    document: _Document,
    segment: _Segment,
    line: Line,
    section: str,
) -> list[Claim]:
    claims: list[Claim] = []
    for name, start, end in language_mentions(line.text):
        support = (
            Support.EXPLICIT_CLAIM
            if section == LANGUAGES_SECTION
            else Support.KEYWORD_MENTION
        )
        attributes = [_attribute("name", name)]
        level = None
        tail = line.text[end:]
        paren = re.match(r"^\s*\(\s*([A-Za-z0-9 +/]{1,20})\s*\)", tail)
        if paren and paren.group(1).strip().casefold() in LANGUAGE_LEVELS:
            level = paren.group(1).strip().casefold()
            end += paren.end()
        if level:
            attributes.append(_attribute("proficiency", level))
        dated = re.match(r"^\s*[,;–—-]\s*((?:19|20)\d{2})(?![0-9])", line.text[end:])
        if dated is not None:
            attributes.append(_attribute("date", dated.group(1)))
            end += dated.end()
        claims.append(
            _make_claim(
                document,
                segment,
                ClaimCategory.LANGUAGE,
                name,
                line.text[start:end],
                attributes,
                line.start + start,
                line.start + end,
                support,
            )
        )
    return claims


_GRADUATION = re.compile(
    r"graduated\s*(?:in|on)?\s*((?:19|20)\d{2})(?![0-9])",
    re.IGNORECASE,
)


def _graduation_claims(
    document: _Document,
    segment: _Segment,
    line: Line,
) -> list[Claim]:
    """Read an explicit statement about the year a qualification was finished."""
    match = _GRADUATION.search(line.text)
    if match is None:
        return []
    return [
        _make_claim(
            document,
            segment,
            ClaimCategory.EDUCATION,
            "graduation",
            match.group(0),
            [_attribute("graduation_year", match.group(1))],
            line.start + match.start(),
            line.start + match.end(),
            Support.EXPLICIT_CLAIM,
        )
    ]


def _employment_claims(
    document: _Document,
    segment: _Segment,
    line: Line,
) -> list[Claim]:
    parsed = parse_employment_line(line.text)
    if parsed is None:
        return []
    claims: list[Claim] = []
    role = parsed["role"]
    base_roles = sorted(role_variants(role))
    subject = base_roles[0]
    attributes = [_attribute("role", role)]
    if parsed["organization"]:
        attributes.append(_attribute("organization", parsed["organization"]))
    if parsed["start"]:
        attributes.append(_attribute("start", parsed["start"]))
    if parsed["end"]:
        attributes.append(_attribute("end", parsed["end"]))
    if parsed["duration_months"] is not None:
        attributes.append(_attribute("duration_months", parsed["duration_months"]))
        attributes.append(
            _attribute("duration_exact", "exact" if parsed["duration_exact"] else "at_least")
        )
    claims.append(
        _make_claim(
            document,
            segment,
            ClaimCategory.EMPLOYMENT,
            subject,
            role,
            attributes,
            line.start,
            line.end,
            Support.EXPLICIT_CLAIM,
        )
    )
    if parsed["organization"]:
        organization = parsed["organization"]
        organization_attributes = [_attribute("name", organization)]
        organization_attributes.append(_attribute("role", role))
        if parsed["start"]:
            organization_attributes.append(_attribute("start", parsed["start"]))
        if parsed["end"]:
            organization_attributes.append(_attribute("end", parsed["end"]))
        claims.append(
            _make_claim(
                document,
                segment,
                ClaimCategory.ORGANIZATION,
                normalise(organization),
                organization,
                organization_attributes,
                line.start,
                line.end,
                Support.EXPLICIT_CLAIM,
            )
        )
    return claims


def _degree_attributes(parsed: Mapping[str, Any]) -> list[ClaimAttribute]:
    """The attributes a degree statement states.

    A degree claim carries the same identity attributes as the education
    claim it comes from, so two degrees can only be merged when the sources
    state the institution or the dates that identify them.
    """
    attributes = [
        _attribute("level", parsed["level"]),
        _attribute("field", parsed["field"]),
    ]
    if parsed["institution"]:
        attributes.append(_attribute("institution", parsed["institution"]))
    if parsed["start"]:
        attributes.append(_attribute("start", parsed["start"]))
    if parsed["end"]:
        attributes.append(_attribute("end", parsed["end"]))
    return attributes


def _education_claims(
    document: _Document,
    segment: _Segment,
    line: Line,
) -> list[Claim]:
    parsed = parse_education_line(line.text)
    if parsed is None:
        return []
    claims: list[Claim] = []
    attributes = _degree_attributes(parsed)
    claims.append(
        _make_claim(
            document,
            segment,
            ClaimCategory.EDUCATION,
            normalise(parsed["field"]),
            parsed["field"],
            attributes,
            line.start,
            line.end,
            Support.EXPLICIT_CLAIM,
        )
    )
    claims.append(
        _make_claim(
            document,
            segment,
            ClaimCategory.DEGREE,
            f"{parsed['level']}|{normalise(parsed['field'])}",
            f"{parsed['level']} {parsed['field']}",
            _degree_attributes(parsed),
            line.start,
            line.end,
            Support.EXPLICIT_CLAIM,
        )
    )
    if parsed["institution"]:
        institution = parsed["institution"]
        claims.append(
            _make_claim(
                document,
                segment,
                ClaimCategory.INSTITUTION,
                normalise(institution),
                institution,
                [_attribute("name", institution)],
                line.start,
                line.end,
                Support.EXPLICIT_CLAIM,
            )
        )
    return claims


def _project_claims(
    document: _Document,
    segment: _Segment,
    line: Line,
) -> list[Claim]:
    parsed = parse_project_line(line.text)
    if parsed is None:
        return []
    name = parsed["name"]
    description = parsed["description"]
    subject = normalise(name)
    claims: list[Claim] = []

    cleaned, bullet_offset = strip_bullet(line.text)
    position = cleaned.find(name)
    if position < 0:
        position = 0
    title_start = line.start + bullet_offset + position
    title_end = title_start + len(name)
    description_offset = (
        cleaned.find(description, position + len(name)) if description else -1
    )
    if description_offset < 0:
        description_offset = position + len(name)
    description_start = line.start + bullet_offset + description_offset

    mentions = skill_mentions(description)
    technologies = sorted({mention[0] for mention in mentions})
    attributes = [_attribute("name", name)]
    if description:
        attributes.append(_attribute("description", description))
    if technologies:
        attributes.append(_attribute("technologies", ", ".join(technologies)))
    claims.append(
        _make_claim(
            document,
            segment,
            ClaimCategory.PROJECT,
            subject,
            name,
            attributes,
            title_start,
            title_end,
            Support.EXPLICIT_CLAIM,
        )
    )

    seen: set[str] = set()
    for technology, start, end in mentions:
        if technology in seen:
            continue
        seen.add(technology)
        claims.append(
            _make_claim(
                document,
                segment,
                ClaimCategory.TECHNOLOGY,
                technology,
                description[start:end],
                [_attribute("name", technology), _attribute("project", name)],
                description_start + start,
                description_start + end,
                Support.EXPLICIT_CLAIM,
            )
        )

    for clause_start, clause_end, clause in _clauses(description):
        statement = parse_statement(clause)
        # An achievement is only claimed when the statement carries a genuine
        # numeric quantity. A technology named in the statement makes it a
        # contribution, never a measurement.
        category = (
            ClaimCategory.ACHIEVEMENT
            if statement.quantities
            else ClaimCategory.CONTRIBUTION
        )
        clause_attributes = [
            _attribute("text", clause),
            _attribute("project", name),
            _attribute("template", statement.template),
        ]
        if statement.quantities:
            clause_attributes.append(
                _attribute("quantities", ", ".join(statement.quantities))
            )
        if statement.technologies:
            clause_attributes.append(
                _attribute("technologies", ", ".join(statement.technologies))
            )
        claims.append(
            _make_claim(
                document,
                segment,
                category,
                subject,
                name,
                clause_attributes,
                description_start + clause_start,
                description_start + clause_end,
                Support.EXPLICIT_CLAIM,
            )
        )
    return claims


def _certification_claims(
    document: _Document,
    segment: _Segment,
    line: Line,
) -> list[Claim]:
    parsed = parse_certification_line(line.text)
    if parsed is None:
        return []
    name = parsed["name"]
    attributes = [_attribute("name", name)]
    if parsed["issuer"]:
        attributes.append(_attribute("issuer", parsed["issuer"]))
    if parsed["date"]:
        attributes.append(_attribute("date", parsed["date"]))
    cleaned, bullet_offset = strip_bullet(line.text)
    position = cleaned.find(name)
    if position < 0:
        position = 0
    start = line.start + bullet_offset + position
    return [
        _make_claim(
            document,
            segment,
            ClaimCategory.CERTIFICATION,
            normalise(name),
            name,
            attributes,
            start,
            start + len(name),
            Support.EXPLICIT_CLAIM,
        )
    ]


def extract_claims(documents: Sequence[_Document]) -> list[Claim]:
    """Extract every typed claim the documents state.

    The function is pure and deterministic: the same documents always yield
    the same claims, in the same order, with the same identifiers.
    """
    claims: list[Claim] = []
    for document in documents:
        if document.status not in {"extracted", "partial"}:
            continue
        section = ""
        for segment in document.segments:
            for line in iter_lines(segment.text):
                if not line.text.strip():
                    continue
                heading = match_heading(line.text)
                if heading is not None:
                    section = heading
                    continue
                claims.extend(_skill_claims(document, segment, line, section))
                claims.extend(_language_claims(document, segment, line, section))
                claims.extend(_graduation_claims(document, segment, line))
                if section == EXPERIENCE_SECTION:
                    claims.extend(_employment_claims(document, segment, line))
                if section == EDUCATION_SECTION:
                    claims.extend(_education_claims(document, segment, line))
                if section == PROJECTS_SECTION:
                    claims.extend(_project_claims(document, segment, line))
                if section == CERTIFICATIONS_SECTION:
                    claims.extend(_certification_claims(document, segment, line))
    return claims
