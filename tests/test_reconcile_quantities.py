"""P0 regressions: ``quantities`` holds only genuine numeric quantities.

A technology is a technology and a measurement is a measurement. The engine
must never present ``python`` or ``javascript`` as a quantity, must never
invent a measurement that the source does not state, and must only call a
statement an achievement when it carries a real figure.

Every document is synthetic.
"""
from __future__ import annotations

import re

import pytest
from profile_fixtures import make_document, make_response

from joblens_public.reconcile import ClaimCategory, reconcile_documents

#: The shape of a genuine quantity the extractor may produce.
_QUANTITY = re.compile(
    r"\d[\d,.]*(?:\s?(?:%|percent|percentage points?|k|m|bn|x))?", re.IGNORECASE
)


def reconcile(*texts: str):
    documents = [
        make_document(f"doc_{index}", text, index=index)
        for index, text in enumerate(texts)
    ]
    return reconcile_documents(make_response(documents, job_id="job_quantities"))


def claim_of(report, category: ClaimCategory, subject: str):
    for claim in report.claims:
        if claim.category is category and claim.subject == subject:
            return claim
    raise AssertionError(f"no {category.value} claim for {subject!r}")


def responsibility(report, subject: str):
    for claim in report.claims:
        if claim.category in {ClaimCategory.CONTRIBUTION, ClaimCategory.ACHIEVEMENT}:
            if claim.subject == subject:
                return claim
    raise AssertionError(f"no responsibility claim for {subject!r}")


@pytest.mark.parametrize(
    ("statement", "technology"),
    [
        ("Built a Python API", "python"),
        ("Built a JavaScript API", "javascript"),
        ("Built a Python API with a SQL backend", "python"),
    ],
)
def test_a_technology_is_never_a_quantity(statement, technology):
    report = reconcile(f"Projects\nLedger - {statement}\n")
    claim = responsibility(report, "ledger")

    assert claim.category is ClaimCategory.CONTRIBUTION
    assert claim.attribute("quantities") is None
    assert claim.attribute("technologies") == technology


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ("Reduced latency by 35%", "35%"),
        ("Managed 5 engineers", "5"),
        ("Processed 1,000 documents", "1,000"),
        ("Reduced latency by 40 percent", "40 percent"),
    ],
)
def test_a_real_measurement_is_an_achievement(statement, expected):
    report = reconcile(f"Projects\nLedger - {statement}\n")
    claim = responsibility(report, "ledger")

    assert claim.category is ClaimCategory.ACHIEVEMENT
    assert claim.attribute("quantities") == expected


def test_a_statement_with_a_figure_and_a_technology_keeps_them_apart():
    report = reconcile("Projects\nLedger - Reduced latency by 35% using Postgres\n")
    claim = responsibility(report, "ledger")

    assert claim.category is ClaimCategory.ACHIEVEMENT
    assert claim.attribute("quantities") == "35%"
    assert claim.attribute("technologies") == "postgresql"
    assert claim.attribute("template") == "reduced latency by # using #"


def test_a_technology_only_statement_has_no_quantity_attribute():
    report = reconcile("Projects\nLedger - Automated the release pipeline using Docker\n")
    claim = responsibility(report, "ledger")

    assert claim.category is ClaimCategory.CONTRIBUTION
    assert claim.attribute("quantities") is None
    assert claim.attribute("technologies") == "docker"


def test_no_quantities_attribute_ever_holds_a_word():
    text = (
        "Projects\n"
        "Ledger - built a Python API with a JavaScript client and a SQL backend\n"
        "Ledger - reduced the processing time by 40%\n"
        "Ledger - migrated the billing service to Postgres\n"
        "Ledger - processed 1,000 documents\n\n"
        "Skills\nPython, JavaScript, SQL\n"
    )
    report = reconcile(text)

    for claim in report.claims:
        quantities = claim.attribute("quantities")
        if quantities is None:
            continue
        assert claim.category in {
            ClaimCategory.ACHIEVEMENT,
        }
        for value in quantities.split(", "):
            assert _QUANTITY.fullmatch(value), value


def test_a_technology_is_still_reported_as_a_technology():
    report = reconcile("Projects\nLedger - Built a Python API\n")

    technology = claim_of(report, ClaimCategory.TECHNOLOGY, "python")
    assert technology.attribute("project") == "ledger"


def test_two_technologies_in_one_template_are_a_contradiction():
    report = reconcile(
        "Projects\nLedger - Built a Python API\n",
        "Projects\nLedger - Built a JavaScript API\n",
    )
    responsibilities = [
        claim
        for claim in report.claims
        if claim.category is ClaimCategory.CONTRIBUTION and claim.subject == "ledger"
    ]
    assert len(responsibilities) == 2
    relationship = next(
        item
        for item in report.relationships
        if {item.left_claim_id, item.right_claim_id}
        == {responsibilities[0].claim_id, responsibilities[1].claim_id}
    )
    assert relationship.relation.value == "contradictory"
    assert "technologies" in relationship.attributes
    assert "quantities" not in relationship.attributes


def source_of(response, reference):
    for document in response["documents"]:
        if document["document_id"] == reference.document_id:
            return document["segments"][reference.segment_index]["text"]
    raise AssertionError("document not found")


def test_a_technology_alias_is_reported_with_its_exact_quote():
    text = "Projects\nLedger - migrated the billing service to Postgres\n"
    documents = [make_document("doc_0", text, index=0)]
    response = make_response(documents, job_id="job_quantities")
    report = reconcile_documents(response)

    technology = claim_of(report, ClaimCategory.TECHNOLOGY, "postgresql")
    reference = technology.evidence[0]
    assert reference.quote == "Postgres"
    assert source_of(response, reference)[reference.start:reference.end] == "Postgres"


def test_a_technology_span_is_exact_with_trailing_whitespace():
    text = "Projects\nLedger - a Django application   \n"
    documents = [make_document("doc_0", text, index=0)]
    response = make_response(documents, job_id="job_quantities")
    report = reconcile_documents(response)

    technology = claim_of(report, ClaimCategory.TECHNOLOGY, "django")
    reference = technology.evidence[0]
    assert reference.quote == "Django"
    assert source_of(response, reference)[reference.start:reference.end] == "Django"


def test_a_responsibility_span_is_exact_with_trailing_whitespace():
    text = "Projects\nLedger - reduced latency by 35%   \n"
    documents = [make_document("doc_0", text, index=0)]
    response = make_response(documents, job_id="job_quantities")
    report = reconcile_documents(response)

    claim = responsibility(report, "ledger")
    reference = claim.evidence[0]
    assert reference.quote == "reduced latency by 35%"
    assert source_of(response, reference)[reference.start:reference.end] == reference.quote
