"""Deterministic mapping between claims and candidate profile proposals.

The profile engine and the reconciliation layer read the same source
documents and describe the same facts at a different granularity. This module
answers one narrow question: *given a claim in a reconciliation report, which
proposal of a profile envelope is about exactly the same source text?*

The mapping is read-only and deterministic. It never synchronises the two
artifacts, never merges proposals, never approves anything and never guesses a
correspondence:

* ``matched`` — exactly one proposal of a compatible category points at the
  same evidence and the normalised attributes that both sides state agree.
* ``ambiguous`` — several proposals share that evidence, or the evidence
  points at the same text while the normalised attributes disagree. A person
  has to look, so no correspondence is announced.
* ``unmapped`` — no proposal of a compatible category shares the evidence.

An evidence match is only accepted when the two quotations agree exactly:
identical spans must carry identical text, and a nested span must be the exact
slice of the containing quotation at its own offsets. The utility verifies
that from the quotations alone, so it needs no access to the source text.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from joblens_public.profile.models import (
    PROFILE_SCHEMA_VERSION,
    EvidenceReference,
    ProfileEnvelope,
    Proposal,
)

from .models import Claim, ClaimCategory
from .text import normalise

__all__ = [
    "AMBIGUOUS",
    "MATCHED",
    "UNMAPPED",
    "ClaimProposalMatch",
    "ReconciliationMapping",
    "map_claim_to_proposals",
    "map_claims_to_proposals",
    "proposal_categories_for",
]

#: Version of the mapping payload.
MAPPING_SCHEMA_VERSION = "0.1"

MATCHED = "matched"
AMBIGUOUS = "ambiguous"
UNMAPPED = "unmapped"

#: How the evidence span of a claim and of a proposal relate.
EXACT = "exact"
CLAIM_WITHIN_PROPOSAL = "claim_within_proposal"
PROPOSAL_WITHIN_CLAIM = "proposal_within_claim"

#: The proposal categories a claim category can correspond to. The tuple is
#: ordered and closed; an empty tuple means "no profile category".
CLAIM_TO_PROPOSAL: Mapping[ClaimCategory, tuple[str, ...]] = {
    ClaimCategory.SKILL: ("skill",),
    ClaimCategory.LANGUAGE: ("language",),
    ClaimCategory.EMPLOYMENT: ("experience",),
    ClaimCategory.EDUCATION: ("education",),
    ClaimCategory.DEGREE: ("education",),
    ClaimCategory.PROJECT: ("project",),
    ClaimCategory.CERTIFICATION: ("certification",),
    ClaimCategory.TECHNOLOGY: ("project",),
    ClaimCategory.CONTRIBUTION: ("project",),
    ClaimCategory.ACHIEVEMENT: ("project",),
    ClaimCategory.ORGANIZATION: (),
    ClaimCategory.INSTITUTION: (),
}

#: ``(claim attribute, proposal value key)`` pairs whose normalised values
#: must agree for a correspondence to be plausible.
_ATTRIBUTE_PAIRS: Mapping[
    tuple[ClaimCategory, str], tuple[tuple[str, str], ...]
] = {
    (ClaimCategory.SKILL, "skill"): (("name", "name"),),
    (ClaimCategory.LANGUAGE, "language"): (
        ("name", "language"),
        ("proficiency", "stated_level"),
    ),
    (ClaimCategory.EMPLOYMENT, "experience"): (("role", "role"),),
    (ClaimCategory.EDUCATION, "education"): (("level", "level"), ("field", "field")),
    (ClaimCategory.DEGREE, "education"): (("level", "level"), ("field", "field")),
    (ClaimCategory.PROJECT, "project"): (("name", "name"),),
    (ClaimCategory.CERTIFICATION, "certification"): (("name", "name"),),
    (ClaimCategory.TECHNOLOGY, "project"): (("project", "name"),),
    (ClaimCategory.CONTRIBUTION, "project"): (("project", "name"),),
    (ClaimCategory.ACHIEVEMENT, "project"): (("project", "name"),),
}


def proposal_categories_for(category: ClaimCategory) -> tuple[str, ...]:
    """Return the proposal categories a claim category may map to."""
    return CLAIM_TO_PROPOSAL.get(category, ())


@dataclass(frozen=True)
class ClaimProposalMatch:
    """The outcome of mapping one claim to the profile proposals."""

    claim_id: str
    claim_category: str
    outcome: str
    proposal_id: str | None = None
    proposal_category: str | None = None
    span_relation: str | None = None
    compatible_attributes: tuple[str, ...] = ()
    conflicting_attributes: tuple[str, ...] = ()
    candidate_proposal_ids: tuple[str, ...] = ()
    claim_support: str | None = None
    proposal_support: str | None = None
    reason: str = ""

    @property
    def matched(self) -> bool:
        return self.outcome == MATCHED

    def as_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "claim_category": self.claim_category,
            "outcome": self.outcome,
            "proposal_id": self.proposal_id,
            "proposal_category": self.proposal_category,
            "span_relation": self.span_relation,
            "compatible_attributes": list(self.compatible_attributes),
            "conflicting_attributes": list(self.conflicting_attributes),
            "candidate_proposal_ids": list(self.candidate_proposal_ids),
            "claim_support": self.claim_support,
            "proposal_support": self.proposal_support,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ReconciliationMapping:
    """The deterministic mapping of one reconciliation report."""

    reconciliation_schema_version: str
    profile_schema_version: str
    matches: tuple[ClaimProposalMatch, ...]
    mapping_schema_version: str = MAPPING_SCHEMA_VERSION

    def for_claim(self, claim_id: str) -> ClaimProposalMatch:
        for match in self.matches:
            if match.claim_id == claim_id:
                return match
        raise KeyError(claim_id)

    def for_proposal(self, proposal_id: str) -> tuple[str, ...]:
        """The claim ids that are matched to a proposal, in report order."""
        return tuple(
            match.claim_id
            for match in self.matches
            if match.matched and match.proposal_id == proposal_id
        )

    def by_outcome(self, outcome: str) -> tuple[ClaimProposalMatch, ...]:
        return tuple(match for match in self.matches if match.outcome == outcome)

    def counts(self) -> dict[str, int]:
        return {
            outcome: len(self.by_outcome(outcome))
            for outcome in (MATCHED, AMBIGUOUS, UNMAPPED)
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "mapping_schema_version": self.mapping_schema_version,
            "reconciliation_schema_version": self.reconciliation_schema_version,
            "profile_schema_version": self.profile_schema_version,
            "counts": self.counts(),
            "matches": [match.as_dict() for match in self.matches],
        }


@dataclass(frozen=True)
class _Candidate:
    proposal: Proposal
    relation: str
    compatible: tuple[str, ...]
    conflicting: tuple[str, ...]
    claim_support: str
    proposal_support: str


def _contains(outer: EvidenceReference, inner: EvidenceReference) -> bool:
    """True when the inner quotation is the exact slice of the outer one."""
    offset = inner.start - outer.start
    if offset < 0:
        return False
    return outer.quote[offset:offset + len(inner.quote)] == inner.quote


def _span_relation(
    claim: Claim, proposal: Proposal
) -> tuple[str, EvidenceReference, EvidenceReference] | None:
    for claim_reference in claim.evidence:
        for proposal_reference in proposal.evidence:
            if claim_reference.document_id != proposal_reference.document_id:
                continue
            if claim_reference.segment_index != proposal_reference.segment_index:
                continue
            if (
                claim_reference.start == proposal_reference.start
                and claim_reference.end == proposal_reference.end
            ):
                if claim_reference.quote == proposal_reference.quote:
                    return (EXACT, claim_reference, proposal_reference)
                continue
            if (
                claim_reference.start <= proposal_reference.start
                and proposal_reference.end <= claim_reference.end
                and _contains(claim_reference, proposal_reference)
            ):
                return (PROPOSAL_WITHIN_CLAIM, claim_reference, proposal_reference)
            if (
                proposal_reference.start <= claim_reference.start
                and claim_reference.end <= proposal_reference.end
                and _contains(proposal_reference, claim_reference)
            ):
                return (CLAIM_WITHIN_PROPOSAL, claim_reference, proposal_reference)
    return None


def _compare_attributes(
    claim_values: Mapping[str, Any],
    proposal_values: Mapping[str, Any],
    pairs: Sequence[tuple[str, str]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    compatible: list[str] = []
    conflicting: list[str] = []
    for claim_name, proposal_name in pairs:
        claim_value = claim_values.get(claim_name)
        proposal_value = proposal_values.get(proposal_name)
        if claim_value is None or proposal_value is None:
            continue
        if normalise(str(claim_value)) == normalise(str(proposal_value)):
            compatible.append(claim_name)
        else:
            conflicting.append(claim_name)
    return tuple(compatible), tuple(conflicting)


def _candidates(claim: Claim, proposals: Sequence[Proposal]) -> list[_Candidate]:
    wanted = proposal_categories_for(claim.category)
    if not wanted:
        return []
    claim_values = {item.name: item.value for item in claim.attributes}
    candidates: list[_Candidate] = []
    for proposal in proposals:
        category = proposal.category.value
        if category not in wanted:
            continue
        span = _span_relation(claim, proposal)
        if span is None:
            continue
        pairs = _ATTRIBUTE_PAIRS.get((claim.category, category), ())
        compatible, conflicting = _compare_attributes(
            claim_values, dict(proposal.value), pairs
        )
        candidates.append(
            _Candidate(
                proposal=proposal,
                relation=span[0],
                compatible=compatible,
                conflicting=conflicting,
                claim_support=span[1].support.value,
                proposal_support=span[2].support.value,
            )
        )
    return candidates


def map_claim_to_proposals(
    claim: Claim,
    proposals: Sequence[Proposal],
) -> ClaimProposalMatch:
    """Map one claim to the proposals that share exactly its source text."""
    candidates = _candidates(claim, proposals)
    if not candidates:
        if not proposal_categories_for(claim.category):
            reason = (
                f"no profile proposal category corresponds to a "
                f"{claim.category.value} claim"
            )
        else:
            reason = (
                "no proposal of a compatible category shares the exact evidence "
                "of the claim"
            )
        return ClaimProposalMatch(
            claim_id=claim.claim_id,
            claim_category=claim.category.value,
            outcome=UNMAPPED,
            reason=reason,
        )

    candidate_ids = tuple(sorted(candidate.proposal.proposal_id for candidate in candidates))
    compatible = [candidate for candidate in candidates if not candidate.conflicting]
    if len(compatible) == 1:
        chosen = compatible[0]
        return ClaimProposalMatch(
            claim_id=claim.claim_id,
            claim_category=claim.category.value,
            outcome=MATCHED,
            proposal_id=chosen.proposal.proposal_id,
            proposal_category=chosen.proposal.category.value,
            span_relation=chosen.relation,
            compatible_attributes=chosen.compatible,
            conflicting_attributes=(),
            candidate_proposal_ids=candidate_ids,
            claim_support=chosen.claim_support,
            proposal_support=chosen.proposal_support,
            reason=(
                "one proposal of a compatible category shares the exact evidence "
                "and the stated attributes agree"
            ),
        )

    conflicting = tuple(
        sorted({name for candidate in candidates for name in candidate.conflicting})
    )
    if len(compatible) > 1:
        reason = (
            "several proposals of a compatible category share the exact evidence, "
            "so no correspondence is chosen"
        )
    else:
        reason = (
            "the proposals that share the exact evidence state different "
            "normalised attributes, so no correspondence is chosen"
        )
    return ClaimProposalMatch(
        claim_id=claim.claim_id,
        claim_category=claim.category.value,
        outcome=AMBIGUOUS,
        candidate_proposal_ids=candidate_ids,
        compatible_attributes=tuple(
            sorted(set.intersection(*(set(c.compatible) for c in candidates)))
        ),
        conflicting_attributes=conflicting,
        reason=reason,
    )


def map_claims_to_proposals(
    report: Any,
    proposals: ProfileEnvelope | Sequence[Proposal],
) -> ReconciliationMapping:
    """Map every claim of a reconciliation report to the profile proposals.

    ``proposals`` is a :class:`~joblens_public.profile.models.ProfileEnvelope`
    or a plain sequence of proposals. The result is deterministic and
    read-only: neither artifact is changed.
    """
    if isinstance(proposals, ProfileEnvelope):
        sequence: Sequence[Proposal] = proposals.proposals
        profile_version = proposals.profile_schema_version
    else:
        sequence = tuple(proposals)
        profile_version = PROFILE_SCHEMA_VERSION
    matches = tuple(
        map_claim_to_proposals(claim, sequence) for claim in report.claims
    )
    return ReconciliationMapping(
        reconciliation_schema_version=report.reconciliation_schema_version,
        profile_schema_version=profile_version,
        matches=matches,
    )
