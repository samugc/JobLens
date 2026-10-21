from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class Decision(str, Enum):
    APPLY = "APPLY"
    AMBITIOUS = "APPLY—AMBITIOUS"
    INVESTIGATE = "INVESTIGATE MORE"
    DEPRIORITIZE = "DO NOT PRIORITIZE"
    DISCARD = "DISCARD"


class ConstraintLevel(str, Enum):
    SOFT_GAP = "SOFT_GAP"
    STRETCH = "STRETCH"
    BLOCKER = "BLOCKER"


class EvidenceStatus(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    NEEDS_INVESTIGATION = "NEEDS_INVESTIGATION"


@dataclass(frozen=True)
class EvidenceAssessment:
    status: EvidenceStatus
    missing_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConstraintAssessment:
    name: str
    level: ConstraintLevel
    reason: str


@dataclass(frozen=True)
class CandidateProfile:
    degrees: tuple[str, ...]
    skills: frozenset[str]
    preferred_locations: tuple[str, ...] = ()
    target_families: tuple[str, ...] = ()
    max_required_years: int = 2
    visa_sponsorship_needed: bool = False

    @classmethod
    def from_iterables(
        cls,
        *,
        degrees: Iterable[str],
        skills: Iterable[str],
        preferred_locations: Iterable[str] = (),
        target_families: Iterable[str] = (),
        max_required_years: int = 2,
        visa_sponsorship_needed: bool = False,
    ) -> "CandidateProfile":
        return cls(
            degrees=tuple(degrees),
            skills=frozenset(s.lower() for s in skills),
            preferred_locations=tuple(preferred_locations),
            target_families=tuple(target_families),
            max_required_years=max_required_years,
            visa_sponsorship_needed=visa_sponsorship_needed,
        )


@dataclass(frozen=True)
class JobPosting:
    title: str
    company: str
    location: str
    description: str
    required_skills: frozenset[str] = field(default_factory=frozenset)
    preferred_skills: frozenset[str] = field(default_factory=frozenset)
    years_required: int | None = None
    seniority: str | None = None
    remote: bool = False
    source_url: str | None = None

    @classmethod
    def build(
        cls,
        *,
        title: str,
        company: str,
        location: str,
        description: str,
        required_skills: Iterable[str] = (),
        preferred_skills: Iterable[str] = (),
        years_required: int | None = None,
        seniority: str | None = None,
        remote: bool = False,
        source_url: str | None = None,
    ) -> "JobPosting":
        return cls(
            title=title,
            company=company,
            location=location,
            description=description,
            required_skills=frozenset(s.lower() for s in required_skills),
            preferred_skills=frozenset(s.lower() for s in preferred_skills),
            years_required=years_required,
            seniority=seniority,
            remote=remote,
            source_url=source_url,
        )


@dataclass(frozen=True)
class ScoreComponent:
    name: str
    value: float
    reason: str


@dataclass(frozen=True)
class MatchResult:
    score: float
    decision: Decision
    strengths: tuple[str, ...]
    gaps: tuple[str, ...]
    components: tuple[ScoreComponent, ...]
    constraints: tuple[ConstraintAssessment, ...] = ()
    evidence: EvidenceAssessment = EvidenceAssessment(EvidenceStatus.SUFFICIENT)
