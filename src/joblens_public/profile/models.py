"""Typed models for evidence-grounded candidate fact proposals.

The models are plain, frozen dataclasses with explicit ``as_dict`` methods, so
the JSON envelope is a contract rather than an accident of serialisation.

Nothing in this module interprets a document. A proposal always points at the
exact text that produced it, and the offsets are Python string indices into
the source segment, so ``segment_text[start:end] == quote`` always holds.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

#: Version of the proposal envelope produced by the profile engine.
PROFILE_SCHEMA_VERSION = "0.1"

#: Version of the parser contract the proposals are derived from.
PARSER_SCHEMA_VERSION = "1.1"


class ProfileError(ValueError):
    """Raised when an input or a review action is not valid."""


class Category(str, Enum):
    """The kinds of fact the engine may propose."""

    SKILL = "skill"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    PROJECT = "project"
    LANGUAGE = "language"
    CERTIFICATION = "certification"


class Support(str, Enum):
    """How a piece of evidence supports a proposal."""

    EXPLICIT_CLAIM = "explicit_claim"
    KEYWORD_MENTION = "keyword_mention"


class ProposalStatus(str, Enum):
    """The review state of a proposal."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class EvidenceReference:
    """One exact quotation that supports a proposal.

    ``start`` and ``end`` are Python string indices into
    ``documents[].segments[segment_index].text`` of the parser response, so
    ``segment_text[start:end]`` is exactly ``quote``.
    """

    document_id: str
    segment_index: int
    locator: Mapping[str, Any]
    quote: str
    start: int
    end: int
    support: Support

    def as_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "segment_index": self.segment_index,
            "locator": dict(self.locator),
            "quote": self.quote,
            "start": self.start,
            "end": self.end,
            "support": self.support.value,
        }


@dataclass(frozen=True)
class ResolutionHint:
    """An optional, advisory preference for one conflict.

    The hint never approves anything: it says which claim is worth keeping
    first, and it always asks for a user confirmation.
    """

    strategy: str
    keep_proposal_ids: tuple[str, ...]
    explanation: str
    requires_user_confirmation: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "keep_proposal_ids": list(self.keep_proposal_ids),
            "explanation": self.explanation,
            "requires_user_confirmation": self.requires_user_confirmation,
        }


@dataclass(frozen=True)
class Conflict:
    """An unresolved conflict between two or more proposals."""

    conflict_id: str
    kind: str
    category: Category
    proposal_ids: tuple[str, ...]
    message: str
    resolution_hint: ResolutionHint | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "conflict_id": self.conflict_id,
            "kind": self.kind,
            "category": self.category.value,
            "proposal_ids": list(self.proposal_ids),
            "message": self.message,
        }
        if self.resolution_hint is not None:
            payload["resolution_hint"] = self.resolution_hint.as_dict()
        return payload


@dataclass(frozen=True)
class Proposal:
    """A reviewable fact proposal, always backed by exact evidence."""

    proposal_id: str
    category: Category
    value: Mapping[str, Any]
    status: ProposalStatus
    evidence: tuple[EvidenceReference, ...]
    conflicts: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "category": self.category.value,
            "value": dict(self.value),
            "status": self.status.value,
            "evidence": [item.as_dict() for item in self.evidence],
            "conflicts": list(self.conflicts),
        }


@dataclass(frozen=True)
class DocumentReference:
    """Provenance of one source document, retained by reference.

    The document text is not copied into the envelope. The consumer keeps the
    parser response and resolves the evidence through ``document_id`` and
    ``segment_index``.
    """

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
class ProfileEnvelope:
    """The versioned proposal envelope."""

    profile_schema_version: str
    parser_schema_version: str
    job_id: str | None
    documents: tuple[DocumentReference, ...]
    proposals: tuple[Proposal, ...]
    conflicts: tuple[Conflict, ...] = ()
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile_schema_version": self.profile_schema_version,
            "parser_schema_version": self.parser_schema_version,
            "job_id": self.job_id,
            "documents": [document.as_dict() for document in self.documents],
            "proposals": [proposal.as_dict() for proposal in self.proposals],
            "conflicts": [conflict.as_dict() for conflict in self.conflicts],
            "warnings": list(self.warnings),
        }


__all__ = [
    "PARSER_SCHEMA_VERSION",
    "PROFILE_SCHEMA_VERSION",
    "Category",
    "Conflict",
    "DocumentReference",
    "EvidenceReference",
    "ProfileEnvelope",
    "ProfileError",
    "Proposal",
    "ProposalStatus",
    "ResolutionHint",
    "Support",
]
