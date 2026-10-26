"""P2 contract tests for the claim-to-proposal mapping utility.

The mapping is deterministic, read-only and exact-evidence based. It returns
``matched``, ``ambiguous`` or ``unmapped`` for every claim, it never guesses a
correspondence and it never synchronises the two artifacts.

Every document is synthetic.
"""
from __future__ import annotations

import json

from profile_fixtures import make_document, make_response

from joblens_public.profile import (
    Category,
    EvidenceReference,
    Proposal,
    ProposalStatus,
    Support,
    build_profile_proposals,
)
from joblens_public.reconcile import (
    AMBIGUOUS,
    MATCHED,
    UNMAPPED,
    map_claim_to_proposals,
    map_claims_to_proposals,
    proposal_categories_for,
    reconcile_documents,
)

TEXT = (
    "Skills\nPython, SQL\n\n"
    "Languages\nEnglish (C1)\n\n"
    "Education\nBSc in Computer Science, University of Manchester (2016-2019)\n\n"
    "Projects\nLedger - a Django application that reduced costs by 30%\n\n"
    "Certifications\nAWS Certified Solutions Architect\n\n"
    "Experience\nData Engineer | Acme Corporation | 2019-2022\n"
)


def artifacts(texts=(TEXT,)):
    documents = [
        make_document(f"doc_{index}", text, index=index)
        for index, text in enumerate(texts)
    ]
    response = make_response(documents, job_id="job_mapping")
    return response, reconcile_documents(response), build_profile_proposals(response)


def matches_of(mapping, category: str):
    return [
        match for match in mapping.matches if match.claim_category == category
    ]


def test_a_skill_claim_maps_to_its_exact_proposal():
    _, report, envelope = artifacts()
    mapping = map_claims_to_proposals(report, envelope)

    match = mapping.for_claim(next(c.claim_id for c in report.claims if c.subject == "sql"))
    assert match.outcome == MATCHED
    assert match.proposal_category == "skill"
    assert match.span_relation == "exact"
    assert match.compatible_attributes == ("name",)
    assert match.conflicting_attributes == ()
    assert match.claim_support == "explicit_claim"
    assert match.proposal_support == "explicit_claim"

    proposal = next(
        item for item in envelope.proposals if item.proposal_id == match.proposal_id
    )
    assert proposal.value["name"] == "sql"


def test_a_keyword_mention_is_reported_as_a_mention_on_both_sides():
    _, report, envelope = artifacts(
        ("Projects\nLedger - a Django application for small shops\n",)
    )
    mapping = map_claims_to_proposals(report, envelope)
    match = next(
        item
        for item in mapping.matches
        if item.claim_category == "skill"
    )

    assert match.outcome == MATCHED
    assert match.claim_support == "keyword_mention"
    assert match.proposal_support == "keyword_mention"


def test_a_project_claim_maps_through_exact_containment():
    _, report, envelope = artifacts()
    mapping = map_claims_to_proposals(report, envelope)

    project = matches_of(mapping, "project")[0]
    technology = matches_of(mapping, "technology")[0]
    achievement = matches_of(mapping, "achievement")[0]

    assert project.outcome == MATCHED
    assert project.span_relation == "claim_within_proposal"
    assert project.compatible_attributes == ("name",)

    # A technology and a responsibility belong to the project entry they are
    # nested in. They are never mapped to a proposal of their own.
    for match in (technology, achievement):
        assert match.outcome == MATCHED
        assert match.proposal_id == project.proposal_id
        assert match.span_relation == "claim_within_proposal"
        assert match.compatible_attributes == ("project",)


def test_education_and_degree_map_to_the_same_education_proposal():
    _, report, envelope = artifacts()
    mapping = map_claims_to_proposals(report, envelope)

    education = matches_of(mapping, "education")[0]
    degree = matches_of(mapping, "degree")[0]

    assert education.outcome == MATCHED
    assert degree.outcome == MATCHED
    assert education.proposal_id == degree.proposal_id
    assert education.span_relation == "proposal_within_claim"
    assert education.compatible_attributes == ("level", "field")


def test_an_employment_claim_maps_through_containment():
    _, report, envelope = artifacts()
    mapping = map_claims_to_proposals(report, envelope)

    employment = matches_of(mapping, "employment")[0]
    assert employment.outcome == MATCHED
    assert employment.proposal_category == "experience"
    assert employment.span_relation == "proposal_within_claim"
    assert employment.compatible_attributes == ("role",)


def test_categories_without_a_profile_counterpart_are_unmapped():
    _, report, envelope = artifacts()
    mapping = map_claims_to_proposals(report, envelope)

    assert proposal_categories_for(report.claim(
        next(c.claim_id for c in report.claims if c.category.value == "organization")
    ).category) == ()

    for category in ("organization", "institution"):
        match = matches_of(mapping, category)[0]
        assert match.outcome == UNMAPPED
        assert match.proposal_id is None
        assert "no profile proposal category" in match.reason


