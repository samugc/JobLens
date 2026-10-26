"""Tests for the evidence-grounded candidate profile proposal engine."""
from __future__ import annotations

import json
import re

import pytest
from profile_fixtures import (
    CERTIFICATIONS_SECTION,
    EDUCATION_SECTION,
    LANGUAGES_SECTION,
    PROJECTS_SECTION,
    SKILLS_SECTION,
    full_cv,
    make_document,
    make_response,
    make_segment,
)

from joblens_public.profile import (
    Category,
    ProfileError,
    Support,
    build_profile_proposals,
)

PROPOSAL_ID_PATTERN = re.compile(r"^prop_[0-9a-f]{16}$")
CONFLICT_ID_PATTERN = re.compile(r"^conf_[0-9a-f]{16}$")


def proposals_of(envelope, category: str) -> list:
    return [item for item in envelope.proposals if item.category.value == category]


def value_for(envelope, category: str, **fields) -> dict:
    for proposal in proposals_of(envelope, category):
        if all(proposal.value.get(key) == value for key, value in fields.items()):
            return proposal.value
    raise AssertionError(f"no {category} proposal with {fields}")


def test_empty_input_produces_an_empty_envelope():
    envelope = build_profile_proposals(make_response([]))

    assert envelope.profile_schema_version == "0.1"
    assert envelope.parser_schema_version == "1.1"
    assert envelope.documents == ()
    assert envelope.proposals == ()
    assert envelope.conflicts == ()
    assert json.loads(json.dumps(envelope.as_dict()))["proposals"] == []


def test_document_without_text_produces_no_proposals():
    document = make_document("doc_empty", "", segments=[])
    envelope = build_profile_proposals(make_response([document]))

    assert envelope.proposals == ()
    assert len(envelope.documents) == 1


def test_every_quote_span_matches_the_source_segment():
    document = make_document("doc_spans", full_cv())
    response = make_response([document])
    envelope = build_profile_proposals(response)
    source = response["documents"][0]["segments"]

    assert envelope.proposals
    for proposal in envelope.proposals:
        for reference in proposal.evidence:
            segment = source[reference.segment_index]
            assert segment["text"][reference.start:reference.end] == reference.quote
            assert reference.quote
            assert reference.quote in segment["text"]


def test_skills_section_produces_explicit_claims():
    document = make_document("doc_skills", SKILLS_SECTION)
    envelope = build_profile_proposals(make_response([document]))

    skills = {item.value["name"]: item for item in proposals_of(envelope, "skill")}
    assert set(skills) == {"python", "sql", "docker", "kubernetes"}
    for proposal in skills.values():
        assert proposal.evidence[0].support is Support.EXPLICIT_CLAIM
        assert proposal.status.value == "proposed"


def test_free_text_mention_is_a_keyword_mention():
    document = make_document("doc_free", "The team ships Python services every day.\n")
    envelope = build_profile_proposals(make_response([document]))

    skill = value_for(envelope, "skill", name="python")
    assert skill == {"name": "python"}
    proposal = proposals_of(envelope, "skill")[0]
    assert proposal.evidence[0].support is Support.KEYWORD_MENTION


def test_explicit_marker_turns_a_mention_into_a_claim():
    document = make_document(
        "doc_marker",
        "I have experience with Python and SQL in production systems.\n",
    )
    envelope = build_profile_proposals(make_response([document]))

    supports = {
        proposal.value["name"]: proposal.evidence[0].support
        for proposal in proposals_of(envelope, "skill")
    }
    assert supports["python"] is Support.EXPLICIT_CLAIM
    assert supports["sql"] is Support.EXPLICIT_CLAIM


def test_ambiguous_skill_is_ignored_in_free_text_but_kept_in_a_skills_section():
    free = make_document("doc_rust", "The project was written in Rust and shipped fast.\n")
    envelope = build_profile_proposals(make_response([free]))
    assert proposals_of(envelope, "skill") == []

    listed = make_document("doc_rust2", SKILLS_SECTION + "Rust\n")
    envelope = build_profile_proposals(make_response([listed]))
    assert value_for(envelope, "skill", name="rust") == {"name": "rust"}


def test_an_unambiguous_surface_form_is_kept_in_free_text():
    document = make_document("doc_ts", "The service is written in TypeScript today.\n")
    envelope = build_profile_proposals(make_response([document]))

    assert value_for(envelope, "skill", name="typescript") == {"name": "typescript"}
    assert proposals_of(envelope, "skill")[0].evidence[0].support is Support.KEYWORD_MENTION


