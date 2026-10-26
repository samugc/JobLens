"""A synthetic multi-document conflict benchmark for the reconciliation layer.

Every document is written by hand. No real CV, name, employer or personal
information is used. The benchmark covers the positive cases, the negative
cases that must not be reported as conflicts, and the cases that must stay
unresolved.
"""
from __future__ import annotations

import json

import pytest
from profile_fixtures import make_document, make_response

from joblens_public.reconcile import (
    ClaimCategory,
    Relation,
    Resolution,
    reconcile_documents,
)

CEFR_LEVELS = ("a1", "a2", "b1", "b2", "c1", "c2")


def reconcile(*texts: str, job_id: str = "job_benchmark"):
    documents = [
        make_document(f"doc_{index}", text, index=index)
        for index, text in enumerate(texts)
    ]
    return reconcile_documents(make_response(documents, job_id=job_id))


def claims_of(report, category: str, subject: str | None = None):
    return [
        claim
        for claim in report.claims
        if claim.category.value == category
        and (subject is None or claim.subject == subject)
    ]


def relation_for(report, left, right):
    left_claim, right_claim = left, right
    for relationship in report.relationships:
        if {relationship.left_claim_id, relationship.right_claim_id} == {
            left_claim.claim_id,
            right_claim.claim_id,
        }:
            return relationship
    return None


def decision_for(report, category: str, subject: str):
    for decision in report.decisions:
        if decision.category.value == category and decision.subject == subject:
            return decision
    return None


# ---------------------------------------------------------------------------
# Languages: every CEFR pair
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("left_level", CEFR_LEVELS)
@pytest.mark.parametrize("right_level", CEFR_LEVELS)
def test_every_cefr_pair_is_reconciled(left_level, right_level):
    first = f"Languages\nEnglish ({left_level.upper()})\n"
    second = f"Languages\nEnglish ({right_level.upper()})\n"
    report = reconcile(first, second)

    languages = claims_of(report, "language", "english")
    assert len(languages) == 2

    relationship = relation_for(report, languages[0], languages[1])
    if left_level == right_level:
        assert relationship.relation is Relation.DUPLICATE
        decision = decision_for(report, "language", "english")
        assert decision.outcome is Resolution.AUTO_CONSOLIDATE
        assert decision.requires_user_confirmation is False
        assert len(report.consolidated) == 1
        assert len(report.consolidated[0].evidence) == 2
    else:
        assert relationship.relation is Relation.POTENTIALLY_CONFLICTING
        decision = decision_for(report, "language", "english")
        assert decision.outcome is Resolution.RECOMMEND
        assert decision.requires_user_confirmation is True
        assert len(decision.keep_claim_ids) == 1
        kept = report.claim(decision.keep_claim_ids[0])
        assert kept.attribute_value("proficiency") == max(
            left_level, right_level, key=CEFR_LEVELS.index
        )
        # the higher level is only ever recommended, never consolidated
        assert not report.consolidated


def test_a_language_level_that_is_not_cefr_is_never_compared():
    report = reconcile(
        "Languages\nEnglish (native)\n",
        "Languages\nEnglish (C1)\n",
    )
    languages = claims_of(report, "language", "english")
    relationship = relation_for(report, languages[0], languages[1])

    assert relationship.relation is Relation.POTENTIALLY_CONFLICTING
    decision = decision_for(report, "language", "english")
    assert decision.outcome is Resolution.UNRESOLVED
    assert decision.requires_user_confirmation is True


def test_three_conflicting_sources_stay_reviewable():
    report = reconcile(
        "Languages\nEnglish (C1)\n",
        "Languages\nEnglish (B2)\n",
        "Languages\nEnglish (A1)\n",
    )
    languages = claims_of(report, "language", "english")
    assert len(languages) == 3
    for index, left in enumerate(languages):
        for right in languages[index + 1:]:
            assert relation_for(report, left, right).relation is (
                Relation.POTENTIALLY_CONFLICTING
            )
    decision = decision_for(report, "language", "english")
    assert decision.outcome is Resolution.RECOMMEND
    assert decision.requires_user_confirmation is True
    assert not report.consolidated


