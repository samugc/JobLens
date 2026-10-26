"""P1/P3 regressions: unsafe consolidation and decision semantics.

The reconciliation layer may only merge two claims when the sources state
enough identity for the merge to be safe. It must keep support qualifiers
distinct, must never promote a keyword mention to a claim, must keep every
source, and must never present a recommendation or an inference as approved.

Every document is synthetic.
"""
from __future__ import annotations

from profile_fixtures import make_document, make_response

from joblens_public.reconcile import (
    APPROVAL_STATE_NOT_APPROVED,
    ClaimCategory,
    Relation,
    Resolution,
    reconcile_documents,
)


def reconcile(*texts: str):
    documents = [
        make_document(f"doc_{index}", text, index=index)
        for index, text in enumerate(texts)
    ]
    return reconcile_documents(make_response(documents, job_id="job_safety"))


def claims_of(report, category: str, subject: str | None = None):
    return [
        claim
        for claim in report.claims
        if claim.category.value == category
        and (subject is None or claim.subject == subject)
    ]


def relation_for(report, left, right):
    for relationship in report.relationships:
        if {relationship.left_claim_id, relationship.right_claim_id} == {
            left.claim_id,
            right.claim_id,
        }:
            return relationship
    return None


def decision_for(report, category: str, subject: str):
    for decision in report.decisions:
        if decision.category.value == category and decision.subject == subject:
            return decision
    return None


# ---------------------------------------------------------------------------
# Employment identity
# ---------------------------------------------------------------------------


def test_the_same_job_title_without_employer_or_dates_is_not_merged():
    report = reconcile(
        "Experience\nData Engineer\n",
        "Experience\nData Engineer\n",
    )
    employment = claims_of(report, "employment", "data engineer")
    assert len(employment) == 2
    relationship = relation_for(report, employment[0], employment[1])
    assert relationship.relation is Relation.UNCERTAIN

    decision = decision_for(report, "employment", "data engineer")
    assert decision.outcome is Resolution.UNRESOLVED
    assert decision.requires_user_confirmation is True
    assert not report.consolidated


def test_an_employer_stated_by_one_source_only_keeps_the_identity_uncertain():
    report = reconcile(
        "Experience\nData Engineer | Acme Corporation | 2019-2022\n",
        "Experience\nData Engineer | 2019-2022\n",
    )
    employment = claims_of(report, "employment", "data engineer")
    assert relation_for(report, employment[0], employment[1]).relation is Relation.UNCERTAIN
    assert decision_for(report, "employment", "data engineer").outcome is (
        Resolution.UNRESOLVED
    )
    assert not report.consolidated


# ---------------------------------------------------------------------------
# Support qualifiers
# ---------------------------------------------------------------------------


def test_an_explicit_claim_and_a_keyword_mention_are_not_the_same_claim():
    report = reconcile(
        "Skills\nPython\n",
        "Projects\nLedger - a Python service\n",
    )
    skills = claims_of(report, "skill", "python")
    assert {claim.qualifier for claim in skills} == {
        "explicit_claim",
        "keyword_mention",
    }
    relationship = relation_for(report, skills[0], skills[1])
    assert relationship.relation is Relation.COMPLEMENTARY
    assert "qualifier" in relationship.attributes

    decision = decision_for(report, "skill", "python")
    assert decision is None
    assert not [item for item in report.consolidated if item.subject == "python"]


def test_merged_keyword_mentions_stay_keyword_mentions():
    report = reconcile(
        "Projects\nLedger - a Python service\n",
        "Projects\nLedger - a Python service\n",
    )
    consolidated = [
        item
        for item in report.consolidated
        if item.category is ClaimCategory.SKILL
    ]
    assert len(consolidated) == 1
    assert consolidated[0].qualifiers == ("keyword_mention",)


def test_a_skill_is_not_inferred_from_a_certification_title():
    report = reconcile("Certifications\nAWS Certified Solutions Architect\n")

    assert claims_of(report, "skill", "aws") == []
    certifications = claims_of(report, "certification")
    assert len(certifications) == 1
    assert not report.consolidated
    assert not report.decisions


def test_a_certification_and_a_stated_skill_stay_complementary():
    report = reconcile(
        "Certifications\nAWS Certified Solutions Architect\n",
        "Skills\nAWS\n",
    )
    skill = claims_of(report, "skill", "aws")[0]
    certification = claims_of(report, "certification")[0]
    relationship = relation_for(report, skill, certification)

    assert relationship.relation is Relation.COMPLEMENTARY
    assert decision_for(report, "skill", "aws") is None


