"""Professional claim reconciliation.

This layer reads the same source documents as the profile layer, extracts the
typed professional claims they state, relates those claims with an explicit
comparison framework and proposes consolidation decisions.

It is additive: the profile envelope (schema 0.1), the parser contract
(schema 1.1) and the transport (1.0) are not changed, and the report has its
own version.

The separation is deliberate and stays visible in the report:

* a :class:`~joblens_public.reconcile.models.Claim` says what a source
  states, with its exact evidence;
* a :class:`~joblens_public.reconcile.models.Relationship` says what the
  engine infers about two claims;
* a :class:`~joblens_public.reconcile.models.ResolutionDecision` says what
  the engine recommends, and it always asks for a user confirmation;
* an unresolved conflict says that nothing can be decided yet.

:mod:`joblens_public.reconcile.mapping` is a separate, read-only utility that
links a claim to the proposal of a profile envelope that shares its exact
evidence. It never changes either artifact and never guesses.
"""
from __future__ import annotations

from .comparators import Comparator, Comparison, comparator_for, compare_claims, register
from .engine import reconcile_documents
from .mapping import (
    AMBIGUOUS,
    MATCHED,
    UNMAPPED,
    ClaimProposalMatch,
    ReconciliationMapping,
    map_claim_to_proposals,
    map_claims_to_proposals,
    proposal_categories_for,
)
from .models import (
    APPROVAL_STATE_NOT_APPROVED,
    PARSER_SCHEMA_VERSION,
    PROFILE_SCHEMA_VERSION,
    RECONCILIATION_SCHEMA_VERSION,
    Claim,
    ClaimAttribute,
    ClaimCategory,
    ConsolidatedClaim,
    DocumentReference,
    ReconciliationError,
    ReconciliationReport,
    Relation,
    Relationship,
    Resolution,
    ResolutionDecision,
)
from .policy import resolve
from .semantic import (
    DeterministicReasoner,
    SemanticJudgement,
    SemanticReasoner,
    validate_judgement,
)

__all__ = [
    "AMBIGUOUS",
    "APPROVAL_STATE_NOT_APPROVED",
    "MATCHED",
    "PARSER_SCHEMA_VERSION",
    "PROFILE_SCHEMA_VERSION",
    "RECONCILIATION_SCHEMA_VERSION",
    "UNMAPPED",
    "Claim",
    "ClaimAttribute",
    "ClaimCategory",
    "ClaimProposalMatch",
    "Comparison",
    "Comparator",
    "ConsolidatedClaim",
    "DeterministicReasoner",
    "DocumentReference",
    "ReconciliationError",
    "ReconciliationMapping",
    "ReconciliationReport",
    "Relation",
    "Resolution",
    "ResolutionDecision",
    "Relationship",
    "SemanticJudgement",
    "SemanticReasoner",
    "compare_claims",
    "comparator_for",
    "map_claim_to_proposals",
    "map_claims_to_proposals",
    "proposal_categories_for",
    "reconcile_documents",
    "register",
    "resolve",
    "validate_judgement",
]
