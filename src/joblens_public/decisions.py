"""Deterministic explanations for CV drafting decisions.

The report is derived from the same trace that drives the generator: it never
calls a model and it never guesses why something happened. It only translates
an actual decision into a short, human-readable statement:

* an included fact and the job requirement it supports;
* an omitted fact and the concrete reason it was left out;
* a detail the sources contradicted, with every stated value and no automatic
  choice.

Technical identifiers are deliberately not part of the user-facing contract.
Each decision has a label, an explanation, the requirement text it supports and
the source document names. A response is additive and carries its own version,
so older clients can ignore it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from joblens_public.requirements import (
    COVERED,
    REQUIRED,
    TECHNOLOGY,
    UNCOVERED,
    RequirementAssessment,
    assess_requirements,
    is_gap,
)

#: Version of the decision-report contract.
DECISION_REPORT_VERSION = "0.1"

#: Stable internal reason vocabulary.
SELECTED_RELEVANT = "selected_relevant"
SELECTED_ESSENTIAL = "selected_essential"
EXCLUDED_CONFLICT = "excluded_conflict"
EXCLUDED_UNSUPPORTED = "excluded_unsupported"
EXCLUDED_REDUNDANT = "excluded_redundant"
EXCLUDED_LOWER_PRIORITY = "excluded_lower_priority"

REASONS = (
    SELECTED_RELEVANT,
    SELECTED_ESSENTIAL,
    EXCLUDED_CONFLICT,
    EXCLUDED_UNSUPPORTED,
    EXCLUDED_REDUNDANT,
    EXCLUDED_LOWER_PRIORITY,
)

#: Acronyms rendered in upper case in labels.
_ACRONYMS = frozenset(
    {"sql", "aws", "api", "ci", "cd", "ml", "ai", "nlp", "etl", "gcp", "gpu", "ui", "ux"}
)


def _display_word(word: str) -> str:
    lowered = word.casefold()
    if lowered == "javascript":
        return "JavaScript"
    if lowered == "typescript":
        return "TypeScript"
    if lowered in _ACRONYMS:
        return lowered.upper()
    return word[:1].upper() + word[1:] if word else word


def _display(value: str) -> str:
    return " ".join(_display_word(part) for part in value.split())


def _label(category: str, value: Mapping[str, Any]) -> str:
    if category == "skill":
        return _display(str(value.get("name", "")).strip())
    if category == "language":
        base = _display(str(value.get("language", "")).strip())
        level = value.get("stated_level")
        if not level:
            return base
        shown = "Native" if str(level).casefold() == "native" else str(level).upper()
        return f"{base} ({shown})"
    if category in ("certification", "project"):
        return _display(str(value.get("name", "")).strip())
    if category == "education":
        level = str(value.get("level", "")).strip()
        subject = str(value.get("field", "")).strip()
        if subject:
            return f"{_display(level)} in {_display(subject)}"
        return _display(level)
    if category == "experience":
        role = str(value.get("role", "")).strip()
        organisation = str(value.get("organization", "")).strip()
        if organisation:
            return f"{_display(role)} at {_display(organisation)}"
        return _display(role)
    return _display(str(value))


def _supports(
    fact_text: str, job: Any, aggregate_states: Mapping[str, str]
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return (essential, relevant, essential partial, relevant partial).

    The assessment is element-wise. A requirement is reported as fully
    supported only when the draft as a whole covers it *and* this content
    states at least one of its elements. When only part of the requirement is
    covered, the content is reported separately so it can never read as a
    claim that the requirement is satisfied.
    """
    assessments = assess_requirements(job, [fact_text])
    essential: list[str] = []
    relevant: list[str] = []
    essential_partial: list[str] = []
    relevant_partial: list[str] = []
    for assessment in assessments:
        if assessment.state == UNCOVERED:
            continue
        text = assessment.requirement.text
        importance = assessment.requirement.importance
        is_essential = importance in (REQUIRED, TECHNOLOGY)
        aggregate = aggregate_states.get(assessment.requirement.requirement_id)
        if aggregate == COVERED:
            target = essential if is_essential else relevant
        else:
            target = essential_partial if is_essential else relevant_partial
        if text not in target:
            target.append(text)
    return (
        tuple(essential),
        tuple(relevant),
        tuple(essential_partial),
        tuple(relevant_partial),
    )


