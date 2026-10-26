"""Tests for the conflict decisions of the candidate profile engine.

Every document is synthetic. The tests cover the cases that must stay apart
and the cases that must be merged.
"""
from __future__ import annotations

import json

from profile_fixtures import make_document, make_response

from joblens_public.profile import (
    ReviewAction,
    apply_review_action,
    build_profile_proposals,
    initial_review_state,
)


def envelope(documents):
    return build_profile_proposals(make_response(documents))


def conflicts_of(profile):
    return profile.conflicts


def language_proposals(profile):
    return [item for item in profile.proposals if item.category.value == "language"]


def project_proposals(profile):
    return [item for item in profile.proposals if item.category.value == "project"]


def test_b2_versus_c1_recommends_the_higher_cefr_level():
    first = make_document("doc_a", "Languages\nEnglish (B2)\n", index=0)
    second = make_document("doc_b", "Languages\nEnglish (C1)\n", index=1)
    profile = envelope([first, second])

    assert len(conflicts_of(profile)) == 1
    conflict = conflicts_of(profile)[0]
    assert conflict.kind == "conflicting_stated_level"
    assert conflict.resolution_hint is not None

    hint = conflict.resolution_hint
    assert hint.strategy == "prefer_higher_cefr_claim"
    assert hint.requires_user_confirmation is True

    levels = {
        proposal.proposal_id: proposal.value["stated_level"]
        for proposal in language_proposals(profile)
    }
    kept = levels[hint.keep_proposal_ids[0]]
    assert kept == "c1"
    assert "C1" in hint.explanation
    assert "no reliable chronology" in hint.explanation


def test_equal_levels_are_merged_and_never_conflict():
    first = make_document("doc_a", "Languages\nEnglish (C1)\n", index=0)
    second = make_document("doc_b", "Languages\nEnglish (C1)\n", index=1)
    profile = envelope([first, second])

    assert conflicts_of(profile) == ()
    languages = language_proposals(profile)
    assert len(languages) == 1
    assert len(languages[0].evidence) == 2
    assert {item.document_id for item in languages[0].evidence} == {"doc_a", "doc_b"}


def test_an_unknown_level_is_not_compared_with_a_cefr_level():
    first = make_document("doc_a", "Languages\nEnglish (professional)\n", index=0)
    second = make_document("doc_b", "Languages\nEnglish (C1)\n", index=1)
    profile = envelope([first, second])

    assert len(conflicts_of(profile)) == 1
    conflict = conflicts_of(profile)[0]
    assert conflict.resolution_hint is None
    payload = conflict.as_dict()
    assert "resolution_hint" not in payload


def test_native_is_not_compared_with_a_cefr_level():
    first = make_document("doc_a", "Languages\nEnglish (native)\n", index=0)
    second = make_document("doc_b", "Languages\nEnglish (C2)\n", index=1)
    profile = envelope([first, second])

    assert len(conflicts_of(profile)) == 1
    assert conflicts_of(profile)[0].resolution_hint is None


def test_two_different_non_cefr_levels_conflict_without_a_hint():
    first = make_document("doc_a", "Languages\nEnglish (fluent)\n", index=0)
    second = make_document("doc_b", "Languages\nEnglish (basic)\n", index=1)
    profile = envelope([first, second])

    assert len(conflicts_of(profile)) == 1
    assert conflicts_of(profile)[0].resolution_hint is None


def test_a_dated_claim_is_preferred_over_a_higher_undated_claim():
    first = make_document("doc_a", "Languages\nEnglish (C1)\n", index=0)
    second = make_document("doc_b", "Languages\nEnglish (B2), 2024\n", index=1)
    profile = envelope([first, second])

    conflict = conflicts_of(profile)[0]
    assert conflict.resolution_hint is not None
    hint = conflict.resolution_hint
    assert hint.strategy == "prefer_dated_claim"
    assert "2024" in hint.explanation
    assert hint.requires_user_confirmation is True

    levels = {
        proposal.proposal_id: proposal.value["stated_level"]
        for proposal in language_proposals(profile)
    }
    assert levels[hint.keep_proposal_ids[0]] == "b2"


def test_the_most_recent_dated_claim_wins_over_the_highest_level():
    first = make_document("doc_a", "Languages\nEnglish (C2), 2015\n", index=0)
    second = make_document("doc_b", "Languages\nEnglish (B2), 2024\n", index=1)
    profile = envelope([first, second])

    hint = conflicts_of(profile)[0].resolution_hint
    assert hint is not None
    assert hint.strategy == "prefer_dated_claim"
    assert "2024" in hint.explanation

    levels = {
        proposal.proposal_id: proposal.value["stated_level"]
        for proposal in language_proposals(profile)
    }
    assert levels[hint.keep_proposal_ids[0]] == "b2"


def test_the_upload_order_never_changes_the_recommendation():
    first = make_document("doc_a", "Languages\nEnglish (C2), 2015\n", index=0)
    second = make_document("doc_b", "Languages\nEnglish (B2), 2024\n", index=1)
    forward = envelope([first, second])
    backward = envelope([second, first])

    forward_hint = conflicts_of(forward)[0].resolution_hint
    backward_hint = conflicts_of(backward)[0].resolution_hint
    assert forward_hint is not None and backward_hint is not None
    assert forward_hint.strategy == backward_hint.strategy
    assert forward_hint.explanation == backward_hint.explanation
    assert set(forward_hint.keep_proposal_ids) == set(backward_hint.keep_proposal_ids)