def test_education_requires_an_explicit_degree_statement():
    document = make_document(
        "doc_education",
        "I studied computer science and enjoyed the coursework.\n",
    )
    envelope = build_profile_proposals(make_response([document]))
    assert proposals_of(envelope, "education") == []

    document = make_document("doc_education2", EDUCATION_SECTION)
    envelope = build_profile_proposals(make_response([document]))
    education = proposals_of(envelope, "education")
    assert {item.value["level"] for item in education} == {"bachelor", "master"}
    assert value_for(envelope, "education", level="bachelor") == {
        "level": "bachelor",
        "field": "computer science",
    }
    assert value_for(envelope, "education", level="master") == {
        "level": "master",
        "field": "data science",
    }


def test_no_years_dates_or_employers_are_proposed():
    document = make_document(
        "doc_dates",
        "Experience\nSenior Data Engineer | Acme Corporation | 2020-2023\n",
    )
    envelope = build_profile_proposals(make_response([document]))

    experience = proposals_of(envelope, "experience")
    assert len(experience) == 1
    assert experience[0].value == {"role": "senior data engineer"}
    serialized = json.dumps(envelope.as_dict())
    assert "acme" not in serialized
    assert "2020" not in serialized
    assert "2023" not in serialized
    assert "years" not in serialized


def test_a_job_title_is_not_read_as_a_degree():
    document = make_document(
        "doc_master",
        "Experience\nMaster Data Manager | Acme Corporation | 2020-2023\n",
    )
    envelope = build_profile_proposals(make_response([document]))

    assert proposals_of(envelope, "education") == []
    assert value_for(envelope, "experience", role="master data manager") == {
        "role": "master data manager"
    }


def test_a_degree_earned_in_a_sentence_is_an_explicit_claim():
    document = make_document(
        "doc_earned",
        "I earned a BSc in Computer Science and finished a MSc in Data Science.\n",
    )
    envelope = build_profile_proposals(make_response([document]))

    education = proposals_of(envelope, "education")
    assert {item.value["level"] for item in education} == {"bachelor", "master"}


def test_a_degree_mention_without_a_claim_is_not_proposed():
    document = make_document(
        "doc_mention",
        "The BSc in Computer Science programme admits forty students a year.\n",
    )
    envelope = build_profile_proposals(make_response([document]))
    assert proposals_of(envelope, "education") == []


def test_experience_requires_a_role_title():
    document = make_document("doc_role", "Experience\nAcme Corporation | 2020-2023\n")
    envelope = build_profile_proposals(make_response([document]))
    assert proposals_of(envelope, "experience") == []


def test_languages_record_the_stated_level_without_interpreting_it():
    document = make_document("doc_languages", LANGUAGES_SECTION)
    envelope = build_profile_proposals(make_response([document]))

    assert value_for(envelope, "language", language="english") == {
        "language": "english",
        "stated_level": "c1",
    }
    assert value_for(envelope, "language", language="spanish") == {
        "language": "spanish",
        "stated_level": "b2",
    }


def test_projects_and_certifications_are_proposed():
    document = make_document(
        "doc_sections",
        "\n".join([PROJECTS_SECTION.rstrip("\n"), CERTIFICATIONS_SECTION.rstrip("\n")]),
    )
    envelope = build_profile_proposals(make_response([document]))

    assert value_for(envelope, "project", name="cv evidence workspace") == {
        "name": "cv evidence workspace"
    }
    assert value_for(envelope, "certification", name="aws certified solutions architect") == {
        "name": "aws certified solutions architect"
    }


def test_duplicates_across_documents_are_grouped_and_keep_every_reference():
    first = make_document("doc_one", SKILLS_SECTION, index=0)
    second = make_document("doc_two", "Skills\nPython and SQL\n", index=1)
    envelope = build_profile_proposals(make_response([first, second]))

    python = [
        proposal
        for proposal in proposals_of(envelope, "skill")
        if proposal.value["name"] == "python"
    ]
    assert len(python) == 1
    evidence = python[0].evidence
    assert len(evidence) == 2
    assert {reference.document_id for reference in evidence} == {"doc_one", "doc_two"}
    assert all(reference.support is Support.EXPLICIT_CLAIM for reference in evidence)


def test_more_than_five_documents_are_rejected():
    documents = [
        make_document(f"doc_{index}", SKILLS_SECTION, index=index) for index in range(6)
    ]
    with pytest.raises(ProfileError):
        build_profile_proposals(make_response(documents))


