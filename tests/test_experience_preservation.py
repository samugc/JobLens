"""Experience entries must keep every source-stated contribution.

The previous implementation attached a follow-up line only when it began with a
small hand-written verb list, and stopped at the first line that did not. A
fictional entry beginning "Increased conversion by 18%" therefore lost that
line and every line after it. These tests use the real proposal engine and the
real draft generator, never a model.
"""
from __future__ import annotations

from profile_fixtures import make_document, make_response

from joblens_public.cv import generate_cv_draft
from joblens_public.jobs import parse_job_posting
from joblens_public.profile import build_profile_proposals
from joblens_public.profile.approved import ApprovedFact, ApprovedProfile, CandidateContact
from joblens_public.profile.models import Category


def _experience(envelope):
    return [p for p in envelope.proposals if p.category is Category.EXPERIENCE]


def _profile(envelope) -> ApprovedProfile:
    facts = tuple(
        ApprovedFact(
            fact_id=proposal.proposal_id,
            category=proposal.category,
            value=proposal.value,
            evidence=proposal.evidence,
            source_document_ids=tuple(
                sorted({reference.document_id for reference in proposal.evidence})
            ),
            review_sequence=1,
        )
        for proposal in envelope.proposals
    )
    return ApprovedProfile(
        approved_profile_version="0.1",
        parser_schema_version="1.1",
        profile_schema_version="1.0",
        job_id=envelope.job_id,
        documents=envelope.documents,
        facts=facts,
        candidate=CandidateContact(full_name="Fictional Candidate"),
        review_sequence=1,
    )


def test_non_whitelisted_first_line_does_not_hide_the_rest():
    text = (
        "Experience\n"
        "Software Engineer | Fictional Cedar Labs | 2021-2024\n"
        "Increased checkout conversion by 18% by rebuilding the payment service.\n"
        "Built Python REST APIs and automated tests.\n"
    )
    envelope = build_profile_proposals(make_response([make_document("doc", text)]))
    experience = _experience(envelope)

    assert len(experience) == 1
    quotes = [reference.quote for reference in experience[0].evidence]
    assert quotes[0] == "Software Engineer | Fictional Cedar Labs | 2021-2024"
    assert "Increased checkout conversion by 18% by rebuilding the payment service." in quotes
    assert "Built Python REST APIs and automated tests." in quotes

    # Every reference is an exact slice of the segment it cites.
    segment = make_response([make_document("doc", text)])["documents"][0]["segments"][0]["text"]
    for reference in experience[0].evidence:
        assert segment[reference.start:reference.end] == reference.quote


def test_entry_stops_at_the_next_section():
    text = (
        "Experience\n"
        "Software Engineer | Fictional Cedar Labs | 2021-2024\n"
        "Automated nightly reconciliation reports.\n"
        "Education\n"
        "BSc in Computer Science.\n"
    )
    envelope = build_profile_proposals(make_response([make_document("doc", text)]))
    quotes = [reference.quote for reference in _experience(envelope)[0].evidence]

    assert "Automated nightly reconciliation reports." in quotes
    assert all("BSc" not in quote for quote in quotes)


def test_entry_stops_at_the_next_role():
    text = (
        "Experience\n"
        "Data Analyst | Fictional Harbor | 2019-2021\n"
        "Built SQL reports for operations teams.\n"
        "Software Engineer | Fictional Cedar Labs | 2021-2024\n"
        "Owned the ingestion roadmap for three regions.\n"
    )
    envelope = build_profile_proposals(make_response([make_document("doc", text)]))
    experience = _experience(envelope)

    # The proposal engine groups by role, so the roles stay separate and each
    # carries only its own contribution.
    assert {item.value["role"] for item in experience} == {
        "data analyst",
        "software engineer",
    }
    for item in experience:
        quotes = [reference.quote for reference in item.evidence]
        if item.value["role"] == "data analyst":
            assert "Built SQL reports for operations teams." in quotes
            assert all("Owned the ingestion" not in quote for quote in quotes)
        else:
            assert "Owned the ingestion roadmap for three regions." in quotes
            assert all("Built SQL reports" not in quote for quote in quotes)


def test_paragraph_segments_keep_their_contributions():
    """DOCX extraction may give every paragraph its own segment."""
    segments = [
        {"locator": {"kind": "paragraph", "paragraph": index + 1}, "text": line}
        for index, line in enumerate(
            [
                "Experience",
                "Data Analyst | Fictional Harbor | 2019-2023",
                "\u2022 Led migration of the reporting stack to PostgreSQL.",
                "\u2022 Negotiated a 12% reduction in vendor costs.",
                "Education",
                "BSc in Computer Science.",
            ]
        )
    ]
    document = make_document(
        "doc", "\n".join(segment["text"] for segment in segments), segments=segments
    )
    envelope = build_profile_proposals(make_response([document]))
    quotes = [reference.quote for reference in _experience(envelope)[0].evidence]

    assert "\u2022 Led migration of the reporting stack to PostgreSQL." in quotes
    assert "\u2022 Negotiated a 12% reduction in vendor costs." in quotes


def test_approved_draft_keeps_achievements_employer_and_dates():
    text = (
        "Candidate Example\n"
        "Skills\n"
        "Python, SQL\n"
        "Experience\n"
        "Software Engineer | Fictional Cedar Labs | 2021-2024\n"
        "Increased conversion by 18% by rebuilding the checkout service.\n"
        "Managed a team of four engineers.\n"
    )
    envelope = build_profile_proposals(make_response([make_document("doc", text)]))
    draft = generate_cv_draft(_profile(envelope), parse_job_posting("Requirements:\n- Python\n"))
    experience = next(section for section in draft.sections if section.kind == "experience")
    item = experience.items[0]

    assert item.heading == "Software Engineer"
    assert item.subheading == "Fictional Cedar Labs"
    assert item.period == "2021-2024"
    assert "Increased conversion by 18% by rebuilding the checkout service." in item.text
    assert "Managed a team of four engineers." in item.text
    assert "\u2022" not in item.text


def test_summary_does_not_turn_a_skill_into_stated_experience():
    text = (
        "Candidate Example\n"
        "Skills\n"
        "Python, SQL\n"
        "Experience\n"
        "Software Engineer | Fictional Cedar Labs | 2021-2024\n"
        "Built Python REST APIs.\n"
    )
    envelope = build_profile_proposals(make_response([make_document("doc", text)]))
    draft = generate_cv_draft(_profile(envelope), parse_job_posting("Requirements:\n- Python\n"))
    summary = next(section for section in draft.sections if section.kind == "summary")

    assert "skills in" in summary.items[0].text
    assert "experience in" not in summary.items[0].text
