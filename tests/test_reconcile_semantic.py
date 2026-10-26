"""Tests for the semantic reasoner extension point.

The deterministic engine must work without any model. These tests check that
the seam exists, that a model conclusion is validated against the original
evidence, and that a model can never merge or approve anything.
"""
from __future__ import annotations

from profile_fixtures import make_document, make_response

from joblens_public.reconcile import (
    DeterministicReasoner,
    Relation,
    SemanticJudgement,
    reconcile_documents,
)

#: Two organisations whose names are similar: the deterministic comparators
#: cannot relate them, so this is the pair a reasoner would be asked about.
LEFT_TEXT = "Experience\nData Engineer | Acme | 2019-2022\n"
RIGHT_TEXT = "Experience\nData Engineer | Acme Corporation | 2019-2022\n"


def build(*texts: str):
    documents = [
        make_document(f"doc_{index}", text, index=index)
        for index, text in enumerate(texts)
    ]
    return reconcile_documents(make_response(documents))


def rebuild(reasoner):
    return reconcile_documents(
        make_response(
            [
                make_document("doc_0", LEFT_TEXT, index=0),
                make_document("doc_1", RIGHT_TEXT, index=1),
            ]
        ),
        reasoner=reasoner,
    )


class _Reasoner:
    def __init__(self, judgement):
        self.judgement = judgement
        self.calls = 0

    def compare(self, left, right):
        self.calls += 1
        return self.judgement


def employment_claims(report):
    return [claim for claim in report.claims if claim.category.value == "employment"]


def test_the_default_reasoner_never_proposes_anything():
    reasoner = DeterministicReasoner()
    assert reasoner.compare(None, None) is None


def test_an_uncertain_pair_is_where_a_reasoner_is_consulted():
    report = build(LEFT_TEXT, RIGHT_TEXT)
    employment = employment_claims(report)
    relationship = next(
        item
        for item in report.relationships
        if {item.left_claim_id, item.right_claim_id}
        == {employment[0].claim_id, employment[1].claim_id}
    )
    assert relationship.relation is Relation.UNCERTAIN
    assert relationship.semantic is False


def test_a_model_judgement_is_accepted_only_with_the_original_evidence():
    report = build(LEFT_TEXT, RIGHT_TEXT)
    employment = employment_claims(report)
    left, right = employment[0], employment[1]
    quote = left.evidence[0].quote

    reasoner = _Reasoner(
        SemanticJudgement(
            left_claim_id=left.claim_id,
            right_claim_id=right.claim_id,
            relation=Relation.TEMPORAL_UPDATE.value,
            reason="the second source is a later revision",
            quotes=(quote,),
        )
    )
    enriched = rebuild(reasoner)

    assert reasoner.calls >= 1
    semantic = [item for item in enriched.relationships if item.semantic]
    assert semantic
    assert semantic[0].relation is Relation.TEMPORAL_UPDATE
    assert semantic[0].basis == "semantic"


def test_a_judgement_that_cites_an_unknown_quotation_is_rejected():
    report = build(LEFT_TEXT, RIGHT_TEXT)
    employment = employment_claims(report)
    left, right = employment[0], employment[1]

    reasoner = _Reasoner(
        SemanticJudgement(
            left_claim_id=left.claim_id,
            right_claim_id=right.claim_id,
            relation=Relation.TEMPORAL_UPDATE.value,
            reason="invented",
            quotes=("a quotation that is not in the evidence",),
        )
    )
    enriched = rebuild(reasoner)

    assert reasoner.calls >= 1
    assert not [item for item in enriched.relationships if item.semantic]


def test_a_model_may_not_merge_claims():
    report = build(LEFT_TEXT, RIGHT_TEXT)
    employment = employment_claims(report)
    left, right = employment[0], employment[1]

    reasoner = _Reasoner(
        SemanticJudgement(
            left_claim_id=left.claim_id,
            right_claim_id=right.claim_id,
            relation=Relation.DUPLICATE.value,
            reason="the model says they are the same",
            quotes=(left.evidence[0].quote,),
        )
    )
    enriched = rebuild(reasoner)

    assert not [item for item in enriched.relationships if item.semantic]
    assert not enriched.consolidated


def test_an_unknown_relation_from_a_model_is_rejected():
    report = build(LEFT_TEXT, RIGHT_TEXT)
    employment = employment_claims(report)
    left, right = employment[0], employment[1]

    reasoner = _Reasoner(
        SemanticJudgement(
            left_claim_id=left.claim_id,
            right_claim_id=right.claim_id,
            relation="definitely_the_same",
            reason="unknown wording",
            quotes=(left.evidence[0].quote,),
        )
    )
    enriched = rebuild(reasoner)

    assert not [item for item in enriched.relationships if item.semantic]


def test_a_model_never_produces_an_automatic_consolidation():
    report = build(LEFT_TEXT, RIGHT_TEXT)
    employment = employment_claims(report)
    left, right = employment[0], employment[1]

    reasoner = _Reasoner(
        SemanticJudgement(
            left_claim_id=left.claim_id,
            right_claim_id=right.claim_id,
            relation=Relation.TEMPORAL_UPDATE.value,
            quotes=(left.evidence[0].quote,),
        )
    )
    enriched = rebuild(reasoner)

    assert not enriched.consolidated
    for decision in enriched.decisions:
        assert decision.requires_user_confirmation is True