def test_five_documents_are_supported():
    documents = [
        make_document(f"doc_{index}", SKILLS_SECTION, index=index) for index in range(5)
    ]
    envelope = build_profile_proposals(make_response(documents))

    assert len(envelope.documents) == 5
    assert len(proposals_of(envelope, "skill")) == 4


def test_conflicting_language_levels_are_reported():
    first = make_document("doc_a", "Languages\nEnglish (C1)\n", index=0)
    second = make_document("doc_b", "Languages\nEnglish (B2)\n", index=1)
    envelope = build_profile_proposals(make_response([first, second]))

    languages = proposals_of(envelope, "language")
    assert len(languages) == 2
    assert len(envelope.conflicts) == 1
    conflict = envelope.conflicts[0]
    assert conflict.kind == "conflicting_stated_level"
    assert conflict.category is Category.LANGUAGE
    assert set(conflict.proposal_ids) == {item.proposal_id for item in languages}
    for proposal in languages:
        assert conflict.conflict_id in proposal.conflicts
    assert CONFLICT_ID_PATTERN.match(conflict.conflict_id)


def test_ambiguous_document_produces_no_proposals():
    document = make_document(
        "doc_ambiguous",
        "A thoughtful person who enjoys learning and solving hard problems.\n",
    )
    envelope = build_profile_proposals(make_response([document]))
    assert envelope.proposals == ()


def test_unusable_document_status_is_skipped_with_a_warning():
    document = make_document("doc_scanned", "", status="scanned_pdf")
    envelope = build_profile_proposals(make_response([document]))

    assert envelope.proposals == ()
    assert len(envelope.documents) == 1
    assert envelope.warnings
    assert "scanned_pdf" in envelope.warnings[0]


def test_missing_document_id_is_rejected():
    document = make_document("doc_a", SKILLS_SECTION)
    del document["document_id"]
    with pytest.raises(ProfileError):
        build_profile_proposals(make_response([document]))


def test_unknown_schema_version_is_rejected():
    response = make_response([make_document("doc_a", SKILLS_SECTION)])
    response["schema_version"] = "9.9"
    with pytest.raises(ProfileError):
        build_profile_proposals(response)


def test_documents_without_segments_are_rejected():
    document = make_document("doc_a", SKILLS_SECTION)
    document["segments"] = "not-an-array"
    with pytest.raises(ProfileError):
        build_profile_proposals(make_response([document]))


def test_output_is_deterministic():
    response = make_response([make_document("doc_a", full_cv())])
    first = build_profile_proposals(response).as_dict()
    second = build_profile_proposals(response).as_dict()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_identifiers_are_opaque_and_stable():
    response = make_response([make_document("doc_a", full_cv())])
    envelope = build_profile_proposals(response)

    for proposal in envelope.proposals:
        assert PROPOSAL_ID_PATTERN.match(proposal.proposal_id)
        assert "python" not in proposal.proposal_id
        assert "synthetic" not in proposal.proposal_id
    for conflict in envelope.conflicts:
        assert CONFLICT_ID_PATTERN.match(conflict.conflict_id)


def test_documents_provenance_is_kept_by_reference():
    document = make_document("doc_a", full_cv(), filename="synthetic-cv.pdf")
    envelope = build_profile_proposals(make_response([document]))

    reference = envelope.documents[0]
    assert reference.document_id == "doc_a"
    assert reference.filename == "synthetic-cv.pdf"
    assert reference.segment_count == 1
    assert reference.text_length == len(full_cv())
    serialized = json.dumps(envelope.as_dict())
    assert full_cv() not in serialized
    assert len(envelope.documents) == 1


def test_no_contact_details_are_proposed():
    document = make_document(
        "doc_contact",
        "Contact\nreach me through the internal channel 555 0100\n",
    )
    envelope = build_profile_proposals(make_response([document]))
    assert envelope.proposals == ()


def test_segments_keep_their_own_locators():
    document = make_document(
        "doc_multi",
        "",
        segments=[
            make_segment(SKILLS_SECTION, paragraph=3),
            make_segment(PROJECTS_SECTION, paragraph=7),
        ],
    )
    envelope = build_profile_proposals(make_response([document]))

    locators = {
        reference.locator.get("paragraph")
        for proposal in envelope.proposals
        for reference in proposal.evidence
    }
    assert locators == {3, 7}