# ---------------------------------------------------------------------------
# Employment
# ---------------------------------------------------------------------------


def test_the_same_position_in_two_documents_is_merged():
    report = reconcile(
        "Experience\nData Engineer | Acme Corporation | 2019-2022\n",
        "Experience\nData Engineer | Acme Corporation | 2019-2022\n",
    )
    employment = claims_of(report, "employment", "data engineer")
    assert len(employment) == 2
    assert relation_for(report, employment[0], employment[1]).relation is Relation.DUPLICATE
    decision = decision_for(report, "employment", "data engineer")
    assert decision.outcome is Resolution.AUTO_CONSOLIDATE
    consolidated = [
        item for item in report.consolidated if item.category is ClaimCategory.EMPLOYMENT
    ]
    assert len(consolidated) == 1
    assert len(consolidated[0].evidence) == 2


def test_sequential_positions_are_a_progression_not_a_contradiction():
    report = reconcile(
        "Experience\nData Engineer | Acme Corporation | 2016-2019\n",
        "Experience\nData Engineer | Acme Corporation | 2019-2022\n",
    )
    employment = claims_of(report, "employment", "data engineer")
    relationship = relation_for(report, employment[0], employment[1])
    assert relationship.relation is Relation.TEMPORAL_UPDATE
    decision = decision_for(report, "employment", "data engineer")
    assert decision.outcome is Resolution.RECOMMEND
    assert decision.requires_user_confirmation is True


def test_concurrent_positions_for_the_same_role_stay_unresolved():
    report = reconcile(
        "Experience\nData Engineer | Acme Corporation | 2019-2022\n",
        "Experience\nData Engineer | Acme Corporation | 2020-2023\n",
    )
    employment = claims_of(report, "employment", "data engineer")
    assert relation_for(report, employment[0], employment[1]).relation is (
        Relation.POTENTIALLY_CONFLICTING
    )
    decision = decision_for(report, "employment", "data engineer")
    assert decision.outcome is Resolution.UNRESOLVED


def test_different_job_titles_for_the_same_role_are_a_progression():
    report = reconcile(
        "Experience\nData Engineer | Acme Corporation | 2016-2019\n",
        "Experience\nSenior Data Engineer | Acme Corporation | 2019-2022\n",
    )
    employment = claims_of(report, "employment", "data engineer")
    assert len(employment) == 2
    relationship = relation_for(report, employment[0], employment[1])
    assert relationship.relation is Relation.TEMPORAL_UPDATE


def test_the_same_role_at_different_organisations_is_not_a_conflict():
    report = reconcile(
        "Experience\nData Engineer | Acme Corporation | 2019-2022\n",
        "Experience\nData Engineer | Globex Industries | 2019-2022\n",
    )
    employment = claims_of(report, "employment", "data engineer")
    assert len(employment) == 2
    # two different positions: no relationship is reported and no decision is made
    assert relation_for(report, employment[0], employment[1]) is None
    assert decision_for(report, "employment", "data engineer") is None


def test_similar_organisation_names_leave_the_identity_uncertain():
    report = reconcile(
        "Experience\nData Engineer | Acme | 2019-2022\n",
        "Experience\nData Engineer | Acme Corporation | 2019-2022\n",
    )
    employment = claims_of(report, "employment", "data engineer")
    relationship = relation_for(report, employment[0], employment[1])
    assert relationship.relation is Relation.UNCERTAIN
    decision = decision_for(report, "employment", "data engineer")
    assert decision.outcome is Resolution.UNRESOLVED


def test_a_missing_date_is_not_a_contradiction():
    report = reconcile(
        "Experience\nData Engineer | Acme Corporation | 2019-2022\n",
        "Experience\nData Engineer | Acme Corporation\n",
    )
    employment = claims_of(report, "employment", "data engineer")
    relationship = relation_for(report, employment[0], employment[1])
    assert relationship.relation is not Relation.POTENTIALLY_CONFLICTING
    assert relationship.relation is not Relation.CONTRADICTORY