@dataclass(frozen=True)
class Decision:
    """One explained inclusion, omission or unresolved detail."""

    decision_id: str
    outcome: str
    reason: str
    scope: str
    category: str | None
    label: str
    explanation: str
    supports: tuple[str, ...] = ()
    supports_partially: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()
    documents: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "outcome": self.outcome,
            "reason": self.reason,
            "scope": self.scope,
            "category": self.category,
            "label": self.label,
            "explanation": self.explanation,
            "supports": list(self.supports),
            "supports_partially": list(self.supports_partially),
            "alternatives": list(self.alternatives),
            "documents": list(self.documents),
        }


@dataclass(frozen=True)
class UnmetRequirement:
    """A job requirement that no approved fact supports in full."""

    requirement: str
    explanation: str
    state: str = UNCOVERED
    missing: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "requirement": self.requirement,
            "explanation": self.explanation,
            "state": self.state,
            "missing": list(self.missing),
        }


@dataclass(frozen=True)
class DecisionReport:
    """The versioned, deterministic decision report."""

    decision_report_version: str = DECISION_REPORT_VERSION
    decisions: tuple[Decision, ...] = ()
    unmet_requirements: tuple[UnmetRequirement, ...] = ()
    requirement_coverage: tuple[RequirementAssessment, ...] = ()
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        counts = {"included": 0, "omitted": 0, "insufficient": 0}
        for decision in self.decisions:
            if decision.outcome in counts:
                counts[decision.outcome] += 1
        return {
            "decision_report_version": self.decision_report_version,
            "counts": counts,
            "decisions": [decision.as_dict() for decision in self.decisions],
            "unmet_requirements": [
                requirement.as_dict() for requirement in self.unmet_requirements
            ],
            "requirement_coverage": [
                assessment.as_dict() for assessment in self.requirement_coverage
            ],
            "warnings": list(self.warnings),
        }


