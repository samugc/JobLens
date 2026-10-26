"""Portable, human-approved candidate facts.

An :class:`ApprovedProfile` is the only input the CV generator trusts. It is
built from proposals a person explicitly approved, it carries the exact source
evidence of every fact, and it can be exported to and imported from a private
local JSON file. Nothing is approved by a model, a reconciliation
recommendation or the upload order, and nothing leaves the machine.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from joblens_public.profile.models import (
    PARSER_SCHEMA_VERSION,
    PROFILE_SCHEMA_VERSION,
    Category,
    DocumentReference,
    EvidenceReference,
    ProfileEnvelope,
    ProfileError,
)
from joblens_public.profile.review import ReviewState

#: Version of the approved-profile contract.
APPROVED_PROFILE_VERSION = "0.1"


class ApprovedProfileError(ProfileError):
    """Raised when an approved profile is malformed or inconsistent."""


@dataclass(frozen=True)
class CandidateContact:
    """Candidate contact details, always supplied by the user.

    Every field is optional and stays empty until the user provides it. The
    engine never invents a name, an e-mail or a phone number.
    """

    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "location": self.location,
            "links": list(self.links),
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "CandidateContact":
        if not isinstance(payload, Mapping):
            raise ApprovedProfileError("candidate contact must be an object")
        links = payload.get("links", [])
        if not isinstance(links, Sequence) or isinstance(links, (str, bytes)):
            raise ApprovedProfileError("candidate links must be an array of strings")
        normalised_links: list[str] = []
        for item in links:
            if not isinstance(item, str):
                raise ApprovedProfileError("candidate links must be strings")
            normalised_links.append(item)
        for field_name in ("full_name", "email", "phone", "location"):
            value = payload.get(field_name)
            if value is not None and not isinstance(value, str):
                raise ApprovedProfileError(f"candidate {field_name} must be a string or null")
        return cls(
            full_name=payload.get("full_name"),
            email=payload.get("email"),
            phone=payload.get("phone"),
            location=payload.get("location"),
            links=tuple(normalised_links),
        )


@dataclass(frozen=True)
class ApprovedFact:
    """One fact a person explicitly approved, with its exact evidence."""

    fact_id: str
    category: Category
    value: Mapping[str, Any]
    evidence: tuple[EvidenceReference, ...]
    source_document_ids: tuple[str, ...]
    review_sequence: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "category": self.category.value,
            "value": dict(self.value),
            "evidence": [item.as_dict() for item in self.evidence],
            "source_document_ids": list(self.source_document_ids),
            "review_sequence": self.review_sequence,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "ApprovedFact":
        if not isinstance(payload, Mapping):
            raise ApprovedProfileError("an approved fact must be an object")
        try:
            category = Category(payload["category"])
        except (KeyError, ValueError) as exc:
            raise ApprovedProfileError("unknown approved fact category") from exc
        fact_id = payload.get("fact_id")
        if not isinstance(fact_id, str) or not fact_id:
            raise ApprovedProfileError("an approved fact needs a non-empty fact_id")
        value = payload.get("value")
        if not isinstance(value, Mapping):
            raise ApprovedProfileError("an approved fact needs a value object")
        evidence_payload = payload.get("evidence")
        if not isinstance(evidence_payload, Sequence) or isinstance(evidence_payload, (str, bytes)):
            raise ApprovedProfileError("an approved fact needs an evidence array")
        evidence: list[EvidenceReference] = []
        for item in evidence_payload:
            if not isinstance(item, Mapping):
                raise ApprovedProfileError("evidence must be an object")
            try:
                evidence.append(
                    EvidenceReference(
                        document_id=str(item["document_id"]),
                        segment_index=int(item["segment_index"]),
                        locator=dict(item["locator"]) if isinstance(item["locator"], Mapping) else {},
                        quote=str(item["quote"]),
                        start=int(item["start"]),
                        end=int(item["end"]),
                        support=_parse_support(item.get("support", "explicit_claim")),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ApprovedProfileError("malformed evidence reference") from exc
        if not evidence:
            raise ApprovedProfileError("an approved fact needs at least one evidence reference")
        document_ids = payload.get("source_document_ids", [])
        if not isinstance(document_ids, Sequence) or isinstance(document_ids, (str, bytes)):
            raise ApprovedProfileError("source_document_ids must be an array")
        normalised_ids = tuple(str(item) for item in document_ids)
        sequence = payload.get("review_sequence", 0)
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            raise ApprovedProfileError("review_sequence must be an integer")
        return cls(
            fact_id=fact_id,
            category=category,
            value=dict(value),
            evidence=tuple(evidence),
            source_document_ids=normalised_ids,
            review_sequence=sequence,
        )


def _parse_support(value: Any) -> Any:
    from joblens_public.profile.models import Support

    try:
        return Support(value)
    except ValueError as exc:
        raise ApprovedProfileError("unknown evidence support") from exc


@dataclass(frozen=True)
class ApprovedProfile:
    """A portable set of facts a person explicitly approved."""

    approved_profile_version: str
    parser_schema_version: str
    profile_schema_version: str
    job_id: str | None
    documents: tuple[DocumentReference, ...]
    facts: tuple[ApprovedFact, ...]
    candidate: CandidateContact = field(default_factory=CandidateContact)
    review_sequence: int = 0
    review_history: tuple[Mapping[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "approved_profile_version": self.approved_profile_version,
            "parser_schema_version": self.parser_schema_version,
            "profile_schema_version": self.profile_schema_version,
            "job_id": self.job_id,
            "documents": [document.as_dict() for document in self.documents],
            "facts": [fact.as_dict() for fact in self.facts],
            "candidate": self.candidate.as_dict(),
            "review_sequence": self.review_sequence,
            "review_history": [dict(item) for item in self.review_history],
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "ApprovedProfile":
        if not isinstance(payload, Mapping):
            raise ApprovedProfileError("an approved profile must be a JSON object")
        try:
            version = str(payload["approved_profile_version"])
        except KeyError as exc:
            raise ApprovedProfileError("missing approved_profile_version") from exc
        if version != APPROVED_PROFILE_VERSION:
            raise ApprovedProfileError(
                f"unsupported approved profile version {version!r}"
            )
        parser_version = payload.get("parser_schema_version", PARSER_SCHEMA_VERSION)
        profile_version = payload.get("profile_schema_version", PROFILE_SCHEMA_VERSION)
        if parser_version != PARSER_SCHEMA_VERSION:
            raise ApprovedProfileError("incompatible parser schema version")
        if profile_version != PROFILE_SCHEMA_VERSION:
            raise ApprovedProfileError("incompatible profile schema version")
        job_id = payload.get("job_id")
        if job_id is not None and not isinstance(job_id, str):
            raise ApprovedProfileError("job_id must be a string or null")
        documents_payload = payload.get("documents", [])
        if not isinstance(documents_payload, Sequence) or isinstance(documents_payload, (str, bytes)):
            raise ApprovedProfileError("documents must be an array")
        documents: list[DocumentReference] = []
        for item in documents_payload:
            if not isinstance(item, Mapping):
                raise ApprovedProfileError("a document reference must be an object")
            try:
                documents.append(
                    DocumentReference(
                        document_id=str(item["document_id"]),
                        index=int(item["index"]),
                        filename=str(item["filename"]),
                        status=str(item["status"]),
                        format=str(item["format"]),
                        segment_count=int(item["segment_count"]),
                        text_length=int(item["text_length"]),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ApprovedProfileError("malformed document reference") from exc
        facts_payload = payload.get("facts", [])
        if not isinstance(facts_payload, Sequence) or isinstance(facts_payload, (str, bytes)):
            raise ApprovedProfileError("facts must be an array")
        facts: list[ApprovedFact] = []
        seen_ids: set[str] = set()
        for item in facts_payload:
            fact = ApprovedFact.from_dict(item)
            if fact.fact_id in seen_ids:
                raise ApprovedProfileError(f"duplicate fact id {fact.fact_id!r}")
            seen_ids.add(fact.fact_id)
            facts.append(fact)
        candidate = CandidateContact.from_dict(payload.get("candidate", {}))
        review_sequence = payload.get("review_sequence", 0)
        if not isinstance(review_sequence, int) or isinstance(review_sequence, bool):
            raise ApprovedProfileError("review_sequence must be an integer")
        history_payload = payload.get("review_history", [])
        if not isinstance(history_payload, Sequence) or isinstance(history_payload, (str, bytes)):
            raise ApprovedProfileError("review_history must be an array")
        history = tuple(dict(item) for item in history_payload if isinstance(item, Mapping))
        if len(history) != len(history_payload):
            raise ApprovedProfileError("review_history entries must be objects")
        warnings_payload = payload.get("warnings", [])
        if not isinstance(warnings_payload, Sequence) or isinstance(warnings_payload, (str, bytes)):
            raise ApprovedProfileError("warnings must be an array")
        warnings = tuple(str(item) for item in warnings_payload)
        return cls(
            approved_profile_version=version,
            parser_schema_version=str(parser_version),
            profile_schema_version=str(profile_version),
            job_id=job_id,
            documents=tuple(documents),
            facts=tuple(facts),
            candidate=candidate,
            review_sequence=review_sequence,
            review_history=history,
            warnings=warnings,
        )

    def facts_by_category(self, category: Category) -> tuple[ApprovedFact, ...]:
        return tuple(fact for fact in self.facts if fact.category is category)


def validate_approved_profile(
    profile: ApprovedProfile,
    source_response: Mapping[str, Any] | None = None,
) -> None:
    """Validate a profile, and its evidence against retained source material.

    Raises :class:`ApprovedProfileError` on any inconsistency. Fails closed.
    """
    document_by_id = {document.document_id: document for document in profile.documents}
    seen_fact_ids: set[str] = set()
    for fact in profile.facts:
        if fact.fact_id in seen_fact_ids:
            raise ApprovedProfileError(f"duplicate fact id {fact.fact_id!r}")
        seen_fact_ids.add(fact.fact_id)
        if not fact.evidence:
            raise ApprovedProfileError(f"fact {fact.fact_id!r} has no evidence")
        for evidence in fact.evidence:
            if evidence.document_id not in document_by_id:
                raise ApprovedProfileError(
                    f"fact {fact.fact_id!r} references an unknown document"
                )
            document = document_by_id[evidence.document_id]
            if evidence.segment_index < 0 or evidence.segment_index >= document.segment_count:
                raise ApprovedProfileError(
                    f"fact {fact.fact_id!r} references an invalid segment"
                )
            if evidence.start < 0 or evidence.end < evidence.start:
                raise ApprovedProfileError(
                    f"fact {fact.fact_id!r} has invalid offsets"
                )
            if source_response is not None:
                segment_text = _segment_text(source_response, evidence.document_id, evidence.segment_index)
                if segment_text is None:
                    raise ApprovedProfileError(
                        f"fact {fact.fact_id!r} references a missing segment"
                    )
                if evidence.end > len(segment_text):
                    raise ApprovedProfileError(
                        f"fact {fact.fact_id!r} offset exceeds segment length"
                    )
                if segment_text[evidence.start:evidence.end] != evidence.quote:
                    raise ApprovedProfileError(
                        f"fact {fact.fact_id!r} evidence does not match the source"
                    )
    if source_response is not None:
        response_document_ids = {
            str(document.get("document_id"))
            for document in source_response.get("documents", [])
            if isinstance(document, Mapping)
        }
        for document in profile.documents:
            if document.document_id not in response_document_ids:
                raise ApprovedProfileError(
                    f"profile references an unknown source document {document.document_id!r}"
                )


def _segment_text(
    source_response: Mapping[str, Any], document_id: str, segment_index: int
) -> str | None:
    for document in source_response.get("documents", []):
        if not isinstance(document, Mapping):
            continue
        if str(document.get("document_id")) != document_id:
            continue
        segments = document.get("segments")
        if not isinstance(segments, Sequence) or isinstance(segments, (str, bytes)):
            return None
        if segment_index < 0 or segment_index >= len(segments):
            return None
        segment = segments[segment_index]
        if not isinstance(segment, Mapping):
            return None
        text = segment.get("text")
        if not isinstance(text, str):
            return None
        return text
    return None


def build_approved_profile(
    envelope: ProfileEnvelope,
    review_state: ReviewState,
    *,
    candidate_contact: CandidateContact | None = None,
    source_response: Mapping[str, Any] | None = None,
) -> ApprovedProfile:
    """Build an approved profile from explicitly approved proposals."""
    approved = review_state.approved()
    facts: list[ApprovedFact] = []
    for proposal in approved:
        facts.append(
            ApprovedFact(
                fact_id=proposal.proposal_id,
                category=proposal.category,
                value=dict(proposal.value),
                evidence=tuple(proposal.evidence),
                source_document_ids=tuple(
                    sorted({reference.document_id for reference in proposal.evidence})
                ),
                review_sequence=review_state.sequence,
            )
        )
    profile = ApprovedProfile(
        approved_profile_version=APPROVED_PROFILE_VERSION,
        parser_schema_version=envelope.parser_schema_version,
        profile_schema_version=envelope.profile_schema_version,
        job_id=envelope.job_id,
        documents=tuple(envelope.documents),
        facts=tuple(facts),
        candidate=candidate_contact or CandidateContact(),
        review_sequence=review_state.sequence,
        review_history=tuple(event.as_dict() for event in review_state.history),
        warnings=tuple(envelope.warnings),
    )
    validate_approved_profile(profile, source_response)
    return profile


def export_approved_profile(profile: ApprovedProfile) -> str:
    """Serialise an approved profile to private local JSON."""
    return json.dumps(profile.as_dict(), indent=2, ensure_ascii=False)


def import_approved_profile(
    payload: Any,
    *,
    source_response: Mapping[str, Any] | None = None,
) -> ApprovedProfile:
    """Parse and validate an approved profile from JSON or a mapping."""
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ApprovedProfileError("invalid JSON") from exc
    elif isinstance(payload, (bytes, bytearray)):
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApprovedProfileError("invalid JSON") from exc
    else:
        data = payload
    profile = ApprovedProfile.from_dict(data)
    validate_approved_profile(profile, source_response)
    return profile


__all__ = [
    "APPROVED_PROFILE_VERSION",
    "ApprovedFact",
    "ApprovedProfile",
    "ApprovedProfileError",
    "CandidateContact",
    "build_approved_profile",
    "export_approved_profile",
    "import_approved_profile",
    "validate_approved_profile",
]
