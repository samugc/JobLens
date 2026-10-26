"""Contract and behavior tests for the local CV parser."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from cv_builders import (
    encrypt_pdf,
    make_docx,
    make_legacy_doc,
    make_non_word_zip,
    make_pdf,
    make_two_column_pdf,
)

from joblens_public.cv_parser import (
    DEFAULT_LIMITS,
    SCHEMA_VERSION,
    ParseLimits,
    UploadDocument,
    extract_batch,
    extract_document,
)

PARSER_DIR = Path(__file__).resolve().parents[1] / "src" / "joblens_public" / "cv_parser"

BATCH_KEYS = {"schema_version", "batch", "documents"}
BATCH_META_KEYS = {
    "status",
    "document_count",
    "total_bytes",
    "status_counts",
    "limits",
    "error",
}
DOCUMENT_KEYS = {
    "index",
    "filename",
    "format",
    "status",
    "text",
    "segments",
    "warnings",
    "metadata",
}
SEGMENT_KEYS = {"locator", "text"}
WARNING_KEYS = {"code", "message"}
METADATA_KEYS = {"size_bytes", "page_count", "paragraph_count"}
STATUSES = {
    "extracted",
    "partial",
    "empty",
    "scanned_pdf",
    "encrypted",
    "malformed",
    "unsupported_format",
    "too_large",
}


def one(
    filename: str,
    data: bytes,
    *,
    limits=DEFAULT_LIMITS,
) -> dict:
    return extract_document(filename, data, limits=limits)


def warning_codes(document: dict) -> list[str]:
    return [item["code"] for item in document["warnings"]]


def test_pdf_extraction_has_page_level_provenance():
    document = one(
        "synthetic-cv.pdf",
        make_pdf([["Synthetic Candidate", "Experience"], ["Education"]]),
    )

    assert document["format"] == "pdf"
    assert document["status"] == "extracted"
    assert document["metadata"] == {
        "size_bytes": len(make_pdf([["Synthetic Candidate", "Experience"], ["Education"]])),
        "page_count": 2,
        "paragraph_count": None,
    }
    assert [segment["locator"] for segment in document["segments"]] == [
        {"kind": "page", "page": 1},
        {"kind": "page", "page": 2},
    ]
    assert document["segments"][0]["text"] == "Synthetic Candidate\nExperience"
    assert document["text"] == "Synthetic Candidate\nExperience\n\nEducation"
    assert document["warnings"] == []


def test_two_column_pdf_extracts_both_columns_with_page_locator():
    document = one(
        "two-column.pdf",
        make_two_column_pdf(
            ["LEFT_HEADING", "LEFT_BODY", "LEFT_END"],
            ["RIGHT_HEADING", "RIGHT_BODY", "RIGHT_END"],
        ),
    )

    assert document["status"] == "extracted"
    assert document["metadata"]["page_count"] == 1
    assert len(document["segments"]) == 1
    segment = document["segments"][0]
    assert segment["locator"] == {"kind": "page", "page": 1}
    assert set(segment["text"].splitlines()) == {
        "LEFT_HEADING",
        "LEFT_BODY",
        "LEFT_END",
        "RIGHT_HEADING",
        "RIGHT_BODY",
        "RIGHT_END",
    }
    assert document["warnings"] == []


def test_mixed_text_and_image_pages_are_partial_with_exact_page_locators():
    document = one(
        "mixed.pdf",
        make_pdf(
            [["Page one text"], [], ["Page three text"]],
            image_pages=[0, 1],
        ),
    )

    assert document["status"] == "partial"
    assert document["text"] == "Page one text\n\nPage three text"
    assert [segment["locator"] for segment in document["segments"]] == [
        {"kind": "page", "page": 1},
        {"kind": "page", "page": 3},
    ]
    assert warning_codes(document) == ["pages_without_text"]
    assert "1 PDF page" in document["warnings"][0]["message"]


def test_docx_extraction_has_paragraph_and_heading_provenance():
    data = make_docx(
        [
            ("Synthetic Candidate", None),
            ("", None),
            ("Experience", "Heading1"),
            ("Engineer at Example Company", None),
            ("Education", "Heading2"),
            ("Example University", None),
        ]
    )
    document = one("synthetic-cv.docx", data)

    assert document["format"] == "docx"
    assert document["status"] == "extracted"
    assert document["metadata"]["page_count"] is None
    assert document["metadata"]["paragraph_count"] == 6
    assert [segment["locator"] for segment in document["segments"]] == [
        {"kind": "paragraph", "paragraph": 1, "section": None},
        {"kind": "paragraph", "paragraph": 3, "section": "Experience"},
        {"kind": "paragraph", "paragraph": 4, "section": "Experience"},
        {"kind": "paragraph", "paragraph": 5, "section": "Education"},
        {"kind": "paragraph", "paragraph": 6, "section": "Education"},
    ]


def test_docx_table_paragraphs_are_extracted_in_document_order():
    data = make_docx(
        [("Skills", "Heading1")],
        table_rows=[["Python", "SQL"], ["pandas", ""]],
    )
    document = one("cv.docx", data)

    assert document["status"] == "extracted"
    assert [segment["text"] for segment in document["segments"]] == [
        "Skills",
        "Python",
        "SQL",
        "pandas",
    ]
    assert all(
        segment["locator"]["section"] == "Skills" for segment in document["segments"]
    )


def test_docx_lists_and_tables_have_exact_paragraph_locators():
    data = make_docx(
        [("Experience", "Heading1"), ("Senior Analyst", None)],
        list_items=["First item", "Second item"],
        table_rows=[["Python", "SQL"]],
    )
    document = one("structured.docx", data)

    assert document["status"] == "extracted"
    assert document["metadata"]["paragraph_count"] == 6
    assert [segment["text"] for segment in document["segments"]] == [
        "Experience",
        "Senior Analyst",
        "First item",
        "Second item",
        "Python",
        "SQL",
    ]
    assert [segment["locator"] for segment in document["segments"]] == [
        {"kind": "paragraph", "paragraph": 1, "section": "Experience"},
        {"kind": "paragraph", "paragraph": 2, "section": "Experience"},
        {"kind": "paragraph", "paragraph": 3, "section": "Experience"},
        {"kind": "paragraph", "paragraph": 4, "section": "Experience"},
        {"kind": "paragraph", "paragraph": 5, "section": "Experience"},
        {"kind": "paragraph", "paragraph": 6, "section": "Experience"},
    ]


def test_docx_outline_heading_and_run_breaks_are_supported():
    xml = (
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/'
        b'wordprocessingml/2006/main"><w:body>'
        b'<w:p><w:pPr><w:outlineLvl w:val="0"/></w:pPr>'
        b"<w:r><w:t>Experience</w:t></w:r></w:p>"
        b"<w:p><w:r><w:t>Line one</w:t><w:br/><w:t>Line two</w:t>"
        b"<w:tab/><w:t>End</w:t></w:r></w:p>"
        b"</w:body></w:document>"
    )
    document = one("outline.docx", make_docx(document_xml=xml))

    assert document["status"] == "extracted"
    assert document["segments"][1]["text"] == "Line one\nLine two\tEnd"
    assert document["segments"][1]["locator"]["section"] == "Experience"


def test_scanned_pdf_is_reported_explicitly():
    document = one("scan.pdf", make_pdf([[]], image_pages=[0]))

    assert document["status"] == "scanned_pdf"
    assert document["text"] == ""
    assert document["segments"] == []
    assert warning_codes(document) == ["scanned_pdf"]


def test_blank_pdf_is_empty_but_not_scanned():
    document = one("blank.pdf", make_pdf([[]]))

    assert document["status"] == "empty"
    assert warning_codes(document) == ["empty_document"]
    assert document["metadata"]["page_count"] == 1


def test_zero_page_pdf_is_empty():
    document = one("zero.pdf", make_pdf([]))

    assert document["status"] == "empty"
    assert warning_codes(document) == ["empty_pdf"]
    assert document["metadata"]["page_count"] == 0


def test_encrypted_pdf_is_reported_without_password_errors():
    document = one("protected.pdf", encrypt_pdf(make_pdf([["Synthetic Candidate"]])))

    assert document["status"] == "encrypted"
    assert document["text"] == ""
    assert warning_codes(document) == ["pdf_encrypted"]
    assert document["metadata"]["page_count"] is None


def test_pdf_pages_without_text_produce_partial_status_and_keep_text():
    document = one("partial.pdf", make_pdf([["Synthetic Candidate"], []]))

    assert document["status"] == "partial"
    assert document["text"] == "Synthetic Candidate"
    assert warning_codes(document) == ["pages_without_text"]
    assert "1 PDF page" in document["warnings"][0]["message"]


def test_pdf_page_limit_is_reported():
    limits = replace(DEFAULT_LIMITS, max_pdf_pages=1)
    document = one("long.pdf", make_pdf([["One"], ["Two"], ["Three"]]), limits=limits)

    assert document["status"] == "partial"
    assert document["metadata"]["page_count"] == 3
    assert [segment["locator"]["page"] for segment in document["segments"]] == [1]
    assert warning_codes(document) == ["page_limit_reached"]


def test_docx_paragraph_limit_is_reported():
    limits = replace(DEFAULT_LIMITS, max_docx_paragraphs=2)
    data = make_docx([("One", None), ("Two", None), ("Three", None)])
    document = one("long.docx", data, limits=limits)

    assert document["status"] == "partial"
    assert document["metadata"]["paragraph_count"] == 3
    assert [segment["locator"]["paragraph"] for segment in document["segments"]] == [1, 2]
    assert warning_codes(document) == ["paragraph_limit_reached"]


def test_empty_docx_variants_are_explicit():
    no_paragraphs = one("empty.docx", make_docx([]))
    blank_paragraph = one("blank.docx", make_docx([("", None), ("   ", None)]))
    empty_file = one("zero.docx", b"")

    assert no_paragraphs["status"] == "empty"
    assert warning_codes(no_paragraphs) == ["no_body_paragraphs"]
    assert blank_paragraph["status"] == "empty"
    assert warning_codes(blank_paragraph) == ["empty_document"]
    assert empty_file["status"] == "empty"
    assert warning_codes(empty_file) == ["empty_document"]


@pytest.mark.parametrize(
    "document",
    [
        lambda: one("broken.pdf", b"%PDF-1.4\nnot a real pdf"),
        lambda: one("broken.docx", b"not a zip archive"),
        lambda: one("broken.docx", b"PK\x03\x04not really a zip"),
    ],
)
def test_malformed_documents_are_structured_results(document):
    result = document()

    assert result["status"] == "malformed"
    assert result["text"] == ""
    assert result["segments"] == []
    assert warning_codes(result) == ["malformed_document"]


def test_docx_xml_with_doctype_is_rejected():
    xml = (
        b'<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY x "y">]>'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/'
        b'wordprocessingml/2006/main"><w:body/></w:document>'
    )
    document = one("unsafe.docx", make_docx(document_xml=xml))

    assert document["status"] == "malformed"
    assert warning_codes(document) == ["malformed_document"]


def test_docx_utf16_doctype_cannot_bypass_the_safety_check():
    xml = (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<!DOCTYPE foo [<!ENTITY x "y">]>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body/></w:document>'
    ).encode("utf-16")
    document = one("unsafe.docx", make_docx(document_xml=xml))

    assert document["status"] == "malformed"
    assert warning_codes(document) == ["malformed_document"]


def test_docx_utf16_body_is_supported():
    xml = (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
        "Synthetic Candidate</w:t></w:r></w:p></w:body></w:document>"
    ).encode("utf-16")
    document = one("utf16.docx", make_docx(document_xml=xml))

    assert document["status"] == "extracted"
    assert document["text"] == "Synthetic Candidate"


def test_docx_doctype_text_in_a_comment_is_allowed():
    xml = (
        b'<!-- <!DOCTYPE example> -->'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/'
        b'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
        b"Synthetic Candidate</w:t></w:r></w:p></w:body></w:document>"
    )
    document = one("comment.docx", make_docx(document_xml=xml))

    assert document["status"] == "extracted"
    assert document["text"] == "Synthetic Candidate"


def test_docx_xml_size_limit_is_enforced():
    limits = replace(DEFAULT_LIMITS, max_docx_xml_bytes=32)
    document = one("large.docx", make_docx([("Synthetic Candidate", None)]), limits=limits)

    assert document["status"] == "too_large"
    assert warning_codes(document) == ["document_too_large"]


def test_unsupported_legacy_and_non_word_formats():
    plain_text = one("notes.txt", b"Synthetic notes")
    legacy = one("old.doc", make_legacy_doc())
    spreadsheet = one("sheet.docx", make_non_word_zip())

    assert plain_text["status"] == "unsupported_format"
    assert plain_text["format"] == "unknown"
    assert warning_codes(plain_text) == ["unsupported_format"]
    assert legacy["status"] == "unsupported_format"
    assert warning_codes(legacy) == ["legacy_doc"]
    assert spreadsheet["status"] == "unsupported_format"
    assert warning_codes(spreadsheet) == ["non_word_ooxml"]


def test_content_detection_wins_and_mismatch_is_warned():
    docx_named_pdf = one("cv.pdf", make_docx([("Synthetic Candidate", None)]))
    pdf_named_docx = one("cv.docx", make_pdf([["Synthetic Candidate"]]))

    assert docx_named_pdf["format"] == "docx"
    assert docx_named_pdf["status"] == "extracted"
    assert "format_mismatch" in warning_codes(docx_named_pdf)
    assert pdf_named_docx["format"] == "pdf"
    assert pdf_named_docx["status"] == "extracted"
    assert "format_mismatch" in warning_codes(pdf_named_docx)


def test_per_document_size_limit():
    limits = replace(DEFAULT_LIMITS, max_file_bytes=10)
    document = one("large.pdf", make_pdf([["Synthetic Candidate"]]), limits=limits)

    assert document["status"] == "too_large"
    assert document["metadata"]["size_bytes"] > 10
    assert warning_codes(document) == ["document_too_large"]


def test_batch_rejects_more_than_five_documents():
    documents = [UploadDocument(f"cv-{index}.pdf", b"x") for index in range(6)]
    response = extract_batch(documents)

    assert response["batch"]["status"] == "rejected"
    assert response["batch"]["error"]["code"] == "too_many_documents"
    assert response["batch"]["document_count"] == 6
    assert response["documents"] == []
    assert all(value == 0 for value in response["batch"]["status_counts"].values())


def test_document_cap_cannot_be_raised_above_five():
    with pytest.raises(ValueError):
        ParseLimits(max_documents=6)


def test_batch_accepts_five_documents_and_counts_statuses():
    pdf = make_pdf([["Synthetic Candidate"]])
    documents = [UploadDocument(f"cv-{index}.pdf", pdf) for index in range(5)]
    response = extract_batch(documents)

    assert response["batch"]["status"] == "completed"
    assert response["batch"]["document_count"] == 5
    assert response["batch"]["status_counts"]["extracted"] == 5
    assert len(response["documents"]) == 5


def test_batch_is_partial_when_any_document_is_not_complete():
    complete = make_pdf([["Complete"]])
    truncated = make_pdf([["0123456789ABCDEF"]])
    response = extract_batch(
        [
            UploadDocument("complete.pdf", complete),
            UploadDocument("truncated.pdf", truncated),
        ],
        limits=replace(DEFAULT_LIMITS, max_text_chars=10),
    )

    assert [document["status"] for document in response["documents"]] == [
        "extracted",
        "partial",
    ]
    assert response["batch"]["status"] == "partial"
    assert response["batch"]["status_counts"]["extracted"] == 1
    assert response["batch"]["status_counts"]["partial"] == 1
    assert response["batch"]["error"] is None


def test_batch_is_not_completed_when_a_document_has_no_text():
    response = extract_batch(
        [
            UploadDocument("cv.pdf", make_pdf([["Synthetic Candidate"]])),
            UploadDocument("empty.pdf", make_pdf([[]])),
        ]
    )

    assert response["documents"][0]["status"] == "extracted"
    assert response["documents"][1]["status"] == "empty"
    assert response["batch"]["status"] == "partial"
    assert response["batch"]["status_counts"] == {
        "extracted": 1,
        "partial": 0,
        "empty": 1,
        "scanned_pdf": 0,
        "encrypted": 0,
        "malformed": 0,
        "unsupported_format": 0,
        "too_large": 0,
    }


def test_batch_rejects_empty_batch():
    response = extract_batch([])

    assert response["batch"]["status"] == "rejected"
    assert response["batch"]["error"]["code"] == "empty_batch"
    assert response["documents"] == []


def test_batch_total_size_limit_rejects_before_parsing():
    limits = replace(DEFAULT_LIMITS, max_batch_bytes=10)
    response = extract_batch(
        [UploadDocument("a.txt", b"x" * 6), UploadDocument("b.txt", b"x" * 6)],
        limits=limits,
    )

    assert response["batch"]["status"] == "rejected"
    assert response["batch"]["error"]["code"] == "batch_too_large"
    assert response["batch"]["total_bytes"] == 12
    assert response["documents"] == []


def test_text_truncation_applies_to_text_and_segments():
    limits = replace(DEFAULT_LIMITS, max_text_chars=10)
    document = one("long.pdf", make_pdf([["0123456789ABCDEF"]]), limits=limits)

    assert document["status"] == "partial"
    assert document["text"] == "0123456789"
    assert len(document["text"]) == 10
    assert document["segments"] == [
        {
            "locator": {"kind": "page", "page": 1},
            "text": "0123456789",
        }
    ]
    assert document["text"] == "\n\n".join(segment["text"] for segment in document["segments"])
    assert warning_codes(document) == ["text_truncated"]


def test_filename_is_reduced_to_a_safe_basename():
    data = make_pdf([["Synthetic Candidate"]])
    cases = {
        "../../private/cv.pdf": "cv.pdf",
        "folder/subfolder/cv.pdf": "cv.pdf",
        "C:\\\\folder\\\\cv.pdf": "cv.pdf",
        "": "document",
        "..": "document",
    }
    for supplied, expected in cases.items():
        document = one(supplied, data)
        assert document["filename"] == expected
        assert "/" not in document["filename"]
        assert "\\" not in document["filename"]


def test_response_contract_shape_is_stable_and_json_serialisable():
    response = extract_batch(
        [
            UploadDocument("cv.pdf", make_pdf([["Synthetic Candidate"]])),
            UploadDocument("scan.pdf", make_pdf([[]], image_pages=[0])),
            UploadDocument("broken.docx", b"not a zip"),
        ]
    )

    assert set(response) == BATCH_KEYS
    assert response["schema_version"] == SCHEMA_VERSION
    assert set(response["batch"]) == BATCH_META_KEYS
    assert response["batch"]["status"] == "partial"
    assert set(response["batch"]["status_counts"]) == STATUSES
    assert response["batch"]["status_counts"] == {
        "extracted": 1,
        "partial": 0,
        "empty": 0,
        "scanned_pdf": 1,
        "encrypted": 0,
        "malformed": 1,
        "unsupported_format": 0,
        "too_large": 0,
    }
    assert sum(response["batch"]["status_counts"].values()) == 3
    assert response["batch"]["error"] is None

    for index, document in enumerate(response["documents"]):
        assert set(document) == DOCUMENT_KEYS
        assert document["index"] == index
        assert document["status"] in STATUSES
        assert document["format"] in {"pdf", "docx", "unknown"}
        assert isinstance(document["text"], str)
        assert document["text"] == "\n\n".join(
            segment["text"] for segment in document["segments"]
        )
        assert set(document["metadata"]) == METADATA_KEYS
        for segment in document["segments"]:
            assert set(segment) == SEGMENT_KEYS
            assert segment["locator"]["kind"] in {"page", "paragraph"}
        for item in document["warnings"]:
            assert set(item) == WARNING_KEYS
            assert isinstance(item["code"], str)
            assert isinstance(item["message"], str)

    round_tripped = json.loads(json.dumps(response))
    assert round_tripped == response
    serialised = json.dumps(response)
    assert "Synthetic Candidate" in serialised


def test_response_contains_no_evidence_or_skill_verdicts():
    response = extract_batch([UploadDocument("cv.pdf", make_pdf([["Python"]]))])
    serialised = json.dumps(response).casefold()

    for forbidden in ("verified", "attested", "evidence", "skill_score", "confidence"):
        assert forbidden not in serialised


def test_parser_does_not_log_document_contents(caplog):
    caplog.set_level(logging.DEBUG)
    text = "Synthetic Candidate Marker"
    extract_document("cv.pdf", make_pdf([[text]]))
    extract_document("cv.docx", make_docx([(text, None)]))

    assert text not in caplog.text


def test_parser_package_does_not_import_the_evaluator():
    for path in PARSER_DIR.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "real_fit" not in source
        assert "core.models" not in source


def test_pypdf_is_a_mandatory_runtime_dependency():
    import tomllib

    project_root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = config["project"]["dependencies"]

    assert any(dependency.split(";")[0].strip().startswith("pypdf") for dependency in dependencies)
    optional = config["project"].get("optional-dependencies", {})
    assert all(
        "pypdf" not in dependency
        for dependencies in optional.values()
        for dependency in dependencies
    )


def test_cli_emits_the_json_contract(tmp_path):
    cv_path = tmp_path / "synthetic-cv.pdf"
    cv_path.write_bytes(make_pdf([["Synthetic Candidate"]]))

    completed = subprocess.run(
        [sys.executable, "-m", "joblens_public.cv_parser", str(cv_path)],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(PARSER_DIR.parents[2] / "src")},
    )
    response = json.loads(completed.stdout)

    assert response["schema_version"] == SCHEMA_VERSION
    assert response["batch"]["status"] == "completed"
    assert response["documents"][0]["filename"] == "synthetic-cv.pdf"
    assert response["documents"][0]["status"] == "extracted"


def test_cli_returns_nonzero_for_partial_extraction(tmp_path):
    cv_path = tmp_path / "partial-cv.pdf"
    cv_path.write_bytes(make_pdf([["Synthetic Candidate"], []]))

    completed = subprocess.run(
        [sys.executable, "-m", "joblens_public.cv_parser", str(cv_path)],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(PARSER_DIR.parents[2] / "src")},
    )
    response = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert response["batch"]["status"] == "partial"
    assert response["documents"][0]["status"] == "partial"


def test_docx_zip_bomb_via_many_entries_is_not_expanded():
    # Only the document part is read; unrelated huge entries are irrelevant.
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
            "Synthetic Candidate</w:t></w:r></w:p></w:body></w:document>",
        )
        archive.writestr("unused.bin", b"\x00" * 100_000)

    document = one("bomb.docx", output.getvalue())
    assert document["status"] == "extracted"
    assert document["text"] == "Synthetic Candidate"
