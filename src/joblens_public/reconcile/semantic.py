"""The extension point for a future local semantic reasoner.

The deterministic engine works on its own. This module defines the seam where
an optional local model could be plugged in later, and the rules that keep
such a model honest:

* a model only sees the pairs the deterministic comparators could not
  relate, and only when an explicit reasoner is provided;
* a model conclusion is accepted only when it cites quotations that exist in
  the evidence of the two claims;
* an accepted conclusion is a recommendation that needs a user confirmation.
  It never consolidates and never approves.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .comparators import Comparison
from .models import Claim, Relation

__all__ = [
    "DeterministicReasoner",
    "SemanticJudgement",
    "SemanticReasoner",
    "validate_judgement",
]


@dataclass(frozen=True)
class SemanticJudgement:
    """A judgement proposed by a reasoner about two claims."""

    left_claim_id: str
    right_claim_id: str
    relation: str
    attributes: tuple[str, ...] = ()
    reason: str = ""
    quotes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "left_claim_id": self.left_claim_id,
            "right_claim_id": self.right_claim_id,
            "relation": self.relation,
            "attributes": list(self.attributes),
            "reason": self.reason,
            "quotes": list(self.quotes),
        }


@runtime_checkable
class SemanticReasoner(Protocol):
    """The interface a local reasoner has to implement."""

    def compare(self, left: Claim, right: Claim) -> SemanticJudgement | None:
        """Return a judgement about two claims, or ``None``."""


class DeterministicReasoner:
    """The default reasoner: it never proposes anything."""

    def compare(self, left: Claim, right: Claim) -> SemanticJudgement | None:
        return None


def validate_judgement(
    judgement: SemanticJudgement,
    left: Claim,
    right: Claim,
) -> Comparison | None:
    """Accept a judgement only when the evidence supports it.

    Returns ``None`` when the judgement is rejected, so the caller can fall
    back to the deterministic result.
    """
    if judgement.left_claim_id != left.claim_id:
        return None
    if judgement.right_claim_id != right.claim_id:
        return None
    try:
        relation = Relation(judgement.relation)
    except ValueError:
        return None
    allowed = {reference.quote for reference in left.evidence}
    allowed |= {reference.quote for reference in right.evidence}
    for quote in judgement.quotes:
        if quote not in allowed:
            return None
    if relation in {Relation.DUPLICATE, Relation.EQUIVALENT}:
        # A model may not merge claims on its own.
        return None
    return Comparison(
        relation,
        judgement.attributes,
        judgement.reason or "a local reasoner related the two claims",
        "semantic",
    )
