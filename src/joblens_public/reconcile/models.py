"""Typed models for the professional claim reconciliation layer.

The reconciliation layer is a separate artifact from the profile envelope.
It never changes profile schema 0.1, parser schema 1.1 or transport 1.0: it
reads the same source documents and writes its own versioned report.

Three things stay apart, and the model keeps them apart:

* what a source **states** — a :class:`Claim` with exact evidence;
* what the engine **infers** — a :class:`Relationship` between two claims;
* what the engine **recommends** — a :class:`ResolutionDecision`;
* what the **user confirms** — never the engine: every decision and every
  consolidated claim carries ``approval_state`` ``not_approved``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from joblens_public.profile.models import EvidenceReference, Support

#: Version of the reconciliation report.
RECONCILIATION_SCHEMA_VERSION = "0.1"

#: Version of the profile contract the report is compatible with.
PROFILE_SCHEMA_VERSION = "0.1"

#: Version of the parser contract the claims are derived from.
PARSER_SCHEMA_VERSION = "1.1"

#: The engine never approves anything. Every decision and every consolidated
#: claim states that no human approval has happened, so no consumer can read
#: an approval into the report.
APPROVAL_STATE_NOT_APPROVED = "not_approved"

__all__ = [
    "APPROVAL_STATE_NOT_APPROVED",
    "PARSER_SCHEMA_VERSION",
    "PROFILE_SCHEMA_VERSION",
    "RECONCILIATION_SCHEMA_VERSION",
    "Claim",
    "ClaimAttribute",
    "ClaimCategory",
    "ConsolidatedClaim",
    "DocumentReference",
    "ReconciliationError",
    "ReconciliationReport",
    "Relation",
    "Relationship",
    "Resolution",
    "ResolutionDecision",
    "EvidenceReference",
    "Support",
]


class ReconciliationError(ValueError):
    """Raised when an input or a semantic judgement is not valid."""


class ClaimCategory(str, Enum):
    """The kinds of professional fact the engine can extract."""

    SKILL = "skill"
    EMPLOYMENT = "employment"
    ORGANIZATION = "organization"
    EDUCATION = "education"
    INSTITUTION = "institution"
    DEGREE = "degree"
    PROJECT = "project"
    TECHNOLOGY = "technology"
    CONTRIBUTION = "contribution"
    LANGUAGE = "language"
    CERTIFICATION = "certification"
    ACHIEVEMENT = "achievement"


class Relation(str, Enum):
    """How two claims relate to each other."""

    EQUIVALENT = "equivalent"
    DUPLICATE = "duplicate"
    COMPLEMENTARY = "complementary"
    MORE_SPECIFIC = "more_specific"
    LESS_SPECIFIC = "less_specific"
    POTENTIALLY_CONFLICTING = "potentially_conflicting"
    CONTRADICTORY = "contradictory"
    TEMPORAL_UPDATE = "temporal_update"
    UNRELATED = "unrelated"
    UNCERTAIN = "uncertain"


class Resolution(str, Enum):
    """The outcome of reconciling a group of claims."""

    #: Safe equivalence: the claims are merged, every source is preserved.
    AUTO_CONSOLIDATE = "auto_consolidate"
    #: A defensible preference exists, but a user has to confirm it.
    RECOMMEND = "recommend"
    #: The evidence is inadequate or contradictory: a human has to decide.
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class ClaimAttribute:
    """One typed attribute of a claim.

    ``value`` keeps the original form and ``normalized`` the comparable one.
    A missing attribute is absent, never guessed.
    """

    name: str
    value: Any
    normalized: str

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value, "normalized": self.normalized}


@dataclass(frozen=True)
class Claim:
    """One statement made by a source, with its exact evidence.

    ``subject`` is the normalised entity the claim is about, ``subject_label``
    the original wording. ``attributes`` holds only what the source actually
    states.
    """

    claim_id: str
    category: ClaimCategory
    subject: str
    subject_label: str
    attributes: tuple[ClaimAttribute, ...]
    evidence: tuple[EvidenceReference, ...]
    qualifier: str = Support.EXPLICIT_CLAIM.value

    def attribute(self, name: str) -> str | None:
        """Return the normalised value of an attribute, or ``None``."""
        for item in self.attributes:
            if item.name == name:
                return item.normalized
        return None

    def attribute_value(self, name: str) -> Any:
        """Return the original value of an attribute, or ``None``."""
        for item in self.attributes:
            if item.name == name:
                return item.value
        return None

    def attribute_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.attributes)

    @property
    def document_ids(self) -> tuple[str, ...]:
        return tuple(sorted({item.document_id for item in self.evidence}))

    def as_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "category": self.category.value,
            "subject": self.subject,
            "subject_label": self.subject_label,
            "attributes": [item.as_dict() for item in self.attributes],
            "evidence": [item.as_dict() for item in self.evidence],
            "qualifier": self.qualifier,
        }


@dataclass(frozen=True)
class Relationship:
    """An explicit relationship between two claims."""

    relationship_id: str
    relation: Relation
    left_claim_id: str
    right_claim_id: str
    attributes: tuple[str, ...] = ()
    reason: str = ""
    basis: str = "generic"
    evidence: tuple[EvidenceReference, ...] = ()
    semantic: bool = False

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "relationship_id": self.relationship_id,
            "relation": self.relation.value,
            "left_claim_id": self.left_claim_id,
            "right_claim_id": self.right_claim_id,
            "attributes": list(self.attributes),
            "reason": self.reason,
            "basis": self.basis,
            "evidence": [item.as_dict() for item in self.evidence],
        }
        if self.semantic:
            payload["semantic"] = True
        return payload


@dataclass(frozen=True)
class ConsolidatedClaim:
    """A group of claims that were merged because they are safe equivalences.

    A consolidated claim keeps every source and every attribute, and it keeps
    the qualifiers of the claims it merges apart: a merged keyword mention is
    still visible as a mention. It is never approved by the engine.
    """

    subject: str
    category: ClaimCategory
    subject_label: str
    attributes: tuple[ClaimAttribute, ...]
    claim_ids: tuple[str, ...]
    evidence: tuple[EvidenceReference, ...]
    qualifiers: tuple[str, ...] = ()
    approval_state: str = APPROVAL_STATE_NOT_APPROVED

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "category": self.category.value,
            "subject_label": self.subject_label,
            "attributes": [item.as_dict() for item in self.attributes],
            "claim_ids": list(self.claim_ids),
            "evidence": [item.as_dict() for item in self.evidence],
            "qualifiers": list(self.qualifiers),
            "approval_state": self.approval_state,
        }


@dataclass(frozen=True)
class ResolutionDecision:
    """What the engine proposes to do with a group of related claims.

    The decision never approves anything. ``merge_claim_ids`` names the claims
    that are merged into a consolidated claim, and only ``auto_consolidate``
    uses it. A recommendation names the claim it would keep and the
    ``alternative_claim_ids`` it does not discard: they stay in the report
    until a person confirms the preference.
    """

    decision_id: str
    outcome: Resolution
    category: ClaimCategory
    subject: str
    subject_label: str
    keep_claim_ids: tuple[str, ...] = ()
    merge_claim_ids: tuple[str, ...] = ()
    alternative_claim_ids: tuple[str, ...] = ()
    relationship_ids: tuple[str, ...] = ()
    explanation: str = ""
    requires_user_confirmation: bool = True
    approval_state: str = APPROVAL_STATE_NOT_APPROVED

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "outcome": self.outcome.value,
            "category": self.category.value,
            "subject": self.subject,
            "subject_label": self.subject_label,
            "keep_claim_ids": list(self.keep_claim_ids),
            "merge_claim_ids": list(self.merge_claim_ids),
            "alternative_claim_ids": list(self.alternative_claim_ids),
            "relationship_ids": list(self.relationship_ids),
            "explanation": self.explanation,
            "requires_user_confirmation": self.requires_user_confirmation,
            "approval_state": self.approval_state,
        }


@dataclass(frozen=True)
class DocumentReference:
    """Provenance of one source document, retained by reference."""

    document_id: str
    index: int
    filename: str
    status: str
    format: str
    segment_count: int
    text_length: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "index": self.index,
            "filename": self.filename,
            "status": self.status,
            "format": self.format,
            "segment_count": self.segment_count,
            "text_length": self.text_length,
        }


@dataclass(frozen=True)
class ReconciliationReport:
    """The versioned reconciliation report."""

    reconciliation_schema_version: str
    parser_schema_version: str
    profile_schema_version: str
    job_id: str | None
    documents: tuple[DocumentReference, ...]
    claims: tuple[Claim, ...]
    relationships: tuple[Relationship, ...]
    decisions: tuple[ResolutionDecision, ...]
    consolidated: tuple[ConsolidatedClaim, ...] = ()
    warnings: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict[str, Any]:
        return {
            "reconciliation_schema_version": self.reconciliation_schema_version,
            "parser_schema_version": self.parser_schema_version,
            "profile_schema_version": self.profile_schema_version,
            "job_id": self.job_id,
            "documents": [item.as_dict() for item in self.documents],
            "claims": [item.as_dict() for item in self.claims],
            "relationships": [item.as_dict() for item in self.relationships],
            "decisions": [item.as_dict() for item in self.decisions],
            "consolidated": [item.as_dict() for item in self.consolidated],
            "warnings": list(self.warnings),
        }

    def claim(self, claim_id: str) -> Claim:
        for claim in self.claims:
            if claim.claim_id == claim_id:
                return claim
        raise ReconciliationError(f"unknown claim {claim_id!r}")

    def relationships_for(self, claim_id: str) -> tuple[Relationship, ...]:
        return tuple(
            item
            for item in self.relationships
            if claim_id in (item.left_claim_id, item.right_claim_id)
        )
