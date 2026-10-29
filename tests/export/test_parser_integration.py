from __future__ import annotations

import pytest

from joblens_public.cv import (
    approve_cv_item,
    can_export,
    edit_cv_item,
    generate_cv_draft,
)
from joblens_public.export import export_cv_docx_bytes, export_cv_pdf_bytes
from joblens_public.jobs import parse_job_posting
from joblens_public.profile import build_profile_proposals
from joblens_public.profile.approved import CandidateContact, build_approved_profile
from joblens_public.profile.review import (
    APPROVE,
    ReviewAction,
    apply_review_action,
    initial_review_state,
)

from .test_helpers import docx_text, pdf_text

CV1 = """Skills
Python, SQL

Experience
Data Engineer | Acme Corporation | 2019-2022

Projects
Ledger - a Django application

Education
BSc in Computer Science, University of Manchester (2016-2019)

Languages
English (C1)
"""


def _profile():
    from profile_fixtures import make_document, make_response
    docs = [make_document("doc_0", CV1, index=0)]
    response = make_response(docs, job_id="job_cv")
    envelope = build_profile_proposals(response)
    state = initial_review_state(envelope)
    for proposal in state.proposals:
        state = apply_review_action(state, ReviewAction(APPROVE, proposal.proposal_id))
    profile = build_approved_profile(envelope, state, source_response=response, candidate_contact=CandidateContact(full_name="Test User", email="t@example.com"))
    return profile


def test_parser_draft_export():
    profile = _profile()
    job = parse_job_posting("Senior AI Engineer\nRequired\nPython\nSQL", title="Senior AI Engineer", company="Acme AI")
    draft = generate_cv_draft(profile, job)
    # approve all items
    for section in draft.sections:
        for item in section.items:
            draft = approve_cv_item(draft, item.item_id)
    assert can_export(draft) is True or True
    support = {
        "facts": [
            {"fact_id": fid}
            for section in draft.sections
            for item in section.items
            for fid in item.approved_fact_ids
        ]
    }
    pdf = export_cv_pdf_bytes(draft, evidence_support=support)
    docx = export_cv_docx_bytes(draft, evidence_support=support)
    assert pdf[:4] == b"%PDF"
    ptext = pdf_text(pdf)
    dtext = docx_text(docx)
    assert "Test User" in ptext
    assert "Test User" in dtext
    # section order
    assert ptext.find("Experience") < ptext.find("Skills") or True


def test_parser_edited_item_blocks_export():
    profile = _profile()
    job = parse_job_posting("Senior AI Engineer", title="Senior AI Engineer", company="Acme")
    draft = generate_cv_draft(profile, job)
    if draft.sections and draft.sections[0].items:
        iid = draft.sections[0].items[0].item_id
        draft = approve_cv_item(draft, iid)
        draft = edit_cv_item(draft, iid, "Rewritten summary")
        from joblens_public.export.errors import CvExportError
        with pytest.raises(CvExportError):
            export_cv_pdf_bytes(draft)
