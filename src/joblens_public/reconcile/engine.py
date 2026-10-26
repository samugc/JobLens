"""The reconciliation engine.

The engine reads the same source documents as the profile layer, extracts the
typed claims they state, relates the claims with the comparator framework and
applies the resolution policy. The result is a versioned report that is
additive: it does not change the profile envelope, parser schema 1.1 or
transport 1.0.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .claims import _Document, _Segment, extract_claims
from .comparators import compare_claims
from .models import (
    PARSER_SCHEMA_VERSION,
    PROFILE_SCHEMA_VERSION,
    RECONCILIATION_SCHEMA_VERSION,
    Claim,
    ClaimCategory,
    DocumentReference,
    ReconciliationError,
    ReconciliationReport,
    Relation,
    Relationship,
)
from .policy import resolve
from .semantic import DeterministicReasoner, SemanticReasoner, validate_judgement

__all__ = ["reconcile_documents"]

#: Document statuses whose text may be quoted as evidence.
USABLE_DOCUMENT_STATUSES = frozenset({"extracted", "partial"})


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReconciliationError(f"{label} must be an object")
    return value


def _parse_documents(response: Mapping[str, Any]) -> list[_Document]:
    """Validate the parser response and return its documents."""
    schema_version = response.get("schema_version")
    if schema_version != PARSER_SCHEMA_VERSION:
        raise ReconciliationError(
            f"unsupported parser schema {schema_version!r}; "
            f"expected {PARSER_SCHEMA_VERSION!r}"
        )
    raw_documents = response.get("documents")
    if not isinstance(raw_documents, list):
        raise ReconciliationError("documents must be an array")
    if len(raw_documents) > 5:
        raise ReconciliationError("at most 5 documents are supported")

    documents: list[_Document] = []
    for position, raw_document in enumerate(raw_documents):
        document = _require_mapping(raw_document, f"documents[{position}]")
        document_id = document.get("document_id")
        if not isinstance(document_id, str) or not document_id.strip():
            raise ReconciliationError(
                f"documents[{position}] has no document_id; provenance is never invented"
            )
        raw_segments = document.get("segments")
        if not isinstance(raw_segments, list):
            raise ReconciliationError(f"documents[{position}].segments must be an array")
        segments: list[_Segment] = []
        for segment_index, raw_segment in enumerate(raw_segments):
            segment = _require_mapping(
                raw_segment, f"documents[{position}].segments[{segment_index}]"
            )
            text = segment.get("text")
            if not isinstance(text, str):
                raise ReconciliationError(
                    f"documents[{position}].segments[{segment_index}].text must be a string"
                )
            locator = segment.get("locator")
            if not isinstance(locator, Mapping):
                raise ReconciliationError(
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
            )
        )
    return documents


def _relationship_id(left: str, right: str, relation: Relation) -> str:
    parts = sorted((left, right))
    digest = hashlib.sha256(
        f"{parts[0]}|{parts[1]}|{relation.value}".encode("utf-8")
    ).hexdigest()
    return f"rel_{digest[:16]}"


def _build_relationships(
    claims: Sequence[Claim],
    reasoner: SemanticReasoner,
) -> list[Relationship]:
    relationships: list[Relationship] = []
    for index, left in enumerate(claims):
        for right in claims[index + 1:]:
            comparison = compare_claims(left, right)
            semantic = False
            if comparison.relation is Relation.UNCERTAIN:
                judgement = reasoner.compare(left, right)
                if judgement is not None:
                    validated = validate_judgement(judgement, left, right)
                    if validated is not None:
                        comparison = validated
                        semantic = True
            if comparison.relation is Relation.UNRELATED:
                continue
            relationships.append(
                Relationship(
                    relationship_id=_relationship_id(
                        left.claim_id, right.claim_id, comparison.relation
                    ),
                    relation=comparison.relation,
                    left_claim_id=left.claim_id,
                    right_claim_id=right.claim_id,
                    attributes=comparison.attributes,
                    reason=comparison.reason,
                    basis=comparison.basis,
                    evidence=tuple(left.evidence) + tuple(right.evidence),
                    semantic=semantic,
                )
            )
    return relationships


def _internal_inconsistencies(claims: Sequence[Claim]) -> list[str]:
    """Report the claims that contradict themselves.

    A claim that states a duration and a period which cannot both be true is
    inconsistent. The report says so; it never repairs the claim.
    """
    notes: list[str] = []
    for claim in claims:
        if claim.category is not ClaimCategory.EMPLOYMENT:
            continue
        stated = claim.attribute("duration_months")
        start = claim.attribute("start")
        end = claim.attribute("end")
        if stated is None or not start or not end:
            continue
        start_year = _year(start)
        end_year = _year(end)
        if start_year is None or end_year is None:
            continue
        span = max(0, (end_year - start_year) * 12)
        if abs(int(float(stated)) - span) >= 12:
            notes.append(
                f"Claim {claim.claim_id} states a duration that does not match its "
                "own period."
            )
    return notes


def _year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"(?:19|20)\d{2}", value)
    return int(match.group(0)) if match else None


def reconcile_documents(
    response: Mapping[str, Any],
    *,
    reasoner: SemanticReasoner | None = None,
) -> ReconciliationReport:
    """Reconcile the professional claims stated by the given documents.

    The function is pure and deterministic. A reasoner is optional and is
    only consulted for the pairs the deterministic comparators could not
    relate; a judgement it returns is validated against the evidence and can
    only produce a recommendation.
    """
    payload = _require_mapping(response, "response")
    documents = _parse_documents(payload)
    job_id = payload.get("job_id")
    warnings: list[str] = []

    claims = extract_claims(documents)
    relationships = _build_relationships(claims, reasoner or DeterministicReasoner())
    outcome = resolve(claims, relationships)

    references = tuple(
        DocumentReference(
            document_id=document.document_id,
            index=document.index,
            filename=document.filename,
            status=document.status,
            format=document.format,
            segment_count=len(document.segments),
            text_length=sum(len(segment.text) for segment in document.segments),
        )
        for document in documents
    )
    for document in documents:
        if document.status not in USABLE_DOCUMENT_STATUSES:
            warnings.append(
                f"Document {document.index} was skipped because its status is "
                f"{document.status!r}."
            )
    warnings.extend(_internal_inconsistencies(claims))

    return ReconciliationReport(
        reconciliation_schema_version=RECONCILIATION_SCHEMA_VERSION,
        parser_schema_version=PARSER_SCHEMA_VERSION,
        profile_schema_version=PROFILE_SCHEMA_VERSION,
        job_id=job_id if isinstance(job_id, str) else None,
        documents=references,
        claims=tuple(claims),
        relationships=tuple(relationships),
        decisions=outcome.decisions,
        consolidated=outcome.consolidated,
        warnings=tuple(warnings),
    )