def test_a_stated_duration_that_contradicts_the_dates_is_flagged():
    report = reconcile(
        "Experience\nData Engineer | Acme Corporation | 2018-2020, 5 years\n",
        "Experience\nData Engineer | Acme Corporation | 2018-2020\n",
    )
    employment = claims_of(report, "employment", "data engineer")
    relationship = relation_for(report, employment[0], employment[1])
    assert relationship.relation is Relation.CONTRADICTORY
    decision = decision_for(report, "employment", "data engineer")
    assert decision.outcome is Resolution.UNRESOLVED


def test_a_claim_that_contradicts_itself_is_reported_as_a_warning():
    report = reconcile("Experience\nData Engineer | Acme Corporation | 2018-2020, 5 years\n")
    assert any("duration" in warning for warning in report.warnings)


def test_contradictory_chronology_is_unresolved():
    report = reconcile(
        "Experience\nData Engineer | Acme Corporation | 2020-2023\n",
        "Experience\nData Engineer | Acme Corporation | 2018-2021\n",
    )
    employment = claims_of(report, "employment", "data engineer")
    assert relation_for(report, employment[0], employment[1]).relation is (
        Relation.POTENTIALLY_CONFLICTING
    )
    assert decision_for(report, "employment", "data engineer").outcome is (
        Resolution.UNRESOLVED
    )


# ---------------------------------------------------------------------------
# Education
# ---------------------------------------------------------------------------


def test_compatible_education_dates_are_merged():
    report = reconcile(
        "Education\nBSc in Computer Science, University of Manchester (2016-2019)\n",
        "Education\nBSc in Computer Science, University of Manchester (2016-2019)\n",
    )
    education = claims_of(report, "education", "computer science")
    assert relation_for(report, education[0], education[1]).relation is Relation.DUPLICATE
    assert decision_for(report, "education", "computer science").outcome is (
        Resolution.AUTO_CONSOLIDATE
    )


def test_conflicting_education_dates_stay_unresolved():
    report = reconcile(
        "Education\nBSc in Computer Science, University of Manchester (2016-2019)\n",
        "Education\nBSc in Computer Science, University of Manchester (2017-2020)\n",
    )
    education = claims_of(report, "education", "computer science")
    assert relation_for(report, education[0], education[1]).relation is (
        Relation.POTENTIALLY_CONFLICTING
    )
    assert decision_for(report, "education", "computer science").outcome is (
        Resolution.UNRESOLVED
    )


def test_a_bachelor_and_a_master_are_a_progression():
    report = reconcile(
        "Education\nBSc in Computer Science, University of Manchester (2016-2019)\n",
        "Education\nMSc in Computer Science, University of Manchester (2019-2021)\n",
    )
    education = claims_of(report, "education", "computer science")
    relationship = relation_for(report, education[0], education[1])
    assert relationship.relation is Relation.TEMPORAL_UPDATE
    decision = decision_for(report, "education", "computer science")
    assert decision.outcome is Resolution.RECOMMEND
    assert decision.requires_user_confirmation is True


def test_a_graduation_year_outside_the_period_is_contradictory():
    report = reconcile(
        "Education\nBSc in Computer Science, University of Manchester (2016-2019)\n",
        "Summary\nGraduated in 2021\n",
    )
    graduation = claims_of(report, "education", "graduation")
    education = claims_of(report, "education", "computer science")
    assert len(graduation) == 1
    relationship = relation_for(report, graduation[0], education[0])
    assert relationship.relation is Relation.CONTRADICTORY


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


def test_equivalent_project_responsibilities_are_merged():
    report = reconcile(
        "Projects\nLedger - built the ingestion pipeline\n",
        "Projects\nLedger - built the ingestion pipeline\n",
    )
    contributions = claims_of(report, "contribution", "ledger")
    assert len(contributions) == 2
    assert relation_for(report, contributions[0], contributions[1]).relation is (
        Relation.DUPLICATE
    )
    assert decision_for(report, "contribution", "ledger").outcome is Resolution.AUTO_CONSOLIDATE


