"""The resolution policy.

Three outcomes are possible, and only three:

* ``AUTO_CONSOLIDATE`` for safe equivalences. The claims are merged into one
  consolidated claim and every source is preserved.
* ``RECOMMEND`` when a defensible preference exists. The preference is
  advisory and always asks for a user confirmation; the claims it does not
  choose are kept as alternatives, never discarded.
* ``UNRESOLVED`` when the evidence is inadequate or contradictory.

The policy never assumes that the highest number, the newest upload, the most
favourable statement or the most impressive title is true. Preferences come
from dates that the sources state, or from the amount of information a claim
carries, and never from the order of the documents.

A recommendation is only made when nothing in the group is in doubt: a
contradictory relation or an unresolved identity blocks it, so a group that
mixes a preference with a contradiction stays unresolved.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from .models import (
    Claim,
    ClaimAttribute,
    ClaimCategory,
    ConsolidatedClaim,
    Relation,
    Relationship,
    Resolution,
    ResolutionDecision,
)

__all__ = ["PolicyOutcome", "resolve"]

_CEFR = ("a1", "a2", "b1", "b2", "c1", "c2")
_SAFE_RELATIONS = (Relation.DUPLICATE, Relation.EQUIVALENT)
#: A hard contradiction or an unresolved identity blocks a recommendation: a
#: preference is only defensible when nothing in the group is in doubt.
_BLOCKING_RELATIONS = (Relation.CONTRADICTORY, Relation.UNCERTAIN)
_PREFERENCE_RELATIONS = (
    Relation.TEMPORAL_UPDATE,
    Relation.MORE_SPECIFIC,
    Relation.LESS_SPECIFIC,
)
_YEAR = re.compile(r"(?:19|20)\d{2}")

#: An end date that means "still current" ranks above every stated year.
_CURRENT_END = 9999
#: An end date that is not stated at all ranks with the start date.
_UNSTATED = -1


@dataclass(frozen=True)
class PolicyOutcome:
    """The decisions and the consolidated claims of one reconciliation."""

    decisions: tuple[ResolutionDecision, ...]
    consolidated: tuple[ConsolidatedClaim, ...]


def _decision_id(category: ClaimCategory, subject: str, outcome: Resolution) -> str:
    import hashlib

    digest = hashlib.sha256(
        f"{category.value}|{subject}|{outcome.value}".encode("utf-8")
    ).hexdigest()
    return f"dec_{digest[:16]}"


def _year(value: str | None) -> int | None:
    if not value:
        return None
    match = _YEAR.search(value)
    return int(match.group(0)) if match else None


def _period_order(claim: Claim) -> tuple[int, int]:
    """Order a claim by the period it states, current first.

    An end date written as ``present`` outranks every stated year, so a
    position that is still held is the more recent statement. An end date the
    source does not state is not current: it ranks with the start date.
    """
    start = _year(claim.attribute("start"))
    end_value = claim.attribute("end")
    if end_value == "present":
        end = _CURRENT_END
    else:
        end = _year(end_value)
    if end is None:
        end = start if start is not None else _UNSTATED
    if start is None:
        start = _UNSTATED
    return (end, start)


def _inside_relations(
    relationships: Sequence[Relationship],
    claim_ids: Sequence[str],
) -> list[Relationship]:
    wanted = set(claim_ids)
    return [
        relationship
        for relationship in relationships
        if relationship.left_claim_id in wanted and relationship.right_claim_id in wanted
    ]


def _preferred_temporal(
    left: Claim,
    right: Claim,
) -> Claim:
    """Prefer the claim whose stated period is later."""
    return right if _period_order(right) > _period_order(left) else left


def _preferred_specific(left: Claim, right: Claim) -> Claim:
    """Prefer the claim that carries more information."""
    return right if len(right.attributes) > len(left.attributes) else left


def _language_preference(group: Sequence[Claim]) -> Claim | None:
    """Prefer a comparable CEFR level, or the claim that states a date."""
    levels = {claim.claim_id: (claim.attribute("proficiency") or "") for claim in group}
    if not levels or not all(level in _CEFR for level in levels.values()):
        return None
    dated = [claim for claim in group if claim.attribute("date")]
    if len(dated) == 1:
        return dated[0]
    if dated:
        return max(dated, key=lambda claim: claim.attribute("date") or "")
    return max(group, key=lambda claim: _CEFR.index(levels[claim.claim_id]))


def _consolidate(group: Sequence[Claim]) -> ConsolidatedClaim:
    """Merge equivalent claims, keeping every source and every attribute."""
    attributes: dict[str, ClaimAttribute] = {}
    for claim in group:
        for item in claim.attributes:
            attributes.setdefault(item.name, item)
    evidence = tuple(
        reference
        for claim in group
        for reference in claim.evidence
    )
    return ConsolidatedClaim(
        subject=group[0].subject,
        category=group[0].category,
        subject_label=group[0].subject_label,
        attributes=tuple(attributes.values()),
        claim_ids=tuple(claim.claim_id for claim in group),
        evidence=evidence,
        qualifiers=tuple(sorted({claim.qualifier for claim in group})),
    )


def _unresolved_explanation(relations: set[Relation]) -> str:
    """A fixed explanation that names the kind of doubt, not a verdict."""
    parts: list[str] = []
    if Relation.CONTRADICTORY in relations:
        parts.append("some sources state facts that cannot both be true")
    if Relation.POTENTIALLY_CONFLICTING in relations:
        parts.append("some sources differ in a way that may be legitimate")
    if Relation.UNCERTAIN in relations:
        parts.append("the identity of the entity is not established")
    detail = "; ".join(parts) if parts else "the evidence is not conclusive"
    return (
        f"{detail[0].upper()}{detail[1:]}, so no claim is preferred and every "
        "source is kept for a reviewer to decide."
    )


def resolve(
    claims: Sequence[Claim],
    relationships: Sequence[Relationship],
) -> PolicyOutcome:
    """Turn the relationships into decisions and consolidated claims."""
    groups: dict[tuple[str, str], list[Claim]] = {}
    for claim in claims:
        groups.setdefault((claim.category.value, claim.subject), []).append(claim)

    decisions: list[ResolutionDecision] = []
    consolidated: list[ConsolidatedClaim] = []

    for (category_value, subject), group in sorted(groups.items()):
        if len(group) < 2:
            continue
        category = ClaimCategory(category_value)
        inside = _inside_relations(relationships, [claim.claim_id for claim in group])
        relations = {relationship.relation for relationship in inside}
        claim_ids = [claim.claim_id for claim in group]
        relationship_ids = tuple(sorted(relationship.relationship_id for relationship in inside))

        if relations and relations <= set(_SAFE_RELATIONS):
            consolidated.append(_consolidate(group))
            decisions.append(
                ResolutionDecision(
                    decision_id=_decision_id(category, subject, Resolution.AUTO_CONSOLIDATE),
                    outcome=Resolution.AUTO_CONSOLIDATE,
                    category=category,
                    subject=subject,
                    subject_label=group[0].subject_label,
                    merge_claim_ids=tuple(claim_ids),
                    relationship_ids=relationship_ids,
                    explanation=(
                        "The sources state the same fact, so the claims are merged into "
                        "one and every source is kept; nothing is approved."
                    ),
                    requires_user_confirmation=False,
                )
            )
            continue

        blocked = bool(relations & set(_BLOCKING_RELATIONS))
        if not blocked and relations & set(_PREFERENCE_RELATIONS):
            preferred: Claim | None = None
            reason = ""
            if Relation.TEMPORAL_UPDATE in relations:
                pair = next(
                    relationship
                    for relationship in inside
                    if relationship.relation is Relation.TEMPORAL_UPDATE
                )
                left = next(claim for claim in group if claim.claim_id == pair.left_claim_id)
                right = next(claim for claim in group if claim.claim_id == pair.right_claim_id)
                preferred = _preferred_temporal(left, right)
                reason = (
                    "The later period is the more recent statement of the same fact, "
                    "so it is recommended and every other claim is kept."
                )
            elif category is ClaimCategory.LANGUAGE:
                preferred = _language_preference(group)
                reason = (
                    "The levels are comparable, so the higher declared level is "
                    "recommended, but no chronology is available; every other claim "
                    "is kept."
                )
            else:
                pair = next(
                    relationship
                    for relationship in inside
                    if relationship.relation
                    in (Relation.MORE_SPECIFIC, Relation.LESS_SPECIFIC)
                )
                left = next(claim for claim in group if claim.claim_id == pair.left_claim_id)
                right = next(claim for claim in group if claim.claim_id == pair.right_claim_id)
                preferred = _preferred_specific(left, right)
                reason = (
                    "One source states more about the same fact than the other, so it "
                    "is recommended and every other claim is kept."
                )
            if preferred is not None:
                decisions.append(
                    ResolutionDecision(
                        decision_id=_decision_id(category, subject, Resolution.RECOMMEND),
                        outcome=Resolution.RECOMMEND,
                        category=category,
                        subject=subject,
                        subject_label=preferred.subject_label,
                        keep_claim_ids=(preferred.claim_id,),
                        alternative_claim_ids=tuple(
                            claim_id for claim_id in claim_ids if claim_id != preferred.claim_id
                        ),
                        relationship_ids=relationship_ids,
                        explanation=reason,
                        requires_user_confirmation=True,
                    )
                )
                continue

        if (
            not blocked
            and category is ClaimCategory.LANGUAGE
            and Relation.POTENTIALLY_CONFLICTING in relations
        ):
            preferred = _language_preference(group)
            if preferred is not None:
                decisions.append(
                    ResolutionDecision(
                        decision_id=_decision_id(category, subject, Resolution.RECOMMEND),
                        outcome=Resolution.RECOMMEND,
                        category=category,
                        subject=subject,
                        subject_label=preferred.subject_label,
                        keep_claim_ids=(preferred.claim_id,),
                        alternative_claim_ids=tuple(
                            claim_id for claim_id in claim_ids if claim_id != preferred.claim_id
                        ),
                        relationship_ids=relationship_ids,
                        explanation=(
                            "The levels are comparable, so one of them is recommended, but "
                            "the reviewer has to confirm it; every other claim is kept."
                        ),
                        requires_user_confirmation=True,
                    )
                )
                continue

        if relations & {
            Relation.CONTRADICTORY,
            Relation.POTENTIALLY_CONFLICTING,
            Relation.UNCERTAIN,
        }:
            decisions.append(
                ResolutionDecision(
                    decision_id=_decision_id(category, subject, Resolution.UNRESOLVED),
                    outcome=Resolution.UNRESOLVED,
                    category=category,
                    subject=subject,
                    subject_label=group[0].subject_label,
                    alternative_claim_ids=tuple(claim_ids),
                    relationship_ids=relationship_ids,
                    explanation=_unresolved_explanation(relations),
                    requires_user_confirmation=True,
                )
            )

    return PolicyOutcome(
        decisions=tuple(decisions),
        consolidated=tuple(consolidated),
    )
