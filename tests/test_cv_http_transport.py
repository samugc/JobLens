"""Unit tests for the local CV HTTP transport."""
from __future__ import annotations

import io
import json
import re
import tempfile

import pytest
from cv_builders import make_docx, make_pdf
from cv_http_helpers import build_multipart

from joblens_public.cv_parser import ParseLimits, UploadDocument, extract_batch
from joblens_public.cv_parser.http_transport import (
    SCHEMA_VERSION,
    TRANSPORT_VERSION,
    ExtractionGate,
    TransportError,
    decorate_parser_response,
    default_extract_fn,
    error_payload,
    handle_upload_request,
    max_body_bytes,
    parse_multipart,
    read_bounded_body,
    serve_extraction_request,
)

JOB_ID_PATTERN = re.compile(r"^job_[0-9a-f]{32}$")
DOCUMENT_ID_PATTERN = re.compile(r"^doc_[0-9a-f]{32}$")


def parse(
    files: list[tuple[str, bytes]],
    *,
    fields: list[tuple[str, str]] | None = None,
    max_parts: int = 64,
):
    body, boundary = build_multipart(files, fields=fields or [])
    return parse_multipart(
        f"multipart/form-data; boundary={boundary}",
        body,
        max_parts=max_parts,
    )


def test_multipart_preserves_binary_payloads_and_order():
    binary = b"%PDF-1.7\r\n\x00\x01\x02--not-the-boundary\r\nend"
    uploads = parse(
        [
            ("files", "first.pdf", binary),
            ("files", "second.docx", b"PK\x03\x04\x00\r\n"),
        ]
    )

    assert [upload.filename for upload in uploads] == ["first.pdf", "second.docx"]
    assert uploads[0].data == binary
    assert uploads[1].data == b"PK\x03\x04\x00\r\n"


def test_multipart_preserves_unicode_filename():
    uploads = parse([("files", "currículum.pdf", b"data")])
    assert uploads[0].filename == "currículum.pdf"


def test_multipart_ignores_other_fields():
    uploads = parse(
        [("files", "cv.pdf", b"data")],
        fields=[("note", "ignored")],
    )
    assert len(uploads) == 1
    assert uploads[0].filename == "cv.pdf"


def test_multipart_without_files_returns_empty_list():
    assert parse([], fields=[("note", "ignored")]) == []


def test_multipart_rejects_missing_boundary():
    with pytest.raises(TransportError) as caught:
        parse_multipart("multipart/form-data", b"body")

    assert caught.value.status == 400
    assert caught.value.code == "invalid_content_type"


def test_multipart_rejects_non_multipart_content_type():
    with pytest.raises(TransportError) as caught:
        parse_multipart("application/json", b"{}")

    assert caught.value.status == 415
    assert caught.value.code == "invalid_content_type"


def test_multipart_rejects_wrong_boundary():
    body, _ = build_multipart([("files", "cv.pdf", b"data")])
    with pytest.raises(TransportError) as caught:
        parse_multipart("multipart/form-data; boundary=other", body)

    assert caught.value.status == 400
    assert caught.value.code == "invalid_multipart"


def test_multipart_rejects_truncated_body():
    body, boundary = build_multipart([("files", "cv.pdf", b"data")])
    body = body.rsplit(b"\r\n--", 1)[0]
    with pytest.raises(TransportError) as caught:
        parse_multipart(f"multipart/form-data; boundary={boundary}", body)

    assert caught.value.status == 400
    assert caught.value.code == "invalid_multipart"


def test_multipart_rejects_missing_filename():
    boundary = "bnd"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="files"\r\n\r\n'
        "data\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    with pytest.raises(TransportError) as caught:
        parse_multipart(f"multipart/form-data; boundary={boundary}", body)

    assert caught.value.status == 400
    assert caught.value.code == "missing_filename"


def test_multipart_rejects_nested_multipart_files_part():
    boundary = "bnd"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="files"; filename="cv.pdf"\r\n'
        "Content-Type: multipart/mixed; boundary=inner\r\n\r\n"
        "--inner\r\n\r\nabc\r\n--inner--\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    with pytest.raises(TransportError) as caught:
        parse_multipart(f"multipart/form-data; boundary={boundary}", body)

    assert caught.value.status == 400
    assert caught.value.code == "invalid_part"