def trace_from_approved_profile(
    profile: Any,
    envelope: Any = None,
    *,
    documents: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Build the same trace shape the provisional path produces.

    ``profile`` is an :class:`ApprovedProfile`; ``envelope`` is the canonical
    proposal envelope, when available, so facts the candidate did not approve
    can be reported as omitted rather than silently disappearing.
    """
    documents = documents or {}
    trace: list[dict[str, Any]] = []
    approved_ids = {fact.fact_id for fact in profile.facts}
    for fact in profile.facts:
        trace.append(
            {
                "proposal_id": fact.fact_id,
                "category": fact.category.value,
                "value": dict(fact.value),
                "source_quotes": [item.quote for item in fact.evidence],
                "retained_quotes": [item.quote for item in fact.evidence],
                "reason": "retained",
                "fact_ids": [fact.fact_id],
                "document_labels": [
                    documents.get(document_id, document_id)
                    for document_id in sorted(
                        {item.document_id for item in fact.evidence}
                    )
                ],
            }
        )
    if envelope is not None:
        for proposal in envelope.proposals:
            if proposal.proposal_id in approved_ids:
                continue
            trace.append(
                {
                    "proposal_id": proposal.proposal_id,
                    "category": proposal.category.value,
                    "value": dict(proposal.value),
                    "source_quotes": [item.quote for item in proposal.evidence],
                    "retained_quotes": [],
                    "reason": (
                        "unresolved profile conflict"
                        if proposal.conflicts
                        else "not approved"
                    ),
                    "fact_ids": [],
                    "document_labels": [
                        documents.get(document_id, document_id)
                        for document_id in sorted(
                            {item.document_id for item in proposal.evidence}
                        )
                    ],
                }
            )
    return trace


def _omission_explanation(reason: str, label: str) -> tuple[str, str]:
    """Return (outcome, explanation) for an omission reason."""
    if reason == "unresolved profile conflict":
        return (
            "omitted",
            f"{label} was left out because the source documents disagree about it. "
            "No value is added without an explicit candidate choice.",
        )
    if reason == "no explicit skill claim":
        return (
            "omitted",
            f"{label} was left out because the source only mentioned it in passing; "
            "there was no explicit skill claim to support it.",
        )
    if reason == "all evidence overlaps unresolved contradictions":
        return (
            "omitted",
            f"{label} was left out because every quotation for it overlaps an "
            "unresolved contradiction in the sources.",
        )
    if reason == "not approved":
        return (
            "omitted",
            f"{label} was left out because the candidate did not approve it.",
        )
    return (
        "omitted",
        f"{label} was not selected for this draft.",
    )


def _reason_for_omission(reason: str) -> str:
    if reason in (
        "unresolved profile conflict",
        "all evidence overlaps unresolved contradictions",
    ):
        return EXCLUDED_CONFLICT
    if reason in ("no explicit skill claim", "not approved"):
        return EXCLUDED_UNSUPPORTED
    return EXCLUDED_LOWER_PRIORITY


def _included_explanation(
    label: str,
    essential: Sequence[str],
    relevant: Sequence[str],
    essential_partial: Sequence[str] = (),
    relevant_partial: Sequence[str] = (),
) -> tuple[str, str]:
    if essential:
        requirement = essential[0]
        return (
            SELECTED_ESSENTIAL,
            f"{label} was included because it supports the essential job "
            f"requirement “{requirement}”.",
        )
    if relevant:
        requirement = relevant[0]
        return (
            SELECTED_RELEVANT,
            f"{label} was included because it supports the job requirement "
            f"“{requirement}”.",
        )
    if essential_partial:
        requirement = essential_partial[0]
        return (
            SELECTED_ESSENTIAL,
            f"{label} was included because it contributes evidence to the essential "
            f"job requirement “{requirement}”, which is only partly covered. "
            "The draft does not claim the whole requirement is satisfied.",
        )
    if relevant_partial:
        requirement = relevant_partial[0]
        return (
            SELECTED_RELEVANT,
            f"{label} was included because it contributes evidence to the job "
            f"requirement “{requirement}”, which is only partly covered. "
            "The draft does not claim the whole requirement is satisfied.",
        )
    return (
        SELECTED_RELEVANT,
        f"{label} was included as approved professional content; no specific "
        "job requirement matched it.",
    )


def build_decision_report(
    *,
    job: Any,
    draft: Any,
    trace: Sequence[Mapping[str, Any]],
    conflicts: Sequence[Mapping[str, Any]] = (),
    documents: Mapping[str, str] | None = None,
    redundant_fact_ids: Sequence[str] = (),
) -> DecisionReport:
    """Translate an actual generation trace into a deterministic report."""
    documents = documents or {}
    coverage = tuple(getattr(draft, "requirement_coverage", ()) or ())
    aggregate_states = {
        assessment.requirement.requirement_id: assessment.state
        for assessment in coverage
    }
    included_ids = {
        fact_id
        for section in draft.sections
        for item in section.items
        for fact_id in item.approved_fact_ids
        if not fact_id.startswith("attestation:")
    }
    summary_ids: set[str] = set()
    for section in draft.sections:
        if section.kind == "summary":
            for item in section.items:
                summary_ids.update(item.approved_fact_ids)

    decisions: list[Decision] = []
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"decision_{counter:04d}"

    def document_labels(entry: Mapping[str, Any]) -> tuple[str, ...]:
        raw = entry.get("document_labels") or ()
        labels = []
        for item in raw:
            resolved = documents.get(str(item), str(item))
            if resolved not in labels:
                labels.append(resolved)
        return tuple(labels)

    # Index trace entries by every fact identifier they produced.
    by_fact_id: dict[str, Mapping[str, Any]] = {}
    for entry in trace:
        for fact_id in entry.get("fact_ids") or ():
            by_fact_id[str(fact_id)] = entry

    # Included facts, in the order the generator emitted them.
    included_entries: list[Mapping[str, Any]] = []
    seen_proposals: set[str] = set()
    for section in draft.sections:
        for item in section.items:
            for fact_id in item.approved_fact_ids:
                entry = by_fact_id.get(fact_id)
                if entry is None:
                    continue
                proposal_id = str(entry.get("proposal_id") or fact_id)
                if proposal_id in seen_proposals:
                    continue
                seen_proposals.add(proposal_id)
                included_entries.append(entry)

    for entry in included_entries:
        category = str(entry.get("category") or "")
        value = entry.get("value") or {}
        label = _label(category, value)
        quotes = " ".join(entry.get("retained_quotes") or entry.get("source_quotes") or ())
        essential, relevant, essential_partial, relevant_partial = _supports(
            f"{label} {quotes}", job, aggregate_states
        )
        reason, explanation = _included_explanation(
            label, essential, relevant, essential_partial, relevant_partial
        )
        decisions.append(
            Decision(
                decision_id=next_id(),
                outcome="included",
                reason=reason,
                scope="cv",
                category=category or None,
                label=label,
                explanation=explanation,
                supports=essential + relevant,
                supports_partially=essential_partial + relevant_partial,
                documents=document_labels(entry),
            )
        )

    # Summary-only decisions, derived from the actual summary citations.
    if summary_ids:
        summary_entries: list[Mapping[str, Any]] = []
        for fact_id in summary_ids:
            entry = by_fact_id.get(fact_id)
            if entry is not None and entry not in summary_entries:
                summary_entries.append(entry)
        summary_proposals = {
            str(entry.get("proposal_id") or "") for entry in summary_entries
        }
        for entry in summary_entries:
            category = str(entry.get("category") or "")
            value = entry.get("value") or {}
            label = _label(category, value)
            quotes = " ".join(
                entry.get("retained_quotes") or entry.get("source_quotes") or ()
            )
            essential, relevant, essential_partial, relevant_partial = _supports(
                f"{label} {quotes}", job, aggregate_states
            )
            reason, explanation = _included_explanation(
                label, essential, relevant, essential_partial, relevant_partial
            )
            decisions.append(
                Decision(
                    decision_id=next_id(),
                    outcome="included",
                    reason=reason,
                    scope="summary",
                    category=category or None,
                    label=label,
                    explanation="Used in the professional summary. " + explanation,
                    supports=essential + relevant,
                    supports_partially=essential_partial + relevant_partial,
                    documents=document_labels(entry),
                )
            )
        for entry in included_entries:
            proposal_id = str(entry.get("proposal_id") or "")
            category = str(entry.get("category") or "")
            if proposal_id in summary_proposals or category not in ("experience", "skill"):
                continue
            label = _label(category, entry.get("value") or {})
            decisions.append(
                Decision(
                    decision_id=next_id(),
                    outcome="omitted",
                    reason=EXCLUDED_LOWER_PRIORITY,
                    scope="summary",
                    category=category or None,
                    label=label,
                    explanation=(
                        f"{label} was not used in the professional summary because "
                        "other approved facts ranked higher for this job; it remains "
                        "in its full section."
                    ),
                    documents=document_labels(entry),
                )
            )

    # Omitted facts, from the actual exclusion reasons in the trace.
    omitted_proposals: set[str] = set()
    for entry in trace:
        fact_ids = tuple(str(item) for item in (entry.get("fact_ids") or ()))
        reason = str(entry.get("reason") or "")
        if reason == "retained" and any(f in included_ids for f in fact_ids):
            continue
        if reason == "retained":
            # A retained proposal whose facts did not reach the draft.
            reason = "not selected"
        proposal_id = str(entry.get("proposal_id") or "")
        if proposal_id in omitted_proposals:
            continue
        omitted_proposals.add(proposal_id)
        category = str(entry.get("category") or "")
        label = _label(category, entry.get("value") or {})
        outcome, explanation = _omission_explanation(reason, label)
        decisions.append(
            Decision(
                decision_id=next_id(),
                outcome=outcome,
                reason=_reason_for_omission(reason),
                scope="cv",
                category=category or None,
                label=label,
                explanation=explanation,
                documents=document_labels(entry),
            )
        )

    # Duplicates collapsed by the provisional engine, with their evidence merged.
    seen_redundant: set[tuple[str, str]] = set()
    for fact_id in redundant_fact_ids:
        entry = by_fact_id.get(str(fact_id))
        if entry is None:
            continue
        category = str(entry.get("category") or "")
        label = _label(category, entry.get("value") or {})
        key = (category, label)
        if key in seen_redundant:
            continue
        seen_redundant.add(key)
        decisions.append(
            Decision(
                decision_id=next_id(),
                outcome="omitted",
                reason=EXCLUDED_REDUNDANT,
                scope="cv",
                category=category or None,
                label=label,
                explanation=(
                    f"{label} was a duplicate of an included fact; every source "
                    "reference was merged into the included entry."
                ),
                documents=document_labels(entry),
            )
        )

    # Contradictions and other insufficiently established details.
    trace_by_proposal = {
        str(entry.get("proposal_id") or ""): entry for entry in trace
    }
    included_labels = {
        _label(str(entry.get("category") or ""), entry.get("value") or {})
        for entry in included_entries
    }
    for conflict in conflicts:
        category = str(conflict.get("category") or "")
        alternatives: list[str] = []
        document_labels_set: list[str] = []
        for proposal_id in conflict.get("proposal_ids") or ():
            entry = trace_by_proposal.get(str(proposal_id))
            if entry is None:
                continue
            label = _label(str(entry.get("category") or category), entry.get("value") or {})
            if label and label not in alternatives:
                alternatives.append(label)
            for document in document_labels(entry):
                if document not in document_labels_set:
                    document_labels_set.append(document)
        explanation = str(conflict.get("message") or "The sources disagree about this detail.")
        if any(label in included_labels for label in alternatives):
            explanation += (
                " The current draft includes one candidate-approved value; the "
                "alternatives remain listed for transparency."
            )
        else:
            explanation += (
                " No value was selected automatically; confirm the correct value "
                "if it matters."
            )
        hint = conflict.get("resolution_hint")
        if isinstance(hint, Mapping) and hint.get("explanation"):
            explanation += (
                " The engine's advisory note: "
                + str(hint["explanation"])
                + " This remains a recommendation and requires candidate confirmation."
            )
        decisions.append(
            Decision(
                decision_id=next_id(),
                outcome="insufficient",
                reason=EXCLUDED_CONFLICT,
                scope="cv",
                category=category or None,
                label=_display(category) if category else "Detail",
                explanation=explanation,
                alternatives=tuple(alternatives),
                documents=tuple(document_labels_set),
            )
        )

    if coverage:
        unmet_items: list[UnmetRequirement] = []
        for assessment in coverage:
            if not is_gap(assessment):
                continue
            missing = tuple(element.label for element in assessment.missing)
            if assessment.state == UNCOVERED:
                explanation = (
                    "No approved fact states this job requirement; it was not "
                    "added to the CV."
                )
            else:
                explanation = (
                    "Only part of this job requirement is supported by approved "
                    "facts"
                    + (f" (missing: {', '.join(missing)})" if missing else "")
                    + "; the draft does not claim the rest."
                )
            unmet_items.append(
                UnmetRequirement(
                    requirement=assessment.requirement.text,
                    explanation=explanation,
                    state=assessment.state,
                    missing=missing,
                )
            )
        unmet = tuple(unmet_items)
    else:
        unmet = tuple(
            UnmetRequirement(
                requirement=requirement,
                explanation=(
                    "No approved fact supports this job requirement; it was not "
                    "added to the CV."
                ),
            )
            for requirement in getattr(draft, "unmet_requirements", ())
        )

    return DecisionReport(
        decisions=tuple(decisions),
        unmet_requirements=unmet,
        requirement_coverage=coverage,
        warnings=tuple(getattr(draft, "warnings", ())),
    )


__all__ = [
    "DECISION_REPORT_VERSION",
    "Decision",
    "DecisionReport",
    "EXCLUDED_CONFLICT",
    "EXCLUDED_LOWER_PRIORITY",
    "EXCLUDED_REDUNDANT",
    "EXCLUDED_UNSUPPORTED",
    "REASONS",
    "SELECTED_ESSENTIAL",
    "SELECTED_RELEVANT",
    "UnmetRequirement",
    "build_decision_report",
    "trace_from_approved_profile",
]
