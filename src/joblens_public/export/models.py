"""Canonical, renderer-agnostic CV model.

The adapter converts a validated CvDraft into these dataclasses. Rendering
code depends only on this module, so schema adjustments are absorbed by the
adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CanonicalTargetJob:
    title: str | None = None
    company: str | None = None


@dataclass(frozen=True)
class CanonicalCandidate:
    full_name: str
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: tuple[str, ...] = ()


@dataclass(frozen=True)
class CanonicalItem:
    item_id: str
    text: str
    approved_fact_ids: tuple[str, ...]
    review_status: str
    heading: str | None = None
    subheading: str | None = None
    period: str | None = None
    location: str | None = None
    provenance: str = "source"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CanonicalSection:
    section_id: str
    kind: str
    title: str
    items: tuple[CanonicalItem, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CanonicalDraft:
    cv_draft_version: str
    target_job: CanonicalTargetJob
    candidate: CanonicalCandidate
    sections: tuple[CanonicalSection, ...]
    warnings: tuple[str, ...] = ()
    unmet_requirements: tuple[str, ...] = ()
    evidence_mode: str = "cited_facts"
    raw: Any = None


SUPPORTED_SCHEMA_VERSIONS = {"0.1"}

APPROVED_STATUS = "approved"
NEEDS_REVIEW_STATUS = "needs_review"