def test_contradictory_project_responsibilities_are_unresolved():
    report = reconcile(
        "Projects\nLedger - migrated the billing service to Postgres\n",
        "Projects\nLedger - migrated the billing service to MySQL\n",
    )
    obligations = claims_of(report, "contribution", "ledger")
    assert len(obligations) == 2
    assert relation_for(report, obligations[0], obligations[1]).relation is (
        Relation.CONTRADICTORY
    )
    assert decision_for(report, "contribution", "ledger").outcome is Resolution.UNRESOLVED


def test_contradictory_project_metrics_are_unresolved():
    report = reconcile(
        "Projects\nLedger - reduced the processing time by 40%\n",
        "Projects\nLedger - reduced the processing time by 10%\n",
    )
    achievements = claims_of(report, "achievement", "ledger")
    assert len(achievements) == 2
    assert relation_for(report, achievements[0], achievements[1]).relation is (
        Relation.CONTRADICTORY
    )


def test_complementary_technology_lists_are_not_a_conflict():
    report = reconcile(
        "Projects\nLedger - a Django application for small shops\n",
        "Projects\nLedger - a Django application for small shops with a React frontend\n",
    )
    projects = claims_of(report, "project", "ledger")
    assert len(projects) == 2
    relationship = relation_for(report, projects[0], projects[1])
    assert relationship.relation in (Relation.COMPLEMENTARY, Relation.MORE_SPECIFIC)
    assert relationship.relation is not Relation.CONTRADICTORY
    decision = decision_for(report, "project", "ledger")
    assert decision is None or decision.outcome is not Resolution.UNRESOLVED


def test_a_contradiction_inside_one_document_is_found():
    report = reconcile(
        "Projects\nLedger - migrated the billing service to Postgres\n"
        "Ledger - migrated the billing service to MySQL\n"
    )
    obligations = claims_of(report, "contribution", "ledger")
    assert len(obligations) == 2
    assert relation_for(report, obligations[0], obligations[1]).relation is (
        Relation.CONTRADICTORY
    )


# ---------------------------------------------------------------------------
# Cross category reasoning
# ---------------------------------------------------------------------------


def test_a_certification_supports_a_skill_mention():
    report = reconcile(
        "Skills\nAWS\n",
        "Certifications\nAWS Certified Solutions Architect\n",
    )
    skill = claims_of(report, "skill", "aws")[0]
    certification = claims_of(report, "certification")[0]
    relationship = relation_for(report, skill, certification)
    assert relationship.relation is Relation.COMPLEMENTARY
    assert relationship.basis == "cross_category"


def test_a_project_technology_supports_a_skill_claim():
    report = reconcile(
        "Skills\nDjango\n",
        "Projects\nLedger - a Django application for small shops\n",
    )
    skill = claims_of(report, "skill", "django")[0]
    technology = claims_of(report, "technology", "django")[0]
    assert relation_for(report, skill, technology).relation is Relation.COMPLEMENTARY


def test_a_position_and_its_organisation_are_complementary():
    report = reconcile("Experience\nData Engineer | Acme Corporation | 2019-2022\n")
    employment = claims_of(report, "employment", "data engineer")[0]
    organization = claims_of(report, "organization", "acme corporation")[0]
    assert relation_for(report, employment, organization).relation is Relation.COMPLEMENTARY


def test_a_responsibility_that_names_the_role_supports_the_position():
    report = reconcile(
        "Experience\nData Engineer | Acme Corporation | 2019-2022\n",
        "Projects\nLedger - led the platform as a data engineer for small shops\n",
    )
    employment = claims_of(report, "employment", "data engineer")[0]
    contributions = claims_of(report, "contribution", "ledger")
    assert contributions
    relationship = relation_for(report, employment, contributions[0])
    assert relationship.relation is Relation.COMPLEMENTARY
    assert relationship.basis == "cross_category"


