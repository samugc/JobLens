"""Tests for the portable approved-profile contract."""
from __future__ import annotations

from profile_fixtures import make_document, make_response

from joblens_public.profile import build_profile_proposals
from joblens_public.profile.approved import (
    ApprovedProfileError,
    build_approved_profile,
    export_approved_profile,
    import_approved_profile,
)
from joblens_public.profile.review import (
    APPROVE,
    ReviewAction,
    apply_review_action,
    initial_review_state,
)


def _envelope_and_state(*texts):
    documents = [make_document(f"doc_{i}", text, index=i) for i, text in enumerate(texts)]
    response = make_response(documents, job_id="job_approved")
    envelope = build_profile_proposals(response)
    state = initial_review_state(envelope)
    return response, envelope, state


def _approve_all(state):
    for proposal in state.proposals:
        state = apply_review_action(state, ReviewAction(APPROVE, proposal.proposal_id))
    return state


def test_an_empty_review_produces_no_facts():
    response, envelope, state = _envelope_and_state("Skills\nPython\n")
    profile = build_approved_profile(envelope, state, source_response=response)
    assert profile.facts == ()


def test_approved_facts_carry_exact_evidence():
    text = "Skills\nPython\n"
    response, envelope, state = _envelope_and_state(text)
    state = _approve_all(state)
    profile = build_approved_profile(envelope, state, source_response=response)
    assert len(profile.facts) == 1
    fact = profile.facts[0]
    assert fact.category.value == "skill"
    assert fact.value["name"] == "python"
    evidence = fact.evidence[0]
    document = response["documents"][0]
    segment = document["segments"][evidence.segment_index]["text"]
    assert segment[evidence.start:evidence.end] == evidence.quote


def test_export_and_import_round_trip_with_source_validation():
    text = "Skills\nPython\n"
    response, envelope, state = _envelope_and_state(text)
    state = _approve_all(state)
    profile = build_approved_profile(envelope, state, source_response=response)
    exported = export_approved_profile(profile)
    restored = import_approved_profile(exported, source_response=response)
    assert restored.as_dict() == profile.as_dict()


def test_a_malformed_profile_is_rejected():
    try:
        import_approved_profile("{not json")
    except ApprovedProfileError:
        pass
    else:
        raise AssertionError("malformed JSON must be rejected")


def test_a_profile_with_tampered_evidence_is_rejected():
    text = "Skills\nPython\n"
    response, envelope, state = _envelope_and_state(text)
    state = _approve_all(state)
    profile = build_approved_profile(envelope, state, source_response=response)
    payload = profile.as_dict()
    payload["facts"][0]["evidence"][0]["quote"] = "Rust"
    try:
        import_approved_profile(payload, source_response=response)
    except ApprovedProfileError:
        pass
    else:
        raise AssertionError("tampered evidence must be rejected")


def test_a_profile_referencing_an_unknown_document_is_rejected():
    text = "Skills\nPython\n"
    response, envelope, state = _envelope_and_state(text)
    state = _approve_all(state)
    profile = build_approved_profile(envelope, state, source_response=response)
    payload = profile.as_dict()
    payload["facts"][0]["evidence"][0]["document_id"] = "doc_unknown"
    payload["documents"][0]["document_id"] = "doc_unknown"  # make doc ref consistent but unknown to source
    try:
        import_approved_profile(payload, source_response=response)
    except ApprovedProfileError:
        pass
    else:
        raise AssertionError("unknown source document must be rejected")


def test_an_edited_fact_carries_no_evidence_and_cannot_be_approved():
    text = "Skills\nPython\n"
    response, envelope, state = _envelope_and_state(text)
    original = state.proposals[0]
    state = apply_review_action(
        state, ReviewAction("edit", original.proposal_id, {"name": "Rust"})
    )
    # The revision has no supporting evidence and stays proposed.
    revision = [p for p in state.proposals if p.status.value == "proposed"][-1]
    assert revision.evidence == ()
    try:
        apply_review_action(state, ReviewAction(APPROVE, revision.proposal_id))
    except Exception:
        pass
    else:
        raise AssertionError("an unsupported edit must not be approvable")


def test_candidate_contact_defaults_are_empty():
    response, envelope, state = _envelope_and_state("Skills\nPython\n")
    profile = build_approved_profile(envelope, state, source_response=response)
    assert profile.candidate.full_name is None
    assert profile.candidate.email is None
    assert profile.candidate.phone is None
    assert profile.candidate.location is None
    assert profile.candidate.links == ()
