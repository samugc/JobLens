"""End-to-end tests for the loopback CV HTTP transport."""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cv_builders import make_docx, make_pdf
from cv_http_helpers import (
    api_headers,
    build_multipart,
    json_body,
    post_files,
    raw_request,
    request,
    running_server,
)

from joblens_public.cv_parser import ParseLimits, UploadDocument, extract_batch
from joblens_public.cv_parser.http_transport import TRANSPORT_VERSION

JOB_ID_PATTERN = re.compile(r"^job_[0-9a-f]{32}$")
DOCUMENT_ID_PATTERN = re.compile(r"^doc_[0-9a-f]{32}$")
SRC = Path(__file__).resolve().parents[1] / "src"


def synthetic_pdf(text: str = "Synthetic Candidate\nExperience") -> bytes:
    return make_pdf([text.splitlines()])


def synthetic_docx() -> bytes:
    return make_docx([("Synthetic Candidate", "Heading1"), ("Experience", None)])


def test_pdf_and_docx_complete_with_ids_and_parser_contract():
    pdf = synthetic_pdf()
    docx = synthetic_docx()
    with running_server() as server:
        status, headers, raw = post_files(
            server.server_port,
            [("files", "synthetic-cv.pdf", pdf), ("files", "synthetic-cv.docx", docx)],
        )

    assert status == 200
    assert headers["content-type"].startswith("application/json")
    assert headers["cache-control"] == "no-store"
    assert "access-control-allow-origin" not in headers
    assert "python" not in headers["server"].casefold()
    assert headers["connection"] == "close"

    payload = json_body(raw)
    assert payload["transport_version"] == TRANSPORT_VERSION
    assert payload["schema_version"] == "1.1"
    assert JOB_ID_PATTERN.match(payload["job_id"])
    assert payload["batch"]["status"] == "completed"
    assert payload["batch"]["document_count"] == 2
    assert [document["filename"] for document in payload["documents"]] == [
        "synthetic-cv.pdf",
        "synthetic-cv.docx",
    ]
    assert [document["format"] for document in payload["documents"]] == ["pdf", "docx"]
    assert all(
        DOCUMENT_ID_PATTERN.match(document["document_id"])
        for document in payload["documents"]
    )

    direct = extract_batch(
        [
            UploadDocument("synthetic-cv.pdf", pdf),
            UploadDocument("synthetic-cv.docx", docx),
        ]
    )
    assert payload["batch"] == direct["batch"]
    assert [
        {key: value for key, value in document.items() if key != "document_id"}
        for document in payload["documents"]
    ] == direct["documents"]


def test_partial_batch_is_http_200_with_document_ids():
    with running_server() as server:
        status, _, raw = post_files(
            server.server_port,
            [
                ("files", "valid.pdf", synthetic_pdf()),
                ("files", "broken.pdf", b"not a PDF"),
            ],
        )

    assert status == 200
    payload = json_body(raw)
    assert payload["batch"]["status"] == "partial"
    assert [document["status"] for document in payload["documents"]] == [
        "extracted",
        "malformed",
    ]
    assert all("document_id" in document for document in payload["documents"])


def test_five_documents_accepted_and_six_rejected():
    files = [
        ("files", f"synthetic-{index}.pdf", synthetic_pdf(f"Candidate {index}"))
        for index in range(5)
    ]
    with running_server() as server:
        status, _, raw = post_files(server.server_port, files)
        assert status == 200
        payload = json_body(raw)
        assert payload["batch"]["document_count"] == 5

        status, _, raw = post_files(
            server.server_port,
            [*files, ("files", "sixth.pdf", synthetic_pdf("Sixth"))],
        )

    assert status == 400
    payload = json_body(raw)
    assert payload["error"]["code"] == "too_many_documents"
    assert payload["batch"]["status"] == "rejected"


