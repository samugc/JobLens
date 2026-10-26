"""Pure, in-memory review of candidate fact proposals.

The reducer is not a database. It holds the proposals of one analysis and the
history of the decisions taken on them, and it returns a new state for every
action. Nothing is written to disk and nothing is decided automatically: an
approval always comes from an explicit user action.

Rules enforced here:

* ``approve`` and ``reject`` require an explicit action.
* ``edit`` creates a revised proposal in the ``proposed`` state.
* Editing a proposal revokes its approval: the edited proposal becomes
  ``superseded`` and the revision starts again as ``proposed``.
* A revision only keeps evidence that still supports the edited value. An
  unsupported revision carries no evidence, and it can never be approved.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from .lexicon import DEGREE_SURFACE_FORMS
from .models import (
    Category,
    EvidenceReference,
    ProfileEnvelope,
    ProfileError,
    Proposal,
    ProposalStatus,
)

APPROVE = "approve"
REJECT = "reject"
EDIT = "edit"

_ACTIONS = (APPROVE, REJECT, EDIT)


@dataclass(frozen=True)
class ReviewAction:
    """One explicit review decision."""

    kind: str
    proposal_id: str
    value: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "proposal_id": self.proposal_id,
            "value": dict(self.value) if self.value is not None else None,
        }


@dataclass(frozen=True)
class ReviewEvent:
    """One entry of the review history."""

    sequence: int
    kind: str
    proposal_id: str
    revision_id: str | None = None
    supported: bool | None = None
    detail: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "kind": self.kind,
            "proposal_id": self.proposal_id,
            "revision_id": self.revision_id,
            "supported": self.supported,
            "detail": dict(self.detail) if self.detail is not None else None,
        }


@dataclass(frozen=True)
class ReviewState:
    """The proposals of one analysis plus the decisions taken on them."""

    proposals: tuple[Proposal, ...]
    history: tuple[ReviewEvent, ...] = ()
    sequence: int = 0

    def proposal(self, proposal_id: str) -> Proposal:
        for proposal in self.proposals:
            if proposal.proposal_id == proposal_id:
                return proposal
        raise ProfileError(f"unknown proposal {proposal_id!r}")

    def approved(self) -> tuple[Proposal, ...]:
        return tuple(
            proposal
            for proposal in self.proposals
            if proposal.status is ProposalStatus.APPROVED
        )

    def rejected(self) -> tuple[Proposal, ...]:
        return tuple(
            proposal
            for proposal in self.proposals
            if proposal.status is ProposalStatus.REJECTED
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "review_sequence": self.sequence,
            "proposals": [proposal.as_dict() for proposal in self.proposals],
            "history": [event.as_dict() for event in self.history],
        }


def initial_review_state(envelope: ProfileEnvelope) -> ReviewState:
    """Start a review session from a proposal envelope."""
    return ReviewState(proposals=tuple(envelope.proposals))


def _value_anchors(category: Category, value: Mapping[str, Any]) -> tuple[tuple[str, ...], bool]:
    """Return the text a quote must contain for an edited value to hold.

    The second element is ``True`` when any one of the alternatives is enough
    (used for degree levels, which have several spellings).
    """
    if category is Category.SKILL:
        return ((str(value.get("name", "")).casefold(),), False)
    if category is Category.LANGUAGE:
        anchors = [str(value.get("language", "")).casefold()]
        stated = value.get("stated_level")
        if stated:
            anchors.append(str(stated).casefold())
        return (tuple(anchors), False)
    if category is Category.EDUCATION:
        return ((str(value.get("field", "")).casefold(),), False)
    if category is Category.PROJECT:
        return ((str(value.get("name", "")).casefold(),), False)
    if category is Category.CERTIFICATION:
        return ((str(value.get("name", "")).casefold(),), False)
    if category is Category.EXPERIENCE:
        return ((str(value.get("role", "")).casefold(),), False)
    return ((), False)


def _is_supported(category: Category, value: Mapping[str, Any], quote: str) -> bool:
    haystack = quote.casefold()
    if category is Category.EDUCATION:
        field = str(value.get("field", "")).casefold()
        level = str(value.get("level", "")).casefold()
        if not field or field not in haystack:
            return False
        forms = DEGREE_SURFACE_FORMS.get(level, ())
        return any(form in haystack for form in forms)
    anchors, any_of = _value_anchors(category, value)
    if not anchors:
        return False
    if any_of:
        return any(anchor and anchor in haystack for anchor in anchors)
    return all(anchor and anchor in haystack for anchor in anchors)


def _supported_evidence(
    proposal: Proposal,
    value: Mapping[str, Any],
) -> tuple[bool, tuple[EvidenceReference, ...]]:
    """Keep only the evidence that still supports the edited value."""
    kept = tuple(
        reference
        for reference in proposal.evidence
        if _is_supported(proposal.category, value, reference.quote)
    )
    if not proposal.evidence:
        return False, ()
    return bool(kept), kept


def _revision_id(proposal: Proposal, sequence: int, value: Mapping[str, Any]) -> str:
    payload = "|".join(
        [
            proposal.proposal_id,
            str(sequence),
            proposal.category.value,
            repr(sorted((str(key), str(item)) for key, item in value.items())),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"prop_{digest[:16]}"


def _apply_approve(state: ReviewState, action: ReviewAction) -> ReviewState:
    proposal = state.proposal(action.proposal_id)
    if not proposal.evidence:
        raise ProfileError(
            "a proposal without evidence cannot be approved; it is not evidence-backed"
        )
    updated = replace(proposal, status=ProposalStatus.APPROVED)
    proposals = tuple(
        updated if item.proposal_id == proposal.proposal_id else item
        for item in state.proposals
    )
    event = ReviewEvent(
        sequence=state.sequence + 1,
        kind=APPROVE,
        proposal_id=proposal.proposal_id,
    )
    return ReviewState(
        proposals=proposals,
        history=state.history + (event,),
        sequence=state.sequence + 1,
    )


def _apply_reject(state: ReviewState, action: ReviewAction) -> ReviewState:
    proposal = state.proposal(action.proposal_id)
    updated = replace(proposal, status=ProposalStatus.REJECTED)
    proposals = tuple(
        updated if item.proposal_id == proposal.proposal_id else item
        for item in state.proposals
    )
    event = ReviewEvent(
        sequence=state.sequence + 1,
        kind=REJECT,
        proposal_id=proposal.proposal_id,
    )
    return ReviewState(
        proposals=proposals,
        history=state.history + (event,),
        sequence=state.sequence + 1,
    )


def _apply_edit(state: ReviewState, action: ReviewAction) -> ReviewState:
    proposal = state.proposal(action.proposal_id)
    if action.value is None:
        raise ProfileError("an edit requires a value")
    value = dict(action.value)
    if not value:
        raise ProfileError("an edit requires a non-empty value")

    supported, evidence = _supported_evidence(proposal, value)
    revision = Proposal(
        proposal_id=_revision_id(proposal, state.sequence + 1, value),
        category=proposal.category,
        value=value,
        status=ProposalStatus.PROPOSED,
        evidence=evidence,
        conflicts=(),
    )
    # Editing revokes the approval of the edited proposal.
    superseded = replace(proposal, status=ProposalStatus.SUPERSEDED)
    proposals = tuple(
        superseded if item.proposal_id == proposal.proposal_id else item
        for item in state.proposals
    ) + (revision,)
    event = ReviewEvent(
        sequence=state.sequence + 1,
        kind=EDIT,
        proposal_id=proposal.proposal_id,
        revision_id=revision.proposal_id,
        supported=supported,
        detail={"value": value},
    )
    return ReviewState(
        proposals=proposals,
        history=state.history + (event,),
        sequence=state.sequence + 1,
    )


def apply_review_action(state: ReviewState, action: ReviewAction) -> ReviewState:
    """Apply one explicit review action and return the new state.

    The function is pure: the input state is never modified.
    """
    if action.kind not in _ACTIONS:
        raise ProfileError(f"unknown review action {action.kind!r}")
    if not isinstance(action.proposal_id, str) or not action.proposal_id.strip():
        raise ProfileError("a review action needs a proposal id")
    if action.kind == APPROVE:
        return _apply_approve(state, action)
    if action.kind == REJECT:
        return _apply_reject(state, action)
    return _apply_edit(state, action)


def review_actions(proposals: Sequence[Proposal]) -> list[ReviewAction]:
    """List the actions a reviewer may take on a set of proposals."""
    return [
        ReviewAction(kind=kind, proposal_id=proposal.proposal_id)
        for proposal in proposals
        for kind in (APPROVE, REJECT)
    ]


__all__ = [
    "APPROVE",
    "EDIT",
    "REJECT",
    "ReviewAction",
    "ReviewEvent",
    "ReviewState",
    "apply_review_action",
    "initial_review_state",
    "review_actions",
]