# ---------------------------------------------------------------------------
# Education and degree identity
# ---------------------------------------------------------------------------


def test_the_same_degree_name_without_identity_is_not_merged():
    report = reconcile(
        "Education\nBSc in Computer Science\n",
        "Education\nBSc in Computer Science\n",
    )
    education = claims_of(report, "education", "computer science")
    education_relationship = relation_for(report, education[0], education[1])
    assert education_relationship.relation is Relation.UNCERTAIN

    degrees = claims_of(report, "degree", "bachelor|computer science")
    degree_relationship = relation_for(report, degrees[0], degrees[1])
    assert degree_relationship.relation is Relation.UNCERTAIN

    assert not report.consolidated
    assert decision_for(report, "education", "computer science").outcome is (
        Resolution.UNRESOLVED
    )


def test_the_same_degree_with_an_institution_is_merged():
    report = reconcile(
        "Education\nBSc in Computer Science, University of Manchester\n",
        "Education\nBSc in Computer Science, University of Manchester\n",
    )
    education = claims_of(report, "education", "computer science")
    assert relation_for(report, education[0], education[1]).relation is Relation.DUPLICATE
    assert decision_for(report, "education", "computer science").outcome is (
        Resolution.AUTO_CONSOLIDATE
    )


def test_the_same_degree_at_two_institutions_stays_unresolved():
    report = reconcile(
        "Education\nBSc in Computer Science, University of Manchester (2016-2019)\n",
        "Education\nBSc in Computer Science, University of Leeds (2016-2019)\n",
    )
    education = claims_of(report, "education", "computer science")
    relationship = relation_for(report, education[0], education[1])
    assert relationship.relation is Relation.POTENTIALLY_CONFLICTING
    assert "institution" in relationship.attributes
    assert decision_for(report, "education", "computer science").outcome is (
        Resolution.UNRESOLVED
    )


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


def test_the_same_project_name_with_different_descriptions_is_not_merged():
    report = reconcile(
        "Projects\nLedger - a Django application for small shops\n",
        "Projects\nLedger - a Flask service for large shops\n",
    )
    projects = claims_of(report, "project", "ledger")
    assert len(projects) == 2
    relationship = relation_for(report, projects[0], projects[1])
    assert relationship.relation is Relation.COMPLEMENTARY
    assert "description" in relationship.attributes

    assert decision_for(report, "project", "ledger") is None
    assert not [item for item in report.consolidated if item.subject == "ledger"]


def test_the_same_project_name_with_the_same_description_is_merged():
    report = reconcile(
        "Projects\nLedger - a Django application for small shops\n",
        "Projects\nLedger - a Django application for small shops\n",
    )
    projects = claims_of(report, "project", "ledger")
    assert relation_for(report, projects[0], projects[1]).relation is Relation.DUPLICATE
    assert decision_for(report, "project", "ledger").outcome is (
        Resolution.AUTO_CONSOLIDATE
    )


# ---------------------------------------------------------------------------
# Decision semantics (P3)
# ---------------------------------------------------------------------------


def test_a_current_position_outranks_an_ended_one():
    report = reconcile(
        "Experience\nData Engineer | Acme Corporation | 2016-2019\n",
        "Experience\nData Engineer | Acme Corporation | 2019-present\n",
    )
    decision = decision_for(report, "employment", "data engineer")
    assert decision.outcome is Resolution.RECOMMEND
    kept = report.claim(decision.keep_claim_ids[0])
    assert kept.attribute("end") == "present"


def test_the_temporal_preference_does_not_depend_on_the_document_order():
    report = reconcile(
        "Experience\nData Engineer | Acme Corporation | 2019-present\n",
        "Experience\nData Engineer | Acme Corporation | 2016-2019\n",
    )
    decision = decision_for(report, "employment", "data engineer")
    kept = report.claim(decision.keep_claim_ids[0])
    assert kept.attribute("end") == "present"


def test_a_recommendation_retains_every_other_claim():
    report = reconcile(
        "Experience\nData Engineer | Acme Corporation | 2016-2019\n",
        "Experience\nData Engineer | Acme Corporation | 2019-present\n",
    )
    decision = decision_for(report, "employment", "data engineer")

    assert decision.keep_claim_ids
    assert decision.merge_claim_ids == ()
    employment = claims_of(report, "employment", "data engineer")
    assert set(decision.alternative_claim_ids) == {
        claim.claim_id for claim in employment
    } - set(decision.keep_claim_ids)