def test_a_claim_without_a_shared_source_text_is_unmapped():
    _, report, envelope = artifacts()
    skill = next(
        claim
        for claim in report.claims
        if claim.category.value == "skill" and claim.subject == "sql"
    )
    # Drop the proposal the claim belongs to: nothing else shares its text.
    remaining = tuple(
        proposal
        for proposal in envelope.proposals
        if not (proposal.category is Category.SKILL and proposal.value["name"] == "sql")
    )
    match = map_claim_to_proposals(skill, remaining)

    assert match.outcome == UNMAPPED
    assert "no proposal of a compatible category shares the exact evidence" in match.reason
    assert match.candidate_proposal_ids == ()


def _proposal(category, value, start, end, quote):
    return Proposal(
        proposal_id=f"prop_{category.value}_{start}",
        category=category,
        value=value,
        status=ProposalStatus.PROPOSED,
        evidence=(
            EvidenceReference(
                document_id="doc_0",
                segment_index=0,
                locator={"kind": "paragraph", "paragraph": 0},
                quote=quote,
                start=start,
                end=end,
                support=Support.EXPLICIT_CLAIM,
            ),
        ),
    )


def test_two_proposals_over_the_same_text_are_ambiguous():
    _, report, _ = artifacts()
    education = next(
        claim for claim in report.claims if claim.category.value == "education"
    )
    reference = education.evidence[0]

    proposals = (
        _proposal(
            Category.EDUCATION,
            {"level": "bachelor", "field": "computer science"},
            reference.start,
            reference.end,
            reference.quote,
        ),
        _proposal(
            Category.EDUCATION,
            {"level": "bachelor", "field": "computer science"},
            reference.start,
            reference.end,
            reference.quote,
        ),
    )
    match = map_claim_to_proposals(education, proposals)

    assert match.outcome == AMBIGUOUS
    assert match.proposal_id is None
    assert len(match.candidate_proposal_ids) == 2
    assert "several proposals" in match.reason


def test_a_conflicting_attribute_is_ambiguous_and_names_the_attribute():
    _, report, _ = artifacts()
    education = next(
        claim for claim in report.claims if claim.category.value == "education"
    )
    reference = education.evidence[0]
    proposal = _proposal(
        Category.EDUCATION,
        {"level": "master", "field": "computer science"},
        reference.start,
        reference.end,
        reference.quote,
    )
    match = map_claim_to_proposals(education, (proposal,))

    assert match.outcome == AMBIGUOUS
    assert match.proposal_id is None
    assert match.conflicting_attributes == ("level",)
    assert "different normalised attributes" in match.reason


def test_evidence_that_does_not_line_up_is_never_mapped():
    _, report, _ = artifacts()
    education = next(
        claim for claim in report.claims if claim.category.value == "education"
    )
    reference = education.evidence[0]
    tampered = _proposal(
        Category.EDUCATION,
        {"level": "bachelor", "field": "computer science"},
        reference.start,
        reference.end,
        reference.quote.upper(),
    )
    match = map_claim_to_proposals(education, (tampered,))

    assert match.outcome == UNMAPPED


def test_every_claim_gets_one_outcome_and_the_mapping_is_deterministic():
    _, report, envelope = artifacts()
    first = map_claims_to_proposals(report, envelope)
    second = map_claims_to_proposals(report, envelope)

    assert len(first.matches) == len(report.claims)
    assert json.dumps(first.as_dict(), sort_keys=True) == json.dumps(
        second.as_dict(), sort_keys=True
    )
    assert {match.claim_id for match in first.matches} == {
        claim.claim_id for claim in report.claims
    }
    for match in first.matches:
        assert match.outcome in {MATCHED, AMBIGUOUS, UNMAPPED}
        if match.outcome == MATCHED:
            assert match.proposal_id
        else:
            assert match.proposal_id is None


def test_the_mapping_payload_has_the_documented_shape():
    _, report, envelope = artifacts()
    payload = map_claims_to_proposals(report, envelope).as_dict()

    assert set(payload) == {
        "mapping_schema_version",
        "reconciliation_schema_version",
        "profile_schema_version",
        "counts",
        "matches",
    }
    assert payload["reconciliation_schema_version"] == "0.1"
    assert payload["profile_schema_version"] == "0.1"
    assert set(payload["counts"]) == {MATCHED, AMBIGUOUS, UNMAPPED}
    assert sum(payload["counts"].values()) == len(report.claims)
    assert set(payload["matches"][0]) == {
        "claim_id",
        "claim_category",
        "outcome",
        "proposal_id",
        "proposal_category",
        "span_relation",
        "compatible_attributes",
        "conflicting_attributes",
        "candidate_proposal_ids",
        "claim_support",
        "proposal_support",
        "reason",
    }


def test_the_reverse_lookup_lists_the_claims_of_a_proposal():
    _, report, envelope = artifacts()
    mapping = map_claims_to_proposals(report, envelope)
    project = matches_of(mapping, "project")[0]

    claim_ids = mapping.for_proposal(project.proposal_id)
    assert project.claim_id in claim_ids
    assert len(claim_ids) == 3  # the project, its technology and its achievement
    assert set(claim_ids) <= {match.claim_id for match in mapping.by_outcome(MATCHED)}


def test_the_mapping_never_changes_the_artifacts():
    _, report, envelope = artifacts()
    before = report.as_dict()
    proposals_before = envelope.as_dict()

    map_claims_to_proposals(report, envelope)

    assert report.as_dict() == before
    assert envelope.as_dict() == proposals_before
