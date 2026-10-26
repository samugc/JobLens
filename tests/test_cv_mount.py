"""Tests for the CV transport mounted in the main local application.

The application under test is the public demo server. These tests check that
the mounted extraction route works, that every pre-existing route keeps its
original behaviour, and that no private file can be served.
"""
from __future__ import annotations

import http.client
import json
import re
import threading

import pytest
from cv_builders import make_docx, make_pdf
from cv_http_helpers import build_multipart

from joblens_public.cv_parser import http_transport
from joblens_public.data import load_demo_data
from joblens_public.webapp import MAX_BODY, create_server

JOB_ID_PATTERN = re.compile(r"^job_[0-9a-f]{32}$")
DOCUMENT_ID_PATTERN = re.compile(r"^doc_[0-9a-f]{32}$")
CV_PATH = "/api/cv/extractions"
WORKSPACE = "/workspace/"


@pytest.fixture
def app_server():
    candidates, jobs = load_demo_data()
    server = create_server(candidates, jobs, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def request(
    port: int,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        raw = response.read()
        return (
            response.status,
            {name.casefold(): value for name, value in response.getheaders()},
            raw,
        )
    finally:
        connection.close()


def cv_headers(port: int, *, content_type: str | None = None) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "X-JobLens-Request": "1",
        "Origin": f"http://127.0.0.1:{port}",
        **({"Content-Type": content_type} if content_type else {}),
    }


def post_cv(
    port: int,
    files: list[tuple[str, bytes]],
    *,
    fields: list[tuple[str, str]] = (),
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    body, boundary = build_multipart(files, fields=fields)
    request_headers = cv_headers(port, content_type=f"multipart/form-data; boundary={boundary}")
    if headers:
        request_headers.update(headers)
    return request(port, "POST", CV_PATH, body, request_headers)


def payload_of(raw: bytes) -> dict:
    value = json.loads(raw.decode("utf-8"))
    assert isinstance(value, dict)
    return value


def synthetic_pdf() -> bytes:
    return make_pdf([["Synthetic Candidate", "Experience"], ["Education"]])


def synthetic_docx() -> bytes:
    return make_docx([("Synthetic Candidate", "Heading1"), ("Experience", None)])


def test_mounted_extraction_returns_the_transport_contract(app_server):
    status, headers, raw = post_cv(
        app_server.server_port,
        [("files", "synthetic-cv.pdf", synthetic_pdf()), ("files", "cv.docx", synthetic_docx())],
    )

    assert status == 200
    assert headers["content-type"].startswith("application/json")
    assert headers["cache-control"] == "no-store"
    assert "access-control-allow-origin" not in headers

    body = payload_of(raw)
    assert body["transport_version"] == "1.0"
    assert body["schema_version"] == "1.1"
    assert JOB_ID_PATTERN.match(body["job_id"])
    assert body["batch"]["status"] == "completed"
    assert body["batch"]["document_count"] == 2
    assert [document["filename"] for document in body["documents"]] == [
        "synthetic-cv.pdf",
        "cv.docx",
    ]
    assert [document["format"] for document in body["documents"]] == ["pdf", "docx"]
    assert all(
        DOCUMENT_ID_PATTERN.match(document["document_id"])
        for document in body["documents"]
    )
    assert body["documents"][0]["text"].startswith("Synthetic Candidate")


def test_mounted_extraction_calls_handle_upload_request_exactly_once(app_server, monkeypatch):
    calls: list[int] = []
    original = http_transport.handle_upload_request

    def counting(**kwargs):
        calls.append(1)
        return original(**kwargs)

    monkeypatch.setattr(http_transport, "handle_upload_request", counting)
    status, _, _ = post_cv(
        app_server.server_port,
        [("files", "synthetic-cv.pdf", synthetic_pdf())],
    )

    assert status == 200
    assert len(calls) == 1


def test_mounted_extraction_rejects_six_documents(app_server):
    files = [
        ("files", f"synthetic-{index}.pdf", synthetic_pdf())
        for index in range(6)
    ]
    status, _, raw = post_cv(app_server.server_port, files)

    assert status == 400
    body = payload_of(raw)
    assert body["error"]["code"] == "too_many_documents"
    assert body["batch"]["status"] == "rejected"
    assert body["documents"] == []


def test_mounted_extraction_reports_a_failed_document_without_failing_the_batch(app_server):
    status, _, raw = post_cv(
        app_server.server_port,
        [("files", "synthetic-cv.pdf", synthetic_pdf()), ("files", "broken.pdf", b"not a pdf")],
    )

    assert status == 200
    body = payload_of(raw)
    assert body["batch"]["status"] == "partial"
    assert [document["status"] for document in body["documents"]] == [
        "extracted",
        "malformed",
    ]


def test_mounted_extraction_uses_the_cv_limits_not_the_json_limit(app_server):
    large = make_pdf([["Synthetic Candidate"] * 4000])
    assert len(large) > MAX_BODY
    status, _, raw = post_cv(
        app_server.server_port,
        [("files", "large.pdf", large)],
    )

    assert status == 200
    assert payload_of(raw)["batch"]["status"] == "completed"


def test_analyze_keeps_the_json_body_limit(app_server):
    body = json.dumps({"candidate_id": "alex-rivera", "job": {"description": "x" * 70000}})
    status, _, raw = request(
        app_server.server_port,
        "POST",
        "/api/analyze",
        body.encode("utf-8"),
        {
            "Content-Type": "application/json",
            "Origin": f"http://127.0.0.1:{app_server.server_port}",
            "X-JobLens-Request": "1",
        },
    )

    assert status == 413
    assert "too large" in payload_of(raw)["error"]


def test_existing_routes_keep_their_original_behaviour(app_server):
    port = app_server.server_port
    candidates, jobs = load_demo_data()

    status, headers, html = request(port, "GET", "/")
    assert status == 200
    assert b"JobLens" in html
    assert "no-store" in headers.get("cache-control", "")

    status, _, raw = request(port, "GET", "/api/status")
    assert status == 200
    assert payload_of(raw)["mode"] == "local"

    status, _, raw = request(port, "GET", "/api/bootstrap")
    assert status == 200
    bootstrap = payload_of(raw)
    assert bootstrap["meta"]["synthetic"] is True
    assert len(bootstrap["candidates"]) == len(candidates)
    assert len(bootstrap["jobs"]) == len(jobs)

    status, _, _ = request(port, "GET", "/assets/app.js")
    assert status == 200
    status, _, _ = request(port, "GET", "/favicon.svg")
    assert status == 200

    status, _, raw = request(port, "GET", "/api/unknown")
    assert status == 404
    assert payload_of(raw)["error"] == "Not found"

    body = json.dumps({
        "candidate_id": "alex-rivera",
        "job": public_job(jobs["junior-ai-engineer-aster"]),
    }).encode()
    status, _, raw = request(
        port,
        "POST",
        "/api/analyze",
        body,
        {
            "Content-Type": "application/json",
            "Origin": f"http://127.0.0.1:{port}",
            "X-JobLens-Request": "1",
        },
    )
    assert status == 200
    assert payload_of(raw)["evaluator"] == "python"


def public_job(job: dict) -> dict:
    return {
        "title": job["title"],
        "company": job["company"],
        "location": job["location"],
        "description": job["description"],
    }


def test_mounted_route_requires_the_same_origin_and_token(app_server):
    port = app_server.server_port
    body, boundary = build_multipart([("files", "synthetic-cv.pdf", synthetic_pdf())])
    content_type = f"multipart/form-data; boundary={boundary}"

    status, _, raw = request(
        port,
        "POST",
        CV_PATH,
        body,
        {"Content-Type": content_type, "Origin": f"http://127.0.0.1:{port}"},
    )
    assert status == 403
    assert payload_of(raw)["error"] == "Invalid origin or request token"

    status, _, raw = request(
        port,
        "POST",
        CV_PATH,
        body,
        {"Content-Type": content_type, "Origin": "https://example.invalid", "X-JobLens-Request": "1"},
    )
    assert status == 403
    assert payload_of(raw)["error"] == "Invalid origin or request token"


def test_mounted_route_rejects_a_non_multipart_body(app_server):
    status, _, raw = request(
        app_server.server_port,
        "POST",
        CV_PATH,
        b"{}",
        {
            "Content-Type": "application/json",
            "Origin": f"http://127.0.0.1:{app_server.server_port}",
            "X-JobLens-Request": "1",
        },
    )

    assert status == 415
    assert payload_of(raw)["error"]["code"] == "invalid_content_type"


def test_mounted_route_keeps_no_state(app_server):
    port = app_server.server_port
    _, _, raw = post_cv(port, [("files", "synthetic-cv.pdf", synthetic_pdf())])
    job_id = payload_of(raw)["job_id"]

    status, _, raw = request(port, "GET", f"{CV_PATH}/{job_id}")
    assert status == 404
    assert payload_of(raw)["error"]["code"] == "job_not_found"

    status, headers, raw = request(port, "GET", CV_PATH)
    assert status == 405
    assert payload_of(raw)["error"]["code"] == "method_not_allowed"
    assert headers.get("allow") == "POST"


def test_mounted_route_reports_a_missing_parser_as_503(app_server, monkeypatch):
    from joblens_public.cv_parser import service

    def unavailable(documents, **kwargs):
        raise ImportError("missing parser library")

    monkeypatch.setattr(service, "extract_batch", unavailable)
    status, _, raw = post_cv(
        app_server.server_port,
        [("files", "synthetic-cv.pdf", synthetic_pdf())],
    )

    assert status == 503
    body = payload_of(raw)
    assert body["error"]["code"] == "parser_unavailable"
    assert "missing parser library" not in raw.decode("utf-8")


def test_mounted_route_redacts_unexpected_failures(app_server, monkeypatch):
    from joblens_public.cv_parser import service

    def explode(documents, **kwargs):
        raise RuntimeError("SECRET-CV-CONTENT /private/path/SECRET-CV-NAME.pdf")

    monkeypatch.setattr(service, "extract_batch", explode)
    status, _, raw = post_cv(
        app_server.server_port,
        [("files", "SECRET-CV-NAME.pdf", synthetic_pdf())],
    )

    assert status == 500
    body = payload_of(raw)
    assert body["error"] == {
        "code": "internal_error",
        "message": "The extraction request failed.",
    }
    assert b"SECRET" not in raw


def test_workspace_route_reports_missing_assets(app_server, tmp_path, monkeypatch):
    monkeypatch.setattr("joblens_public.webapp.WEB_DIR", tmp_path)
    status, _, raw = request(app_server.server_port, "GET", WORKSPACE)

    assert status == 404
    assert "not assembled" in payload_of(raw)["error"]


def test_workspace_assets_are_allowlisted(app_server, tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "index.html").write_text("<!doctype html><title>CV workspace</title>")
    (workspace / "app.js").write_text("// synthetic app")
    (workspace / "api-adapter.js").write_text("// synthetic adapter")
    (workspace / "styles.css").write_text("body { color: #000; }")
    (workspace / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>")
    fixtures = workspace / "fixtures"
    fixtures.mkdir()
    (fixtures / "batch-completed.json").write_text('{"secret_fixture": true}')
    (workspace / "private-notes.txt").write_text("SECRET-PRIVATE-FILE")
    monkeypatch.setattr("joblens_public.webapp.WEB_DIR", tmp_path)

    port = app_server.server_port
    status, headers, raw = request(port, "GET", WORKSPACE)
    assert status == 200
    assert headers["content-type"].startswith("text/html")
    assert b"CV workspace" in raw

    for name, kind in (
        ("app.js", "text/javascript"),
        ("api-adapter.js", "text/javascript"),
        ("styles.css", "text/css"),
        ("favicon.svg", "image/svg+xml"),
    ):
        status, headers, raw = request(port, "GET", f"{WORKSPACE}{name}")
        assert status == 200
        assert headers["content-type"].startswith(kind)

    status, _, raw = request(port, "GET", f"{WORKSPACE}fixtures/batch-completed.json")
    assert status == 404
    assert b"secret_fixture" not in raw

    status, _, raw = request(port, "GET", f"{WORKSPACE}private-notes.txt")
    assert status == 404
    assert b"SECRET-PRIVATE-FILE" not in raw


def test_private_files_cannot_be_served(app_server):
    port = app_server.server_port
    for path in (
        "/src/joblens_public/webapp.py",
        "/tests/test_web.py",
        "/pyproject.toml",
        f"{WORKSPACE}../../../src/joblens_public/webapp.py",
        f"{WORKSPACE}..%2f..%2fpyproject.toml",
        "/workspace/fixtures/batch-completed.json",
    ):
        status, _, raw = request(port, "GET", path)
        assert status == 404, path
        assert b"joblens_public" not in raw
        assert b"def " not in raw
        assert b"dependencies" not in raw


def test_workspace_short_path_redirects_to_the_canonical_url(app_server):
    status, headers, _ = request(app_server.server_port, "GET", "/workspace")

    assert status == 302
    assert headers.get("location") == "/workspace/"