def test_an_unresolved_decision_retains_every_claim_and_names_the_doubt():
    report = reconcile(
        "Languages\nEnglish (C1)\n",
        "Languages\nEnglish (native)\n",
    )
    decision = decision_for(report, "language", "english")

    assert decision.outcome is Resolution.UNRESOLVED
    assert decision.keep_claim_ids == ()
    assert decision.merge_claim_ids == ()
    languages = claims_of(report, "language", "english")
    assert set(decision.alternative_claim_ids) == {
        claim.claim_id for claim in languages
    }
    assert "differ" in decision.explanation


def test_a_preference_beside_an_uncertain_position_is_not_recommended():
    report = reconcile(
        "Experience\nData Engineer | Acme Corporation | 2016-2019\n",
        "Experience\nData Engineer | Acme Corporation | 2019-present\n",
        "Experience\nSenior Data Engineer | 2016-2019\n",
    )
    decision = decision_for(report, "employment", "data engineer")

    # A later period exists, but one source states the same role without an
    # employer, so the group is not a defensible preference.
    assert decision.outcome is Resolution.UNRESOLVED
    assert decision.keep_claim_ids == ()
    assert decision.merge_claim_ids == ()
    assert len(decision.alternative_claim_ids) == 3
    assert not report.consolidated


def test_only_an_automatic_consolidation_merges_claims():
    report = reconcile(
        "Skills\nPython\n",
        "Skills\nPython\n",
        "Languages\nEnglish (C1)\n",
        "Languages\nEnglish (native)\n",
    )
    assert report.decisions
    for decision in report.decisions:
        if decision.outcome is Resolution.AUTO_CONSOLIDATE:
            assert decision.merge_claim_ids
            assert decision.alternative_claim_ids == ()
            assert decision.requires_user_confirmation is False
        else:
            assert decision.merge_claim_ids == ()


def test_nothing_is_ever_approved_and_no_claim_is_dropped():
    report = reconcile(
        "Skills\nPython\n\nProjects\nLedger - Built a Python API\n",
        "Skills\nPython\n\nProjects\nLedger - Built a JavaScript API\n",
        "Experience\nData Engineer | Acme Corporation | 2016-2019\n",
        "Experience\nData Engineer | Acme Corporation | 2019-present\n",
    )
    claims = {claim.claim_id for claim in report.claims}
    accounted: set[str] = set()

    assert report.decisions
    for decision in report.decisions:
        assert decision.approval_state == APPROVAL_STATE_NOT_APPROVED
        accounted.update(decision.keep_claim_ids)
        accounted.update(decision.merge_claim_ids)
        accounted.update(decision.alternative_claim_ids)

    for consolidated in report.consolidated:
        assert consolidated.approval_state == APPROVAL_STATE_NOT_APPROVED
        accounted.update(consolidated.claim_ids)

    # Every claim a decision talks about is accounted for, and no decision
    # silently drops a claim it names.
    for decision in report.decisions:
        named = (
            set(decision.keep_claim_ids)
            | set(decision.merge_claim_ids)
            | set(decision.alternative_claim_ids)
        )
        assert named <= claims
    assert accounted

    for claim in report.claims:
        for decision in report.decisions:
            if claim.claim_id in decision.merge_claim_ids and (
                decision.outcome is not Resolution.AUTO_CONSOLIDATE
            ):
                raise AssertionError("a claim is merged without an automatic merge")


def test_the_report_shape_is_unchanged_by_the_new_semantics():
    report = reconcile("Skills\nPython\n", "Skills\nPython\n")
    payload = report.as_dict()

    assert set(payload) == {
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
    decision = payload["decisions"][0]
    assert {
        "decision_id",
        "outcome",
        "category",
        "subject",
        "subject_label",
        "keep_claim_ids",
        "merge_claim_ids",
        "alternative_claim_ids",
        "relationship_ids",
        "explanation",
        "requires_user_confirmation",
        "approval_state",
    } <= set(decision)
    assert decision["approval_state"] == APPROVAL_STATE_NOT_APPROVED
    consolidated = payload["consolidated"][0]
    assert "qualifiers" in consolidated
    assert consolidated["approval_state"] == APPROVAL_STATE_NOT_APPROVED
