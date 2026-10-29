"""Regression tests for factual provenance at the edit/approve/export boundary.

These tests pin three invariants:

1. Changing an item's wording invalidates its provenance: the item can no longer
   be approved as if approved facts still supported the new text.
2. Candidate attestation is represented by an ``attestation:<item_id>``
   citation, never by the fact ids of the text it replaced.
3. Export refuses citations it cannot verify: unknown ids without support,
   attestation ids belonging to another item, mixed citations, and stale
   wording. Matching ids are still only an identifier check, not an entailment
   proof.
"""

from __future__ import annotations

import json

import pytest
from profile_fixtures import make_document, make_response

from joblens_public.cv import (
    APPROVED,
    ATTESTATION_PREFIX,
    NEEDS_REVIEW,
    PROVENANCE_ATTESTED,
    PROVENANCE_SOURCE,
    PROVENANCE_STALE,
    approve_cv_item,
    edit_cv_item,
    generate_cv_draft,
)
from joblens_public.export import export_cv_pdf_bytes
from joblens_public.export.errors import EvidenceContractError
from joblens_public.jobs import parse_job_posting
from joblens_public.profile import build_profile_proposals
from joblens_public.profile.approved import build_approved_profile
from joblens_public.profile.review import (
    APPROVE,
    ReviewAction,
    apply_review_action,
    initial_review_state,
)

CV1 = """Skills
Python, SQL

Experience
Data Engineer | Acme Corporation | 2019-2022
Built reporting services in Python.

Education
BSc in Computer Science
"""


def _profile():
    documents = [make_document("doc_0", CV1, index=0)]
    response = make_response(documents, job_id="job_cv")
    envelope = build_profile_proposals(response)
    state = initial_review_state(envelope)
    for proposal in state.proposals:
        state = apply_review_action(state, ReviewAction(APPROVE, proposal.proposal_id))
    return build_approved_profile(envelope, state, source_response=response)


def _draft():
    job = parse_job_posting("Senior AI Engineer\nRequired\nPython", title="Senior AI Engineer")
    return generate_cv_draft(_profile(), job)


def _first_item(draft):
    return draft.sections[0].items[0]


def _minimal_draft(**item_overrides):
    item = {
        "item_id": "item_1",
        "text": "Data engineer",
        "approved_fact_ids": ["fact_1"],
        "review_status": "approved",
    }
    item.update(item_overrides)
    return {
        "cv_draft_version": "0.1",
        "target_job": {"title": "X", "company": "Y"},
        "candidate": {"full_name": "Jane Example"},
        "sections": [
            {"section_id": "s1", "kind": "summary", "title": "Summary", "items": [item]}
        ],
    }


# ---------------------------------------------------------------------------
# 1. Edited wording cannot keep pretending to be fact-supported
# ---------------------------------------------------------------------------


def test_edit_marks_provenance_stale_and_blocks_plain_approval():
    draft = _draft()
    item_id = _first_item(draft).item_id
    edited = edit_cv_item(draft, item_id, "AWS Certified Cloud Practitioner")

    item = _first_item(edited)
    assert item.review_status == NEEDS_REVIEW
    assert item.provenance == PROVENANCE_STALE
    # The original ids are kept as an audit trail, not as a support claim.
    with pytest.raises(ValueError, match="attestation"):
        approve_cv_item(edited, item_id)


def test_attested_approval_replaces_fact_ids_with_attestation_id():
    draft = _draft()
    item_id = _first_item(draft).item_id
    edited = edit_cv_item(draft, item_id, "AWS Certified Cloud Practitioner")
    approved = approve_cv_item(edited, item_id, attest=True)

    item = _first_item(approved)
    assert item.review_status == APPROVED
    assert item.provenance == PROVENANCE_ATTESTED
    assert item.approved_fact_ids == (ATTESTATION_PREFIX + item_id,)


def test_unedited_item_keeps_source_provenance_and_fact_ids():
    draft = _draft()
    item = _first_item(draft)
    assert item.provenance == PROVENANCE_SOURCE
    approved = approve_cv_item(draft, item.item_id)
    assert _first_item(approved).approved_fact_ids == item.approved_fact_ids
    assert _first_item(approved).provenance == PROVENANCE_SOURCE