def test_a_date_outside_the_claim_is_not_attached_to_it():
    first = make_document("doc_a", "Languages\nEnglish (C1), 2019\n", index=0)
    second = make_document("doc_b", "Languages\nEnglish (B2)\n2021\n", index=1)
    profile = envelope([first, second])

    # The date of the second claim is on the next line, so it is not anchored
    # to the claim and the default recommendation applies.
    hint = conflicts_of(profile)[0].resolution_hint
    assert hint is not None
    assert hint.strategy == "prefer_higher_cefr_claim"


def test_duplicate_projects_with_the_same_description_are_merged():
    first = make_document(
        "doc_a", "Projects\nInvoice Tracker - a small billing application\n", index=0
    )
    second = make_document(
        "doc_b", "Projects\nInvoice Tracker - a small billing application\n", index=1
    )
    profile = envelope([first, second])

    assert conflicts_of(profile) == ()
    projects = project_proposals(profile)
    assert len(projects) == 1
    assert projects[0].value == {"name": "invoice tracker"}
    assert len(projects[0].evidence) == 2


def test_complementary_descriptions_of_the_same_project_are_merged():
    first = make_document(
        "doc_a",
        "Projects\nInvoice Tracker - a small billing application for shops\n",
        index=0,
    )
    second = make_document(
        "doc_b",
        "Projects\nInvoice Tracker: a billing application written in Python\n",
        index=1,
    )
    profile = envelope([first, second])

    assert conflicts_of(profile) == ()
    projects = project_proposals(profile)
    assert len(projects) == 1
    assert projects[0].value == {"name": "invoice tracker"}
    assert len(projects[0].evidence) == 2


def test_the_original_descriptions_are_preserved_with_exact_spans():
    document = make_document(
        "doc_a",
        "Projects\nInvoice Tracker - a small billing application for shops\n",
    )
    response = make_response([document])
    profile = build_profile_proposals(response)
    segment = response["documents"][0]["segments"][0]["text"]

    reference = project_proposals(profile)[0].evidence[0]
    assert segment[reference.start:reference.end] == reference.quote
    assert "a small billing application for shops" in reference.quote


def test_a_genuine_ambiguity_keeps_two_proposals_and_reports_a_conflict():
    first = make_document(
        "doc_a",
        "Projects\nLedger - a command line tool for small invoices\n",
        index=0,
    )
    second = make_document(
        "doc_b",
        "Projects\nLedger: a mobile app for small invoices\n",
        index=1,
    )
    profile = envelope([first, second])

    projects = project_proposals(profile)
    assert len(projects) == 2
    assert {item.value["name"] for item in projects} == {"ledger"}

    assert len(conflicts_of(profile)) == 1
    conflict = conflicts_of(profile)[0]
    assert conflict.kind == "conflicting_description"
    assert set(conflict.proposal_ids) == {item.proposal_id for item in projects}
    assert conflict.resolution_hint is None


def test_a_different_technology_is_not_a_contradiction():
    first = make_document(
        "doc_a",
        "Projects\nLedger - a Django application for small invoices\n",
        index=0,
    )
    second = make_document(
        "doc_b",
        "Projects\nLedger: a billing application backed by PostgreSQL\n",
        index=1,
    )
    profile = envelope([first, second])

    assert conflicts_of(profile) == ()
    assert len(project_proposals(profile)) == 1


def test_the_resolution_hint_is_optional_and_additive():
    first = make_document("doc_a", "Languages\nEnglish (native)\n", index=0)
    second = make_document("doc_b", "Languages\nEnglish (C1)\n", index=1)
    profile = envelope([first, second])

    payload = profile.as_dict()
    assert set(payload) == {
        "profile_schema_version",
        "parser_schema_version",
        "job_id",
        "documents",
        "proposals",
        "conflicts",
        "warnings",
    }
    assert "resolution_hint" not in payload["conflicts"][0]
    assert json.loads(json.dumps(payload))["conflicts"][0]["kind"] == (
        "conflicting_stated_level"
    )


def test_a_recommendation_never_approves_anything():
    first = make_document("doc_a", "Languages\nEnglish (B2)\n", index=0)
    second = make_document("doc_b", "Languages\nEnglish (C1)\n", index=1)
    profile = envelope([first, second])
    hint = conflicts_of(profile)[0].resolution_hint
    assert hint is not None

    state = initial_review_state(profile)
    assert state.approved() == ()
    assert all(item.status.value == "proposed" for item in state.proposals)

    approved = apply_review_action(
        state,
        ReviewAction(kind="approve", proposal_id=hint.keep_proposal_ids[0]),
    )
    assert len(approved.approved()) == 1
    assert approved.history[0].kind == "approve"


def test_conflicts_do_not_change_the_review_semantics():
    first = make_document("doc_a", "Languages\nEnglish (B2)\n", index=0)
    second = make_document("doc_b", "Languages\nEnglish (C1)\n", index=1)
    profile = envelope([first, second])
    state = initial_review_state(profile)

    rejected = apply_review_action(
        state,
        ReviewAction(kind="reject", proposal_id=language_proposals(profile)[0].proposal_id),
    )
    assert len(rejected.rejected()) == 1
    assert rejected.history[0].kind == "reject"
