"""Deterministic extraction of requirements from a pasted job posting.

A job posting is untrusted content: it may influence relevance ranking and
gap reporting, but it is never a source of candidate facts and it is never
executed. Only closed-vocabulary terms and explicitly labelled sections are
extracted, and every requirement is reported as a string a human can read.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from joblens_public.profile.lexicon import SKILL_TERMS
from joblens_public.reconcile.text import normalise
from joblens_public.requirements import technologies_in

#: Version of the job-posting contract.
JOB_POSTING_VERSION = "0.1"

#: Section headings that mark a requirement block.
_REQUIRED_HEADINGS = (
    "required",
    "requirements",
    "requirements and qualifications",
    "qualifications",
    "must have",
    "must-have",
    "must haves",
    "essential",
    "mandatory",
    "what you need",
    "what you'll need",
    "what you will need",
    "what we need",
    "what we're looking for",
    "what we are looking for",
    "who you are",
    "about you",
    "your profile",
    "you have",
    "you'll have",
    "you will have",
    "skills and experience",
    "minimum",
)
_PREFERRED_HEADINGS = (
    "preferred",
    "preferred qualifications",
    "nice to have",
    "nice-to-have",
    "nice to haves",
    "bonus",
    "bonus points",
    "plus",
    "desired",
    "advantageous",
    "optional",
)
_RESPONSIBILITY_HEADINGS = (
    "responsibilities",
    "duties",
    "what you will do",
    "what you'll do",
    "what you'll be doing",
    "what you will be doing",
    "day to day",
    "the role",
    "role",
    "about the role",
    "job description",
    "key tasks",
)
_EXPERIENCE_HEADINGS = (
    "experience",
    "years",
)
_ABOUT_HEADINGS = (
    "about",
    "about us",
    "about the company",
    "company",
    "who we are",
    "benefits",
    "perks",
    "we offer",
    "why join",
)
_NOISE = (
    "apply now",
    "apply today",
    "share",
    "share this job",
    "save",
    "save job",
    "report this job",
    "cookie",
    "cookie policy",
    "privacy policy",
    "terms of use",
    "sign in",
    "log in",
    "create account",
    "home",
)
#: Prefixes that mark a whole line as page chrome even when it carries a suffix.
_NOISE_PREFIXES = (
    "apply now",
    "apply today",
    "save job",
    "report this job",
    "cookie ",
    "privacy policy",
    "terms of use",
    "sign in",
    "log in",
    "create account",
    "share this job",
)


def _noise_key(line: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", line.casefold()).strip()


_NOISE_KEYS = frozenset(_noise_key(phrase) for phrase in _NOISE)


def _is_noise(line: str) -> bool:
    key = _noise_key(line)
    if len(key) < 2:
        return True
    # Exact labels and known page-chrome prefixes are dropped. Matching is not
    # a substring search: "Shared on-call rotation" and "Home automation" are
    # content, while the "Share" and "Home" navigation labels are not.
    return key in _NOISE_KEYS or key.startswith(_NOISE_PREFIXES)


def _heading_kind(line: str) -> str | None:
    lowered = normalise(line).rstrip(":").strip()
    if not lowered or len(lowered) > 60:
        return None
    # A heading is short and has no verb-like sentence structure.
    if lowered.endswith((".", "!", "?")):
        return None
    for group, kind in (
        (_REQUIRED_HEADINGS, "required"),
        (_PREFERRED_HEADINGS, "preferred"),
        (_RESPONSIBILITY_HEADINGS, "responsibilities"),
        (_EXPERIENCE_HEADINGS, "experience"),
        (_ABOUT_HEADINGS, "about"),
    ):
        if any(lowered == heading or lowered == heading + ":" or lowered.startswith(heading + ":") for heading in group):
            return kind
    return None


def _clean_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # Strip common bullet markers.
        line = re.sub(r"^[\-\*\u2022\u2013\u2014]+\s*", "", line)
        line = line.strip()
        if not line or _is_noise(line):
            continue
        lines.append(line)
    return lines


def _surface_matches(surface: str, text: str) -> bool:
    """Match a technology surface form as a token, never as a substring.

    A short alias such as ``ts`` must not match inside ``tests``, and ``go``
    must not match inside ``good``. Symbols such as ``c++`` and ``.net`` keep
    their own boundaries because the lookarounds only reject alphanumerics.
    """
    plural = (
        "s?"
        if len(surface) > 1
        and surface[-1:].isalnum()
        and not surface.casefold().endswith("s")
        else ""
    )
    pattern = re.compile(
        r"(?<![A-Za-z0-9])" + re.escape(surface) + plural + r"(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    return pattern.search(text) is not None


def _extract_technologies(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for canonical, surface, _unambiguous in SKILL_TERMS:
        if _surface_matches(surface, text) and canonical not in found:
            found.append(canonical)
    # Keep a stable, readable order.
    return tuple(found)


def _split_sections(lines: list[str]) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    current_kind = "general"
    current: list[str] = []
    for line in lines:
        kind = _heading_kind(line)
        if kind is not None:
            if current:
                sections.append((current_kind, current))
            current_kind = kind
            current = []
        else:
            current.append(line)
    if current:
        sections.append((current_kind, current))
    return sections


@dataclass(frozen=True)
class JobPosting:
    """A parsed, untrusted job posting."""

    job_posting_version: str = JOB_POSTING_VERSION
    title: str | None = None
    company: str | None = None
    location: str | None = None
    raw_text: str = ""
    required: tuple[str, ...] = ()
    preferred: tuple[str, ...] = ()
    technologies: tuple[str, ...] = ()
    required_technologies: tuple[str, ...] = ()
    preferred_technologies: tuple[str, ...] = ()
    responsibilities: tuple[str, ...] = ()
    experience_expectations: tuple[str, ...] = ()
    other_context: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_posting_version": self.job_posting_version,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "raw_text": self.raw_text,
            "required": list(self.required),
            "preferred": list(self.preferred),
            "technologies": list(self.technologies),
            "required_technologies": list(self.required_technologies),
            "preferred_technologies": list(self.preferred_technologies),
            "responsibilities": list(self.responsibilities),
            "experience_expectations": list(self.experience_expectations),
            "other_context": list(self.other_context),
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "JobPosting":
        if not isinstance(payload, Mapping):
            raise ValueError("a job posting must be an object")
        title = payload.get("title")
        company = payload.get("company")
        location = payload.get("location")
        raw_text = payload.get("raw_text", "")
        if not isinstance(raw_text, str):
            raise ValueError("raw_text must be a string")
        for name, value in (("title", title), ("company", company), ("location", location)):
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{name} must be a string or null")
        return cls(
            job_posting_version=str(payload.get("job_posting_version", JOB_POSTING_VERSION)),
            title=title,
            company=company,
            location=location,
            raw_text=raw_text,
            required=_string_tuple(payload.get("required", [])),
            preferred=_string_tuple(payload.get("preferred", [])),
            technologies=_string_tuple(payload.get("technologies", [])),
            required_technologies=_string_tuple(payload.get("required_technologies", [])),
            preferred_technologies=_string_tuple(payload.get("preferred_technologies", [])),
            responsibilities=_string_tuple(payload.get("responsibilities", [])),
            experience_expectations=_string_tuple(payload.get("experience_expectations", [])),
            other_context=_string_tuple(payload.get("other_context", [])),
        )


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("expected an array of strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("expected strings")
        result.append(item)
    return tuple(result)


def parse_job_posting(
    text: str,
    *,
    title: str | None = None,
    company: str | None = None,
    location: str | None = None,
) -> JobPosting:
    """Parse a pasted job posting into structured requirements."""
    if not isinstance(text, str):
        raise ValueError("job posting text must be a string")
    lines = _clean_lines(text)
    sections = _split_sections(lines)

    required: list[str] = []
    preferred: list[str] = []
    responsibilities: list[str] = []
    experience: list[str] = []
    about: list[str] = []
    general: list[str] = []

    for kind, block in sections:
        if kind == "required":
            required.extend(block)
        elif kind == "preferred":
            preferred.extend(block)
        elif kind == "responsibilities":
            responsibilities.extend(block)
        elif kind == "experience":
            experience.extend(block)
        elif kind == "about":
            about.extend(block)
        else:
            general.extend(block)

    # Technologies: required/preferred sections first, then everything else.
    technology_source = " ".join(required + preferred + responsibilities + general)
    technologies = list(_extract_technologies(technology_source))

    def technologies_from(lines: list[str]) -> tuple[str, ...]:
        found: list[str] = []
        for line in lines:
            for canonical in technologies_in(line):
                if canonical not in found:
                    found.append(canonical)
        return tuple(found)

    required_technologies = technologies_from(required)
    preferred_technologies = technologies_from(preferred)
    # Requirement-side aliases (for example "Go") are not profile vocabulary,
    # but a posting that names them must still be able to report them.
    for canonical in required_technologies + preferred_technologies:
        if canonical not in technologies:
            technologies.append(canonical)
    technologies = tuple(technologies)

    # Required qualifications: short bullet lines from required sections, dedup.
    required_qualifications: list[str] = []
    for line in required:
        if line not in required_qualifications:
            required_qualifications.append(line)
    # If no explicit required section, treat general short lines as required.
    if not required_qualifications and general:
        for line in general:
            if len(line) <= 120 and line not in required_qualifications:
                required_qualifications.append(line)

    preferred_qualifications: list[str] = []
    for line in preferred:
        if line not in preferred_qualifications:
            preferred_qualifications.append(line)

    responsibility_lines: list[str] = []
    for line in responsibilities:
        if line not in responsibility_lines:
            responsibility_lines.append(line)

    experience_lines: list[str] = []
    for line in experience + general:
        if re.search(r"\d+\s*(?:\+?\s*years?|months?)", line, re.IGNORECASE) and line not in experience_lines:
            experience_lines.append(line)
    # Also capture role expectations from required lines mentioning years.
    for line in required:
        if re.search(r"\d+\s*(?:\+?\s*years?|months?)", line, re.IGNORECASE) and line not in experience_lines:
            experience_lines.append(line)

    other_context: list[str] = []
    for line in about:
        if line not in other_context:
            other_context.append(line)

    return JobPosting(
        title=title,
        company=company,
        location=location,
        raw_text=text,
        required=tuple(required_qualifications),
        preferred=tuple(preferred_qualifications),
        technologies=technologies,
        required_technologies=required_technologies,
        preferred_technologies=preferred_technologies,
        responsibilities=tuple(responsibility_lines),
        experience_expectations=tuple(experience_lines),
        other_context=tuple(other_context),
    )


__all__ = [
    "JOB_POSTING_VERSION",
    "JobPosting",
    "parse_job_posting",
]
