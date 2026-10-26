"""Evidence-grounded candidate fact proposals.

This package turns the canonical CV parser response (schema 1.1) into
reviewable fact proposals. It is a separate layer from the parser: the parser
still only extracts text and locators, and nothing here changes schema 1.1.

* :func:`build_profile_proposals` is a pure, deterministic function.
* :func:`apply_review_action` is a pure reducer over an in-memory session.

No model, no network call, no database and no automatic approval.
"""
from __future__ import annotations

from .contact import (
    CONTACT_FIELDS,
    CONTACT_SUGGESTIONS_VERSION,
    ContactSuggestion,
    ContactSuggestionError,
    ContactSuggestions,
    ContactValue,
    extract_contact_suggestions,
)
from .engine import USABLE_DOCUMENT_STATUSES, build_profile_proposals
from .models import (
    PARSER_SCHEMA_VERSION,
    PROFILE_SCHEMA_VERSION,
    Category,
    Conflict,
    DocumentReference,
    EvidenceReference,
    ProfileEnvelope,
    ProfileError,
    Proposal,
    ProposalStatus,
    Support,
)
from .review import (
    APPROVE,
    EDIT,
    REJECT,
    ReviewAction,
    ReviewEvent,
    ReviewState,
    apply_review_action,
    initial_review_state,
)

__all__ = [
    "APPROVE",
    "EDIT",
    "PARSER_SCHEMA_VERSION",
    "PROFILE_SCHEMA_VERSION",
    "REJECT",
    "USABLE_DOCUMENT_STATUSES",
    "CONTACT_FIELDS",
    "CONTACT_SUGGESTIONS_VERSION",
    "Category",
    "Conflict",
    "ContactSuggestion",
    "ContactSuggestionError",
    "ContactSuggestions",
    "ContactValue",
    "DocumentReference",
    "EvidenceReference",
    "ProfileEnvelope",
    "ProfileError",
    "Proposal",
    "ProposalStatus",
    "ReviewAction",
    "ReviewEvent",
    "ReviewState",
    "Support",
    "apply_review_action",
    "build_profile_proposals",
    "extract_contact_suggestions",
    "initial_review_state",
]
