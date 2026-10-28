"""Regression tests for conservative job-technology and gap extraction."""

from __future__ import annotations

from joblens_public.cv import generate_cv_draft
from joblens_public.jobs import parse_job_posting
from joblens_public.profile.approved import ApprovedFact, ApprovedProfile
from joblens_public.profile.models import Category, EvidenceReference, Support


def test_javascript_does_not_request_java():
    job = parse_job_posting("Required\nJavaScript\nREST APIs\n")
    assert "javascript" in job.technologies
    assert "java" not in job.technologies


def test_the_word_tests_does_not_request_typescript():
    job = parse_job_posting("Required\nPython\nRun automated tests.\n")
    assert "typescript" not in job.technologies


def test_rest_apis_is_canonicalised_as_a_technology():
    job = parse_job_posting("Required\nREST APIs\n")
    assert "rest api" in job.technologies


def test_visible_source_evidence_is_not_reported_as_a_gap():
    quote = "Built Python REST APIs for document ingestion."
    evidence = EvidenceReference(
        document_id="doc_synthetic",
        segment_index=0,
        locator={"page": 1},
        quote=quote,
        start=0,
        end=len(quote),
        support=Support.EXPLICIT_CLAIM,
    )
    profile = ApprovedProfile(
        approved_profile_version="1.0",
        parser_schema_version="1.1",
        profile_schema_version="1.0",
        job_id="job_synthetic",
        documents=(),
        facts=(
            ApprovedFact(
                fact_id="fact_experience",
                category=Category.EXPERIENCE,
                value={"role": "Software Engineer"},
                evidence=(evidence,),
                source_document_ids=("doc_synthetic",),
                review_sequence=1,
            ),
        ),
    )
    job = parse_job_posting("Required\nPython\nREST APIs\n")
    draft = generate_cv_draft(profile, job)
    assert "rest api" not in {item.casefold() for item in draft.unmet_requirements}


def test_noise_matching_does_not_delete_content_words():
    job = parse_job_posting(
        "Platform Engineer\n\nRequired\n"
        "Shared on-call rotation\n"
        "Home automation experience\n"
        "Python\n"
    )
    assert "Shared on-call rotation" in job.required
    assert "Home automation experience" in job.required


def test_the_share_and_home_navigation_labels_are_still_noise():
    job = parse_job_posting(
        "Platform Engineer\n\nRequired\nPython\n\nShare\nHome\nSave job\n"
    )
    assert job.required == ("Python",)