def test_multipart_rejects_too_many_parts():
    files = [("files", f"{index}.pdf", b"x") for index in range(3)]
    with pytest.raises(TransportError) as caught:
        parse(files, max_parts=2)

    assert caught.value.status == 400
    assert caught.value.code == "too_many_parts"


def test_decorate_completed_response_preserves_parser_contract():
    response = extract_batch(
        [UploadDocument("synthetic-cv.pdf", make_pdf([["Synthetic Candidate"]]))]
    )
    status, payload = decorate_parser_response(response, "job_" + "a" * 32)

    assert status == 200
    assert payload["transport_version"] == TRANSPORT_VERSION
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["job_id"] == "job_" + "a" * 32
    assert payload["batch"] == response["batch"]
    assert len(payload["documents"]) == 1
    document = payload["documents"][0]
    assert DOCUMENT_ID_PATTERN.match(document["document_id"])
    assert {key: value for key, value in document.items() if key != "document_id"} == (
        response["documents"][0]
    )


def test_decorate_partial_response_keeps_document_ids():
    response = extract_batch(
        [
            UploadDocument("synthetic-cv.pdf", make_pdf([["Synthetic Candidate"]])),
            UploadDocument("broken.pdf", b"not a pdf"),
        ]
    )
    status, payload = decorate_parser_response(response, "job_" + "b" * 32)

    assert status == 200
    assert payload["batch"]["status"] == "partial"
    assert len(payload["documents"]) == 2
    ids = [document["document_id"] for document in payload["documents"]]
    assert all(DOCUMENT_ID_PATTERN.match(value) for value in ids)
    assert len(set(ids)) == 2


def test_decorate_empty_batch_is_http_400():
    status, payload = decorate_parser_response(extract_batch([]), "job_" + "c" * 32)

    assert status == 400
    assert payload["batch"]["status"] == "rejected"
    assert payload["error"] == payload["batch"]["error"]
    assert payload["error"]["code"] == "empty_batch"


def test_decorate_too_many_documents_is_http_400():
    documents = [UploadDocument(f"{index}.pdf", b"x") for index in range(6)]
    status, payload = decorate_parser_response(
        extract_batch(documents),
        "job_" + "d" * 32,
    )

    assert status == 400
    assert payload["error"]["code"] == "too_many_documents"


def test_decorate_batch_too_large_is_http_413():
    limits = ParseLimits(max_file_bytes=20, max_batch_bytes=10)
    documents = [UploadDocument("a.pdf", b"x" * 20), UploadDocument("b.pdf", b"x" * 20)]
    status, payload = decorate_parser_response(
        extract_batch(documents, limits=limits),
        "job_" + "e" * 32,
    )

    assert status == 413
    assert payload["error"]["code"] == "batch_too_large"


def test_decorate_unknown_rejection_code_is_http_400():
    response = {
        "schema_version": SCHEMA_VERSION,
        "batch": {
            "status": "rejected",
            "document_count": 0,
            "total_bytes": 0,
            "status_counts": {},
            "limits": {},
            "error": {"code": "future_rejection", "message": "Future rejection."},
        },
        "documents": [],
    }
    status, payload = decorate_parser_response(response, "job_" + "f" * 32)

    assert status == 400
    assert payload["error"]["code"] == "future_rejection"


@pytest.mark.parametrize(
    "response",
    [
        None,
        {},
        {"schema_version": "1.0", "batch": {}, "documents": []},
        {"schema_version": SCHEMA_VERSION, "batch": {}, "documents": []},
        {
            "schema_version": SCHEMA_VERSION,
            "batch": {"status": "completed", "document_count": 0},
            "documents": [{}],
        },
    ],
)
def test_decorate_invalid_parser_response_is_http_500(response):
    with pytest.raises(TransportError) as caught:
        decorate_parser_response(response, "job_" + "a" * 32)

    assert caught.value.status == 500
    assert caught.value.code == "invalid_parser_response"


