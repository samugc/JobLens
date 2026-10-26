from __future__ import annotations

import pytest

from joblens_public.export import (
    ApprovalError,
    ContactError,
    EvidenceContractError,
    InvalidDraftError,
    UnsupportedSchemaError,
    export_cv_docx_bytes,
    export_cv_pdf_bytes,
)

from .test_helpers import make_draft


def test_invalid_schema_version():
    d = make_draft(cv_draft_version="9.9")
    with pytest.raises(UnsupportedSchemaError):
        export_cv_pdf_bytes(d)


def test_missing_full_name():
    d = make_draft()
    d["candidate"]["full_name"] = None
    with pytest.raises(ContactError):
        export_cv_pdf_bytes(d)


def test_unapproved_item():
    d = make_draft()
    d["sections"][0]["items"][0]["review_status"] = "needs_review"
    with pytest.raises(ApprovalError):
        export_cv_pdf_bytes(d)


def test_missing_fact_ids():
    d = make_draft()
    d["sections"][0]["items"][0]["approved_fact_ids"] = []
    with pytest.raises(EvidenceContractError):
        export_cv_pdf_bytes(d)


def test_edited_item_not_reapproved():
    # edited item resets to needs_review
    d = make_draft()
    d["sections"][0]["items"][0]["text"] = "Rewritten"
    d["sections"][0]["items"][0]["review_status"] = "approved"  # still approved but fact ids ok; simulate edited? 
    # Actually edited item should be needs_review; approval required.
    d["sections"][0]["items"][0]["review_status"] = "needs_review"
    with pytest.raises(ApprovalError):
        export_cv_docx_bytes(d)


def test_invalid_evidence_contract():
    d = make_draft()
    with pytest.raises(EvidenceContractError):
        export_cv_pdf_bytes(d, evidence_support={"facts": [{"fact_id": "nope"}]})


def test_evidence_contract_unknown_fact():
    d = make_draft()
    with pytest.raises(EvidenceContractError):
        export_cv_pdf_bytes(d, evidence_support={"facts": [{"fact_id": "fact_999"}]})


def test_evidence_contract_valid():
    d = make_draft()
    support = {"facts": [{"fact_id": "fact_1"}, {"fact_id": "fact_2"}, {"fact_id": "fact_3"}, {"fact_id": "fact_4"}]}
    data = export_cv_pdf_bytes(d, evidence_support=support)
    assert data[:4] == b"%PDF"


def test_malformed_draft_not_mapping():
    with pytest.raises(InvalidDraftError):
        export_cv_pdf_bytes("not a draft")


def test_missing_sections_field_ok():
    d = make_draft()
    del d["sections"]
    # no items -> invalid
    with pytest.raises(InvalidDraftError):
        export_cv_pdf_bytes(d)


def test_empty_items_rejected():
    d = make_draft()
    d["sections"][0]["items"] = []
    d["sections"][1]["items"] = []
    d["sections"][2]["items"] = []
    with pytest.raises(InvalidDraftError):
        export_cv_pdf_bytes(d)


def test_invalid_review_status():
    d = make_draft()
    d["sections"][0]["items"][0]["review_status"] = "maybe"
    # adapter allows string; validate requires approved -> ApprovalError (not approved)
    with pytest.raises(ApprovalError):
        export_cv_pdf_bytes(d)


def test_schema_invalid_missing_item_id():
    d = make_draft()
    del d["sections"][0]["items"][0]["item_id"]
    with pytest.raises(InvalidDraftError):
        export_cv_pdf_bytes(d)