def test_empty_batch_is_http_400():
    with running_server() as server:
        status, _, raw = post_files(
            server.server_port,
            [],
            fields=[("note", "no files attached")],
        )

    assert status == 400
    payload = json_body(raw)
    assert payload["error"]["code"] == "empty_batch"
    assert payload["batch"]["status"] == "rejected"


def test_batch_too_large_is_http_413():
    limits = ParseLimits(max_file_bytes=200, max_batch_bytes=300)
    with running_server(limits=limits) as server:
        status, _, raw = post_files(
            server.server_port,
            [
                ("files", "a.pdf", b"x" * 120),
                ("files", "b.pdf", b"x" * 120),
                ("files", "c.pdf", b"x" * 120),
            ],
        )

    assert status == 413
    payload = json_body(raw)
    assert payload["error"]["code"] == "batch_too_large"
    assert payload["batch"]["status"] == "rejected"


def test_per_document_too_large_is_http_200():
    limits = ParseLimits(max_file_bytes=50, max_batch_bytes=1000)
    with running_server(limits=limits) as server:
        status, _, raw = post_files(
            server.server_port,
            [("files", "too-large.pdf", b"x" * 100)],
        )

    assert status == 200
    payload = json_body(raw)
    assert payload["batch"]["status"] == "partial"
    assert payload["documents"][0]["status"] == "too_large"
    assert payload["documents"][0]["document_id"]


def test_text_limit_marks_document_partial():
    limits = ParseLimits(max_text_chars=10)
    with running_server(limits=limits) as server:
        status, _, raw = post_files(
            server.server_port,
            [("files", "long.pdf", synthetic_pdf("A long synthetic candidate text"))],
        )

    assert status == 200
    payload = json_body(raw)
    assert payload["batch"]["status"] == "partial"
    assert payload["documents"][0]["status"] == "partial"
    assert "text_truncated" in [
        warning["code"] for warning in payload["documents"][0]["warnings"]
    ]


def test_malformed_multipart_is_http_400():
    with running_server() as server:
        body, boundary = build_multipart([("files", "cv.pdf", synthetic_pdf())])
        headers = api_headers(
            server.server_port,
            content_type="multipart/form-data; boundary=wrong",
        )
        status, _, raw = request(
            server.server_port,
            "POST",
            "/api/cv/extractions",
            body,
            headers,
        )

    assert status == 400
    assert json_body(raw)["error"]["code"] == "invalid_multipart"


def test_wrong_content_type_is_http_415():
    with running_server() as server:
        headers = api_headers(
            server.server_port,
            content_type="application/json",
        )
        status, _, raw = request(
            server.server_port,
            "POST",
            "/api/cv/extractions",
            b"{}",
            headers,
        )

    assert status == 415
    assert json_body(raw)["error"]["code"] == "invalid_content_type"


def test_oversized_content_length_is_rejected_before_body_read():
    with running_server() as server:
        port = server.server_port
        response = raw_request(
            port,
            (
                "POST /api/cv/extractions HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                f"Origin: http://127.0.0.1:{port}\r\n"
                "X-JobLens-Request: synthetic-test-token\r\n"
                "Content-Type: multipart/form-data; boundary=bnd\r\n"
                "Content-Length: 999999999\r\n"
                "Connection: close\r\n\r\n"
            ).encode(),
        )

    assert b"413" in response
    assert b"request_too_large" in response


def test_host_origin_and_token_guards():
    with running_server() as server:
        port = server.server_port
        body, boundary = build_multipart([("files", "cv.pdf", synthetic_pdf())])
        content_type = f"multipart/form-data; boundary={boundary}"

        headers = api_headers(port, token=False, content_type=content_type)
        status, _, raw = request(
            port, "POST", "/api/cv/extractions", body, headers
        )
        assert status == 403
        assert json_body(raw)["error"]["code"] == "missing_request_token"

        headers = api_headers(port, content_type=content_type)
        headers["Origin"] = "https://example.invalid"
        status, _, raw = request(
            port, "POST", "/api/cv/extractions", body, headers
        )
        assert status == 403
        assert json_body(raw)["error"]["code"] == "invalid_origin"

        response = raw_request(
            port,
            (
                "GET /api/cv/extractions HTTP/1.1\r\n"
                "Host: evil.example\r\n"
                "Connection: close\r\n\r\n"
            ).encode(),
        )
        assert b"403" in response
        assert b"invalid_host" in response

        status, _, raw = request(port, "OPTIONS", "/api/cv/extractions")
        assert status == 403
        assert json_body(raw)["error"]["code"] == "cross_site_request"


