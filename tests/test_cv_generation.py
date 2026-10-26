"""Tests for deterministic CV generation."""
from __future__ import annotations

from profile_fixtures import make_document, make_response

from joblens_public.cv import (
    NEEDS_REVIEW,
    approve_cv_item,
    can_export,
    edit_cv_item,
    generate_cv_draft,
    validate_export_eligibility,
)
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

Projects
Ledger - a Django application that reduced costs by 30%

Education
BSc in Computer Science, University of Manchester (2016-2019)

Languages
English (C1)

Certifications
AWS Certified Solutions Architect
"""

CV2 = """Skills
Python, Docker

Experience
Senior Data Engineer | Acme Corporation | 2022-present

Projects
Ledger - a Django application that reduced costs by 30%

Education
MSc in Data Science, University of Manchester (2019-2021)
"""

JOB_TEXT = """Senior AI Engineer

Required
Python
SQL
Docker
Kubernetes
5+ years experience

Preferred
AWS

Responsibilities
Build and deploy machine learning pipelines

About
We are a fast-growing AI company.
"""


def _profile(*texts, approve_all=True):
    documents = [make_document(f"doc_{i}", text, index=i) for i, text in enumerate(texts)]
    response = make_response(documents, job_id="job_cv")
    envelope = build_profile_proposals(response)
    state = initial_review_state(envelope)
    if approve_all:
        for proposal in state.proposals:
            state = apply_review_action(state, ReviewAction(APPROVE, proposal.proposal_id))
    return response, build_approved_profile(envelope, state, source_response=response)


def test_a_full_draft_contains_only_approved_facts():
    response, profile = _profile(CV1, CV2)
    job = parse_job_posting(JOB_TEXT, title="Senior AI Engineer", company="Acme AI")
    draft = generate_cv_draft(profile, job)

    assert draft.cv_draft_version == "0.1"
    assert draft.target_job.title == "Senior AI Engineer"
    assert draft.target_job.company == "Acme AI"
    kinds = [section.kind for section in draft.sections]
    assert "experience" in kinds
    assert "skills" in kinds
    assert "projects" in kinds
    # Every factual item cites at least one approved fact.
    for section in draft.sections:
        for item in section.items:
            assert item.approved_fact_ids
            assert item.review_status == NEEDS_REVIEW
    # Kubernetes is requested but not approved -> gap.
    assert "Kubernetes" in draft.unmet_requirements


def test_zero_approved_facts_cannot_produce_experience():
    response, profile = _profile(CV1, CV2, approve_all=False)
    job = parse_job_posting(JOB_TEXT)
    draft = generate_cv_draft(profile, job)
    assert draft.sections == ()
    assert any("No approved facts" in w for w in draft.warnings)
    # No item may exist without approved facts.
    for section in draft.sections:
        for item in section.items:
            assert item.approved_fact_ids


def test_an_unsupported_requested_skill_remains_a_gap():
    response, profile = _profile(CV1, CV2)
    job = parse_job_posting(JOB_TEXT)
    draft = generate_cv_draft(profile, job)
    assert "Kubernetes" in draft.unmet_requirements


def test_missing_candidate_details_stay_empty():
    response, profile = _profile(CV1)
    job = parse_job_posting(JOB_TEXT)
    draft = generate_cv_draft(profile, job)
    assert draft.candidate.full_name is None
    assert any("full name" in w for w in draft.warnings)


def test_generation_is_deterministic():
    response, profile = _profile(CV1, CV2)
    job = parse_job_posting(JOB_TEXT)
    first = generate_cv_draft(profile, job).as_dict()
    second = generate_cv_draft(profile, job).as_dict()
    assert first == second


def test_a_user_edit_revokes_approval():
    response, profile = _profile(CV1)
    job = parse_job_posting(JOB_TEXT)
    draft = generate_cv_draft(profile, job)
    item_id = draft.sections[0].items[0].item_id
    approved = approve_cv_item(draft, item_id)
    assert approved.sections[0].items[0].review_status == "approved"
    edited = edit_cv_item(approved, item_id, "Rewritten text")
    assert edited.sections[0].items[0].review_status == NEEDS_REVIEW
    assert edited.sections[0].items[0].text == "Rewritten text"


def test_export_is_blocked_until_every_item_is_approved():
    response, profile = _profile(CV1)
    job = parse_job_posting(JOB_TEXT)
    draft = generate_cv_draft(profile, job)
    assert not can_export(draft)
    reasons = validate_export_eligibility(draft)
    assert any("not approved" in r for r in reasons)
    # Approve every item explicitly.
    for section in draft.sections:
        for item in section.items:
            draft = approve_cv_item(draft, item.item_id)
    # Contact details still missing.
    assert not can_export(draft)
    assert any("full name" in r for r in validate_export_eligibility(draft))


def test_a_draft_round_trips():
    response, profile = _profile(CV1)
    job = parse_job_posting(JOB_TEXT)
    draft = generate_cv_draft(profile, job)
    from joblens_public.cv import CvDraft

    restored = CvDraft.from_dict(draft.as_dict())
    assert restored.as_dict() == draft.as_dict()


def test_an_unapproved_item_cannot_be_approved():
    response, profile = _profile(CV1)
    # Remove approved facts from an item by editing? Instead test approve on a
    # synthetic item-less draft is not applicable; test approve_cv_item rejects
    # items without facts is covered by construction (all items have facts).
    # Forcing approval of an item with empty facts is impossible via the API
    # because generated items always carry facts. Verify the guard exists:
    from joblens_public.cv import CvDraft, CvDraftItem, CvDraftSection

    empty_item = CvDraftItem(item_id="x", text="x", approved_fact_ids=(), review_status=NEEDS_REVIEW)
    empty_draft = CvDraft(sections=(CvDraftSection(section_id="s", kind="summary", title="S", items=(empty_item,)),))
    try:
        approve_cv_item(empty_draft, "x")
    except ValueError:
        pass
    else:
        raise AssertionError("an item without facts must not be approvable")