def test_two_sources_that_agree_on_a_duration_do_not_conflict():
    report = reconcile(
        "Experience\nData Engineer | Acme Corporation | 2018-2020, 5 years\n",
        "Experience\nData Engineer | Acme Corporation | 2018-2020, 5 years\n",
    )
    employment = claims_of(report, "employment", "data engineer")
    assert len(employment) == 2
    relationship = relation_for(report, employment[0], employment[1])
    assert relationship.relation is not Relation.CONTRADICTORY
    # the inconsistency of the two claims with their own dates is reported apart
    assert any("duration" in warning for warning in report.warnings)


def test_the_absence_of_a_skill_in_another_document_is_not_a_conflict():
    report = reconcile(
        "Skills\nPython\nSQL\n",
        "Skills\nPython\n",
    )
    python = claims_of(report, "skill", "python")
    assert len(python) == 2
    assert relation_for(report, python[0], python[1]).relation is Relation.DUPLICATE
    sql = claims_of(report, "skill", "sql")
    assert len(sql) == 1


# ---------------------------------------------------------------------------
# Evidence and invariants
# ---------------------------------------------------------------------------


def test_every_claim_keeps_an_exact_evidence_span():
    text = "Skills\nPython, SQL\n\nExperience\nData Engineer | Acme Corporation | 2019-2022\n"
    report = reconcile(text)
    document = make_document("doc_0", text)
    segment = document["segments"][0]["text"]

    assert report.claims
    for claim in report.claims:
        for reference in claim.evidence:
            assert segment[reference.start:reference.end] == reference.quote
            assert reference.quote
            assert reference.document_id == "doc_0"


def test_unicode_evidence_is_preserved_exactly():
    text = "Skills\nPython\n\nProjects\nCafé Ünicode — a Django application for small shops\n"
    report = reconcile(text)
    projects = claims_of(report, "project")
    assert len(projects) == 1
    reference = projects[0].evidence[0]
    assert "Café Ünicode" in reference.quote
    assert reference.quote == reference.quote


def test_the_report_is_deterministic_and_serialisable():
    text = "Skills\nPython\n\nLanguages\nEnglish (C1)\n"
    first = reconcile(text, text)
    second = reconcile(text, text)
    assert json.dumps(first.as_dict(), sort_keys=True) == json.dumps(
        second.as_dict(), sort_keys=True
    )
    assert set(first.as_dict()) == {
        "reconciliation_schema_version",
        "parser_schema_version",
        "profile_schema_version",
        "job_id",
        "documents",
        "claims",
        "relationships",
        "decisions",
        "consolidated",
        "warnings",
    }


def test_a_consolidated_claim_keeps_every_source():
    report = reconcile(
        "Skills\nPython\n",
        "Skills\nPython\n",
        "Skills\nPython\n",
    )
    assert len(report.consolidated) == 1
    consolidated = report.consolidated[0]
    assert len(consolidated.evidence) == 3
    assert len(consolidated.claim_ids) == 3


def test_claims_from_an_unusable_document_are_skipped():
    document = make_document("doc_scanned", "", status="scanned_pdf")
    report = reconcile_documents(make_response([document]))
    assert report.claims == ()
    assert report.warnings


def test_the_claim_categories_cover_the_claim_kinds():
    text = (
        "Skills\nPython\n\n"
        "Experience\nData Engineer | Acme Corporation | 2019-2022\n\n"
        "Education\nBSc in Computer Science, University of Manchester (2016-2019)\n\n"
        "Projects\nLedger - a Django application that reduced costs by 30%\n\n"
        "Certifications\nAWS Certified Solutions Architect\n\n"
        "Languages\nEnglish (C1)\n"
    )
    report = reconcile(text)
    categories = {claim.category for claim in report.claims}
    assert ClaimCategory.SKILL in categories
    assert ClaimCategory.EMPLOYMENT in categories
    assert ClaimCategory.ORGANIZATION in categories
    assert ClaimCategory.EDUCATION in categories
    assert ClaimCategory.INSTITUTION in categories
    assert ClaimCategory.DEGREE in categories
    assert ClaimCategory.PROJECT in categories
    assert ClaimCategory.TECHNOLOGY in categories
    assert ClaimCategory.ACHIEVEMENT in categories
    assert ClaimCategory.LANGUAGE in categories
    assert ClaimCategory.CERTIFICATION in categories