def test_missing_content_length_is_http_411():
    with running_server() as server:
        port = server.server_port
        response = raw_request(
            port,
            (
                "POST /api/cv/extractions HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                f"Origin: http://127.0.0.1:{port}\r\n"
                "X-JobLens-Request: synthetic-test-token\r\n"
                "Content-Type: multipart/form-data; boundary=bnd\r\n"
                "Connection: close\r\n\r\n"
            ).encode(),
        )

    assert b"411" in response
    assert b"length_required" in response


def test_content_encoding_and_transfer_encoding_are_rejected():
    with running_server() as server:
        port = server.server_port
        body, boundary = build_multipart([("files", "cv.pdf", synthetic_pdf())])
        headers = api_headers(
            port,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        headers["Content-Encoding"] = "gzip"
        status, _, raw = request(
            port, "POST", "/api/cv/extractions", body, headers
        )
        assert status == 415
        assert json_body(raw)["error"]["code"] == "unsupported_content_encoding"

        headers = api_headers(
            port,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        headers["Transfer-Encoding"] = "chunked"
        status, _, raw = request(
            port, "POST", "/api/cv/extractions", body, headers
        )
        assert status == 411
        assert json_body(raw)["error"]["code"] == "length_required"


def test_routes_and_methods():
    with running_server() as server:
        port = server.server_port
        status, _, raw = request(port, "GET", "/api/cv/extractions")
        assert status == 405
        assert json_body(raw)["error"]["code"] == "method_not_allowed"

        status, _, raw = request(port, "GET", "/api/cv/extractions/job_missing")
        assert status == 404
        assert json_body(raw)["error"]["code"] == "job_not_found"

        status, _, raw = request(port, "GET", "/api/cv/unknown")
        assert status == 404
        assert json_body(raw)["error"]["code"] == "not_found"


def test_ids_are_unique_across_requests():
    with running_server() as server:
        first = json_body(
            post_files(server.server_port, [("files", "a.pdf", synthetic_pdf())])[2]
        )
        second = json_body(
            post_files(server.server_port, [("files", "a.pdf", synthetic_pdf())])[2]
        )

    assert first["job_id"] != second["job_id"]
    assert (
        first["documents"][0]["document_id"]
        != second["documents"][0]["document_id"]
    )


def test_concurrent_requests_are_independent():
    with running_server(max_concurrent=2) as server:
        port = server.server_port

        def send(index: int):
            return post_files(
                port,
                [("files", f"concurrent-{index}.pdf", synthetic_pdf(f"Candidate {index}"))],
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(send, range(2)))

    assert all(status == 200 for status, _, _ in results)
    payloads = [json_body(raw) for _, _, raw in results]
    assert len({payload["job_id"] for payload in payloads}) == 2
    assert all(payload["batch"]["status"] == "completed" for payload in payloads)


def test_privacy_logs_and_error_redaction():
    log = io.StringIO()
    with running_server(access_log=True, log_stream=log) as server:
        status, _, raw = post_files(
            server.server_port,
            [("files", "SECRET-CV-NAME.pdf", synthetic_pdf("SECRET-CV-CONTENT"))],
        )
        assert status == 200
        payload = json_body(raw)
        assert payload["job_id"] in log.getvalue()
        assert "SECRET-CV-NAME" not in log.getvalue()
        assert "SECRET-CV-CONTENT" not in log.getvalue()
        assert "synthetic-test-token" not in log.getvalue()

    def explode(uploads):
        raise RuntimeError("SECRET-CV-CONTENT /private/path/SECRET-CV-NAME.pdf")

    error_log = io.StringIO()
    with running_server(log_stream=error_log, extract_fn=explode) as server:
        status, _, raw = post_files(
            server.server_port,
            [("files", "SECRET-CV-NAME.pdf", synthetic_pdf())],
        )

    assert status == 500
    payload = json_body(raw)
    assert payload["error"] == {
        "code": "internal_error",
        "message": "The extraction request failed.",
    }
    assert b"SECRET" not in raw
    assert "SECRET" not in error_log.getvalue()


def test_parser_unavailable_is_http_503():
    def unavailable(uploads):
        raise ImportError("missing parser library")

    with running_server(extract_fn=unavailable) as server:
        status, _, raw = post_files(
            server.server_port,
            [("files", "cv.pdf", synthetic_pdf())],
        )

    assert status == 503
    payload = json_body(raw)
    assert payload["error"]["code"] == "parser_unavailable"
    assert "missing parser library" not in raw.decode("utf-8")


def test_no_temporary_files_created(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("temporary file used")

    for name in ("mkstemp", "mkdtemp", "NamedTemporaryFile", "TemporaryDirectory"):
        monkeypatch.setattr(tempfile, name, fail)

    with running_server() as server:
        status, _, raw = post_files(
            server.server_port,
            [("files", "cv.pdf", synthetic_pdf())],
        )

    assert status == 200
    assert json_body(raw)["batch"]["status"] == "completed"


def test_unsupported_document_is_http_200_with_a_failed_document():
    with running_server() as server:
        status, _, raw = post_files(
            server.server_port,
            [("files", "notes.txt", b"plain text, not a CV")],
        )

    assert status == 200
    payload = json_body(raw)
    assert payload["batch"]["status"] == "partial"
    assert payload["documents"][0]["status"] == "unsupported_format"
    assert payload["documents"][0]["document_id"]
    assert payload["documents"][0]["text"] == ""


def test_cross_site_fetch_header_is_rejected():
    with running_server() as server:
        port = server.server_port
        body, boundary = build_multipart([("files", "cv.pdf", synthetic_pdf())])
        headers = api_headers(
            port,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        headers["Sec-Fetch-Site"] = "cross-site"
        status, _, raw = request(
            port, "POST", "/api/cv/extractions", body, headers
        )

    assert status == 403
    assert json_body(raw)["error"]["code"] == "cross_site_request"


def test_privacy_headers_and_unknown_route():
    with running_server() as server:
        port = server.server_port
        status, headers, raw = post_files(
            port,
            [("files", "cv.pdf", synthetic_pdf())],
        )
        assert status == 200
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["referrer-policy"] == "no-referrer"
        assert "access-control-allow-origin" not in headers
        assert "set-cookie" not in headers

        status, _, raw = request(port, "POST", "/api/cv/unknown", b"", api_headers(port))
        assert status == 404
        assert json_body(raw)["error"]["code"] == "not_found"


def test_standalone_entry_point_serves_a_real_request():
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(SRC)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "joblens_public.cv_parser.http_transport",
            "--port",
            "0",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        text=True,
    )
    try:
        banner = process.stderr.readline()
        assert "listening on http://127.0.0.1:" in banner, banner
        port = int(banner.rsplit(":", 1)[1].split()[0])
        status, _, raw = post_files(
            port,
            [("files", "synthetic-cv.pdf", synthetic_pdf())],
        )
    finally:
        process.terminate()
        process.wait(timeout=10)

    assert status == 200
    payload = json_body(raw)
    assert payload["batch"]["status"] == "completed"
    assert payload["schema_version"] == "1.1"
    assert JOB_ID_PATTERN.match(payload["job_id"])