def test_ids_are_unique_and_opaque():
    response = extract_batch(
        [UploadDocument("secret-name.pdf", make_pdf([["Synthetic Candidate"]]))]
    )
    first = decorate_parser_response(response, "job_" + "1" * 32)[1]
    second = decorate_parser_response(response, "job_" + "2" * 32)[1]

    assert JOB_ID_PATTERN.match(first["job_id"])
    assert JOB_ID_PATTERN.match(second["job_id"])
    assert first["job_id"] != second["job_id"]
    assert first["documents"][0]["document_id"] != second["documents"][0]["document_id"]
    assert "secret-name" not in first["job_id"]
    assert "secret-name" not in first["documents"][0]["document_id"]


def test_transport_does_not_create_temporary_files(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("temporary file used")

    for name in ("mkstemp", "mkdtemp", "NamedTemporaryFile", "TemporaryDirectory"):
        monkeypatch.setattr(tempfile, name, fail)

    uploads = parse([("files", "cv.pdf", make_pdf([["Synthetic Candidate"]]))])
    response = extract_batch(uploads)
    status, payload = decorate_parser_response(response, "job_" + "3" * 32)

    assert status == 200
    assert json.loads(json.dumps(payload))["batch"]["status"] == "completed"


def test_docx_upload_through_transport_unit_path():
    uploads = parse(
        [
            (
                "files",
                "synthetic.docx",
                make_docx([("Synthetic Candidate", "Heading1"), ("Experience", None)]),
            )
        ]
    )
    response = extract_batch(uploads)

    assert response["documents"][0]["format"] == "docx"
    assert response["documents"][0]["status"] == "extracted"


def test_multipart_rejects_non_ascii_content_type():
    with pytest.raises(TransportError) as caught:
        parse_multipart("multipart/form-data; boundary=b\xf1nd", b"body")

    assert caught.value.status == 400
    assert caught.value.code == "invalid_content_type"


def test_multipart_rejects_boundary_with_control_characters():
    with pytest.raises(TransportError) as caught:
        parse_multipart('multipart/form-data; boundary="bad\nboundary"', b"body")

    assert caught.value.status == 400
    assert caught.value.code == "invalid_content_type"


def test_decorate_rejects_documents_that_are_not_a_list():
    with pytest.raises(TransportError) as caught:
        decorate_parser_response(
            {
                "schema_version": SCHEMA_VERSION,
                "batch": {"status": "completed", "document_count": 0},
                "documents": "not-a-list",
            },
            "job_" + "a" * 32,
        )

    assert caught.value.status == 500
    assert caught.value.code == "invalid_parser_response"


def test_error_payload_contains_only_fixed_information():
    payload = error_payload("internal_error", None, "job_" + "a" * 32)

    assert payload["transport_version"] == TRANSPORT_VERSION
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["job_id"] == "job_" + "a" * 32
    assert payload["documents"] == []
    assert payload["error"] == {
        "code": "internal_error",
        "message": "The extraction request failed.",
    }


def test_handle_upload_request_returns_a_terminal_response():
    body, boundary = build_multipart(
        [("files", "synthetic-cv.pdf", make_pdf([["Synthetic Candidate"]]))]
    )
    status, payload = handle_upload_request(
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        body=body,
        extract_fn=extract_batch,
    )

    assert status == 200
    assert payload["batch"]["status"] == "completed"
    assert payload["transport_version"] == TRANSPORT_VERSION
    assert JOB_ID_PATTERN.match(payload["job_id"])
    assert DOCUMENT_ID_PATTERN.match(payload["documents"][0]["document_id"])


def test_handle_upload_request_requires_a_content_type():
    body, _ = build_multipart([("files", "synthetic-cv.pdf", b"data")])

    with pytest.raises(TransportError) as caught:
        handle_upload_request(headers={}, body=body, extract_fn=extract_batch)

    assert caught.value.status == 415
    assert caught.value.code == "invalid_content_type"


def test_handle_upload_request_rejects_a_body_over_the_limit():
    limits = ParseLimits(max_file_bytes=100, max_batch_bytes=100)
    body, boundary = build_multipart([("files", "synthetic-cv.pdf", b"x" * 200)])
    oversized = body + b"x" * max_body_bytes(limits)

    with pytest.raises(TransportError) as caught:
        handle_upload_request(
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            body=oversized,
            extract_fn=lambda documents: extract_batch(documents, limits=limits),
            limits=limits,
        )

    assert caught.value.status == 413
    assert caught.value.code == "request_too_large"


class _TimeoutStream:
    def read(self, size: int) -> bytes:
        raise TimeoutError


def test_read_bounded_body_returns_the_declared_bytes():
    assert read_bounded_body(io.BytesIO(b"payload"), 7, max_bytes=64) == b"payload"


def test_read_bounded_body_rejects_an_oversized_length():
    with pytest.raises(TransportError) as caught:
        read_bounded_body(io.BytesIO(b"payload"), 65, max_bytes=64)

    assert caught.value.status == 413
    assert caught.value.code == "request_too_large"


def test_read_bounded_body_rejects_a_short_body():
    with pytest.raises(TransportError) as caught:
        read_bounded_body(io.BytesIO(b"pay"), 7, max_bytes=64)

    assert caught.value.status == 400
    assert caught.value.code == "incomplete_body"


def test_read_bounded_body_reports_a_timeout():
    with pytest.raises(TransportError) as caught:
        read_bounded_body(_TimeoutStream(), 7, max_bytes=64)

    assert caught.value.status == 408
    assert caught.value.code == "request_timeout"


def test_serve_extraction_request_returns_a_terminal_response():
    body, boundary = build_multipart(
        [("files", "synthetic-cv.pdf", make_pdf([["Synthetic Candidate"]]))]
    )
    status, payload = serve_extraction_request(
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
        stream=io.BytesIO(body),
        extract_fn=extract_batch,
    )

    assert status == 200
    assert payload["batch"]["status"] == "completed"
    assert JOB_ID_PATTERN.match(payload["job_id"])
    assert DOCUMENT_ID_PATTERN.match(payload["documents"][0]["document_id"])


def test_serve_extraction_request_calls_handle_upload_request_once(monkeypatch):
    calls: list[int] = []
    original = handle_upload_request

    def counting(**kwargs):
        calls.append(1)
        return original(**kwargs)

    monkeypatch.setattr(
        "joblens_public.cv_parser.http_transport.handle_upload_request",
        counting,
    )
    body, boundary = build_multipart(
        [("files", "synthetic-cv.pdf", make_pdf([["Synthetic Candidate"]]))]
    )
    status, _ = serve_extraction_request(
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
        stream=io.BytesIO(body),
        extract_fn=extract_batch,
    )

    assert status == 200
    assert len(calls) == 1


def test_serve_extraction_request_requires_a_declared_length():
    body, boundary = build_multipart([("files", "synthetic-cv.pdf", b"data")])

    with pytest.raises(TransportError) as caught:
        serve_extraction_request(
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            stream=io.BytesIO(body),
            extract_fn=extract_batch,
        )

    assert caught.value.status == 411
    assert caught.value.code == "length_required"


def test_serve_extraction_request_rejects_an_encoded_body():
    body, boundary = build_multipart([("files", "synthetic-cv.pdf", b"data")])

    with pytest.raises(TransportError) as caught:
        serve_extraction_request(
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
                "Content-Encoding": "gzip",
            },
            stream=io.BytesIO(body),
            extract_fn=extract_batch,
        )

    assert caught.value.status == 415
    assert caught.value.code == "unsupported_content_encoding"


def test_serve_extraction_request_rejects_an_oversized_body():
    body, boundary = build_multipart([("files", "synthetic-cv.pdf", b"data")])

    with pytest.raises(TransportError) as caught:
        serve_extraction_request(
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            },
            stream=io.BytesIO(body),
            extract_fn=extract_batch,
            max_body=4,
        )

    assert caught.value.status == 413
    assert caught.value.code == "request_too_large"


def test_extraction_gate_rejects_excess_work_without_queueing():
    gate = ExtractionGate(1)

    with gate.slot():
        with pytest.raises(TransportError) as caught:
            with gate.slot():
                pass

    assert caught.value.status == 503
    assert caught.value.code == "server_busy"

    with gate.slot():
        pass


def test_default_extract_fn_calls_the_parser():
    extract = default_extract_fn()
    response = extract([UploadDocument("synthetic-cv.pdf", make_pdf([["Candidate"]]))])

    assert response["batch"]["status"] == "completed"