def test_provenance_survives_serialisation_round_trip():
    from joblens_public.cv import CvDraft

    draft = _draft()
    item_id = _first_item(draft).item_id
    edited = edit_cv_item(draft, item_id, "Rewritten")
    parsed = CvDraft.from_dict(edited.as_dict())
    assert _first_item(parsed).provenance == PROVENANCE_STALE
    # Unchanged items keep the legacy shape: no provenance key is emitted.
    assert "provenance" not in _first_item(draft).as_dict()


# ---------------------------------------------------------------------------
# 2. Export evidence contract
# ---------------------------------------------------------------------------


def test_export_rejects_unhandled_unknown_fact_ids_without_support():
    with pytest.raises(EvidenceContractError):
        export_cv_pdf_bytes(_minimal_draft(approved_fact_ids=["fact_does_not_exist"]))


def test_export_accepts_explicitly_unverified_rendering_input():
    draft = _minimal_draft()
    assert export_cv_pdf_bytes(draft, allow_unverified=True)[:4] == b"%PDF"


def test_export_rejects_another_items_attestation():
    with pytest.raises(EvidenceContractError):
        export_cv_pdf_bytes(
            _minimal_draft(approved_fact_ids=["attestation:item_OTHER"]),
            evidence_support={"facts": [{"fact_id": "attestation:item_OTHER"}]},
        )


def test_export_rejects_mixed_attestation_and_fact_ids():
    with pytest.raises(EvidenceContractError):
        export_cv_pdf_bytes(
            _minimal_draft(approved_fact_ids=["fact_1", "attestation:item_1"]),
            evidence_support={"facts": [{"fact_id": "fact_1"}, {"fact_id": "attestation:item_1"}]},
        )


def test_export_rejects_stale_wording_marked_approved():
    draft = _minimal_draft(provenance="stale")
    with pytest.raises(EvidenceContractError):
        export_cv_pdf_bytes(
            draft, evidence_support={"facts": [{"fact_id": "fact_1"}]}
        )


def test_attested_item_export_labels_attestation_not_a_fact():
    draft = _minimal_draft(
        approved_fact_ids=["attestation:item_1"], provenance="attested"
    )
    data = export_cv_pdf_bytes(
        draft, evidence_support={"facts": [{"fact_id": "attestation:item_1"}]}
    )
    assert data[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# 3. Optional LLM rewrite is not treated as fact-supported wording
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_accepted_rewrite_is_stale_and_needs_attestation(monkeypatch):
    claim = "Data Engineer with skills in Python and SQL."
    monkeypatch.setattr(
        "joblens_public.cv.urllib.request.urlopen",
        lambda *a, **k: _FakeResponse({"response": json.dumps({"text": claim})}),
    )
    job = parse_job_posting("Senior AI Engineer\nRequired\nPython")
    draft = generate_cv_draft(_profile(), job, ollama=True)

    summary = next(s for s in draft.sections if s.kind == "summary")
    item = summary.items[0]
    assert item.text == claim
    assert item.provenance == PROVENANCE_STALE
    with pytest.raises(ValueError, match="attestation"):
        approve_cv_item(draft, item.item_id)
    approved = approve_cv_item(draft, item.item_id, attest=True)
    typed = next(s for s in approved.sections if s.kind == "summary").items[0]
    assert typed.approved_fact_ids == (ATTESTATION_PREFIX + item.item_id,)


def test_token_guard_is_vocabulary_only_not_entailment():
    """Documents the guard's real limit: it cannot stop cross-fact conflation."""
    from types import SimpleNamespace

    from joblens_public.cv import _ollama_rewrite_summary

    class Fact:
        def __init__(self, fact_id, value):
            self.fact_id = fact_id
            self.value = value

    profile = SimpleNamespace(facts=[
        Fact("f1", {"role": "data engineer", "organization": "Acme"}),
        Fact("f2", {"name": "Python"}),
        Fact("f3", {"name": "SQL", "tenure": "5 years"}),
    ])

    def fake_urlopen(*args, **kwargs):
        return _FakeResponse(
            {"response": json.dumps({"text": "Data engineer with 5 years Python at Acme."})}
        )

    import joblens_public.cv as cv_module

    original = cv_module.urllib.request.urlopen
    cv_module.urllib.request.urlopen = fake_urlopen
    try:
        accepted = _ollama_rewrite_summary(
            "Data engineer with Python at Acme.", ("f1", "f2", "f3"), profile
        )
    finally:
        cv_module.urllib.request.urlopen = original
    # Accepted although the five years belong to SQL, not Python. The guard is a
    # vocabulary filter; provenance is protected by the stale/attestation path.
    assert accepted == "Data engineer with 5 years Python at Acme."
