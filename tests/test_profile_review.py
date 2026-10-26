"""Tests for the pure candidate profile review reducer."""
from __future__ import annotations

import json

import pytest
from profile_fixtures import EDUCATION_SECTION, SKILLS_SECTION, make_document, make_response

from joblens_public.profile import (
    ProfileError,
    ReviewAction,
    apply_review_action,
    build_profile_proposals,
    initial_review_state,
)


def envelope():
    document = make_document("doc_a", SKILLS_SECTION)
    return build_profile_proposals(make_response([document]))


def skill_proposal(source):
    """Find the Python proposal in an envelope or in a review state."""
    return next(
        proposal
        for proposal in source.proposals
        if proposal.value.get("name") == "python"
    )


def test_initial_state_has_no_history_and_no_decisions():
    profile = envelope()
    state = initial_review_state(profile)

    assert state.sequence == 0
    assert state.history == ()
    assert state.approved() == ()
    assert state.rejected() == ()
    assert all(item.status.value == "proposed" for item in state.proposals)


def test_nothing_is_approved_without_an_explicit_action():
    profile = envelope()
    state = initial_review_state(profile)

    assert all(item.status.value == "proposed" for item in profile.proposals)
    assert all(item.status.value == "proposed" for item in state.proposals)
    assert state.approved() == ()
    assert state.history == ()


def test_approve_marks_the_proposal_and_records_the_history():
    profile = envelope()
    state = initial_review_state(profile)
    target = skill_proposal(profile)

    updated = apply_review_action(
        state,
        ReviewAction(kind="approve", proposal_id=target.proposal_id),
    )

    assert updated.proposal(target.proposal_id).status.value == "approved"
    assert len(updated.approved()) == 1
    assert updated.sequence == 1
    assert updated.history[0].kind == "approve"
    assert updated.history[0].proposal_id == target.proposal_id


def test_reject_marks_the_proposal_and_keeps_it_in_the_state():
    profile = envelope()
    state = initial_review_state(profile)
    target = skill_proposal(profile)

    updated = apply_review_action(
        state,
        ReviewAction(kind="reject", proposal_id=target.proposal_id),
    )

    assert updated.proposal(target.proposal_id).status.value == "rejected"
    assert len(updated.rejected()) == 1
    assert updated.history[0].kind == "reject"


def test_a_rejected_proposal_can_be_approved_later():
    profile = envelope()
    state = initial_review_state(profile)
    target = skill_proposal(profile)

    rejected = apply_review_action(
        state, ReviewAction(kind="reject", proposal_id=target.proposal_id)
    )
    approved = apply_review_action(
        rejected, ReviewAction(kind="approve", proposal_id=target.proposal_id)
    )

    assert approved.proposal(target.proposal_id).status.value == "approved"
    assert [event.kind for event in approved.history] == ["reject", "approve"]


def test_edit_creates_a_revised_proposal_in_proposed_state():
    profile = envelope()
    state = initial_review_state(profile)
    target = skill_proposal(profile)

    updated = apply_review_action(
        state,
        ReviewAction(
            kind="edit",
            proposal_id=target.proposal_id,
            value={"name": "java"},
        ),
    )

    assert len(updated.proposals) == len(profile.proposals) + 1
    revision = updated.proposals[-1]
    assert revision.status.value == "proposed"
    assert revision.value == {"name": "java"}
    assert revision.proposal_id != target.proposal_id
    assert updated.history[0].kind == "edit"
    assert updated.history[0].revision_id == revision.proposal_id


def test_edit_revokes_the_approval_of_an_approved_fact():
    profile = envelope()
    state = initial_review_state(profile)
    target = skill_proposal(profile)

    approved = apply_review_action(
        state, ReviewAction(kind="approve", proposal_id=target.proposal_id)
    )
    assert approved.proposal(target.proposal_id).status.value == "approved"

    edited = apply_review_action(
        approved,
        ReviewAction(
            kind="edit",
            proposal_id=target.proposal_id,
            value={"name": "java"},
        ),
    )

    assert edited.proposal(target.proposal_id).status.value == "superseded"
    assert edited.approved() == ()
    assert edited.proposals[-1].status.value == "proposed"


def test_an_unsupported_edit_keeps_no_evidence_and_cannot_be_approved():
    profile = envelope()
    state = initial_review_state(profile)
    target = skill_proposal(profile)

    edited = apply_review_action(
        state,
        ReviewAction(
            kind="edit",
            proposal_id=target.proposal_id,
            value={"name": "java"},
        ),
    )
    revision = edited.proposals[-1]

    assert revision.evidence == ()
    assert edited.history[0].supported is False

    with pytest.raises(ProfileError):
        apply_review_action(
            edited,
            ReviewAction(kind="approve", proposal_id=revision.proposal_id),
        )


def test_a_supported_edit_keeps_the_evidence():
    profile = envelope()
    state = initial_review_state(profile)
    target = skill_proposal(profile)

    edited = apply_review_action(
        state,
        ReviewAction(
            kind="edit",
            proposal_id=target.proposal_id,
            value={"name": "Python"},
        ),
    )
    revision = edited.proposals[-1]

    assert revision.value == {"name": "Python"}
    assert revision.evidence
    assert edited.history[0].supported is True

    approved = apply_review_action(
        edited,
        ReviewAction(kind="approve", proposal_id=revision.proposal_id),
    )
    assert approved.proposal(revision.proposal_id).status.value == "approved"


def test_an_education_edit_keeps_the_evidence_when_the_degree_is_still_quoted():
    document = make_document("doc_edu", EDUCATION_SECTION)
    profile = build_profile_proposals(make_response([document]))
    state = initial_review_state(profile)
    education = next(
        proposal for proposal in profile.proposals if proposal.category.value == "education"
    )

    edited = apply_review_action(
        state,
        ReviewAction(
            kind="edit",
            proposal_id=education.proposal_id,
            value={"level": "bachelor", "field": "computer science"},
        ),
    )
    revision = edited.proposals[-1]

    assert revision.evidence
    assert edited.history[0].supported is True


def test_the_history_is_preserved_in_order():
    profile = envelope()
    state = initial_review_state(profile)
    target = skill_proposal(profile)

    state = apply_review_action(
        state, ReviewAction(kind="reject", proposal_id=target.proposal_id)
    )
    state = apply_review_action(
        state,
        ReviewAction(
            kind="edit",
            proposal_id=target.proposal_id,
            value={"name": "python"},
        ),
    )
    state = apply_review_action(
        state,
        ReviewAction(kind="approve", proposal_id=state.proposals[-1].proposal_id),
    )

    assert [event.sequence for event in state.history] == [1, 2, 3]
    assert [event.kind for event in state.history] == ["reject", "edit", "approve"]


def test_the_reducer_does_not_modify_the_previous_state():
    profile = envelope()
    state = initial_review_state(profile)
    target = skill_proposal(profile)

    updated = apply_review_action(
        state, ReviewAction(kind="approve", proposal_id=target.proposal_id)
    )

    assert state.proposal(target.proposal_id).status.value == "proposed"
    assert state.history == ()
    assert updated is not state


def test_unknown_proposal_is_rejected():
    state = initial_review_state(envelope())
    with pytest.raises(ProfileError):
        apply_review_action(state, ReviewAction(kind="approve", proposal_id="prop_missing"))


def test_unknown_action_is_rejected():
    state = initial_review_state(envelope())
    target = skill_proposal(state)
    with pytest.raises(ProfileError):
        apply_review_action(state, ReviewAction(kind="auto", proposal_id=target.proposal_id))


def test_edit_without_a_value_is_rejected():
    state = initial_review_state(envelope())
    target = skill_proposal(state)
    with pytest.raises(ProfileError):
        apply_review_action(state, ReviewAction(kind="edit", proposal_id=target.proposal_id))


def test_the_review_state_serialises():
    profile = envelope()
    state = initial_review_state(profile)
    target = skill_proposal(profile)
    state = apply_review_action(
        state, ReviewAction(kind="approve", proposal_id=target.proposal_id)
    )

    payload = state.as_dict()
    assert payload["review_sequence"] == 1
    assert payload["proposals"]
    assert payload["history"][0]["kind"] == "approve"
    assert json.loads(json.dumps(payload))["history"][0]["proposal_id"] == target.proposal_id
