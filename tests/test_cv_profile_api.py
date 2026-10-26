"""HTTP tests for the mounted candidate profile route.

The route is exercised over real HTTP against the application server. Every
document is synthetic.
"""
from __future__ import annotations

import http.client
import json
import socket
import threading

import pytest
from profile_fixtures import (
    EDUCATION_SECTION,
    LANGUAGES_SECTION,
    SKILLS_SECTION,
    make_document,
    make_response,
)

from joblens_public import webapp
from joblens_public.data import load_demo_data

PROFILE_PATH = "/api/cv/profiles"


@pytest.fixture(scope="module")
def app_server():
    candidates, jobs = load_demo_data()
    server = webapp.create_server(candidates, jobs, 0)
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
    timeout: float = 20.0,
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


def json_headers(port: int, **extra: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Origin": f"http://127.0.0.1:{port}",
        "X-JobLens-Request": "1",
        "Accept": "application/json",
        **extra,
    }


def profile_body(documents, job_id: str = "job_synthetic") -> bytes:
    response = make_response(documents, job_id=job_id)
    return json.dumps({"job_id": response["job_id"], "documents": response["documents"]}).encode(
        "utf-8"
    )


def post_profile(port: int, body: bytes, headers: dict[str, str] | None = None):
    request_headers = json_headers(port)
    if headers:
        request_headers.update(headers)
    return request(port, "POST", PROFILE_PATH, body, request_headers)


def payload_of(raw: bytes) -> dict:
    value = json.loads(raw.decode("utf-8"))
    assert isinstance(value, dict)
    return value


def test_profile_request_returns_the_canonical_envelope(app_server):
    document = make_document("doc_alpha", SKILLS_SECTION)
    status, headers, raw = post_profile(app_server.server_port, profile_body([document]))

    assert status == 200
    assert headers["content-type"].startswith("application/json")
    assert headers["cache-control"] == "no-store"
    assert "access-control-allow-origin" not in headers

    payload = payload_of(raw)
    assert payload["profile_schema_version"] == "0.1"
    assert payload["parser_schema_version"] == "1.1"
    assert payload["job_id"] == "job_synthetic"
    assert [item["document_id"] for item in payload["documents"]] == ["doc_alpha"]
    assert payload["proposals"]
    assert payload["conflicts"] == []
    assert payload["warnings"] == []


def test_profile_evidence_offsets_match_the_submitted_segments(app_server):
    document = make_document("doc_offsets", SKILLS_SECTION)
    body = profile_body([document])
    status, _, raw = post_profile(app_server.server_port, body)
    assert status == 200

    payload = payload_of(raw)
    submitted = json.loads(body.decode("utf-8"))["documents"][0]["segments"]
    for proposal in payload["proposals"]:
        assert proposal["status"] == "proposed"
        assert proposal["evidence"]
        for reference in proposal["evidence"]:
            segment = submitted[reference["segment_index"]]
            assert segment["text"][reference["start"]:reference["end"]] == reference["quote"]
            assert segment["locator"] == reference["locator"]


def test_profile_groups_duplicates_across_documents(app_server):
    first = make_document("doc_one", SKILLS_SECTION, index=0)
    second = make_document("doc_two", "Skills\nPython and SQL\n", index=1)
    status, _, raw = post_profile(
        app_server.server_port, profile_body([first, second])
    )

    assert status == 200
    payload = payload_of(raw)
    python = [
        proposal
        for proposal in payload["proposals"]
        if proposal["value"].get("name") == "python"
    ]
    assert len(python) == 1
    assert len(python[0]["evidence"]) == 2
    assert {item["document_id"] for item in python[0]["evidence"]} == {"doc_one", "doc_two"}


def test_profile_reports_conflicting_evidence(app_server):
    first = make_document("doc_a", "Languages\nEnglish (C1)\n", index=0)
    second = make_document("doc_b", "Languages\nEnglish (B2)\n", index=1)
    status, _, raw = post_profile(
        app_server.server_port, profile_body([first, second])
    )

    assert status == 200
    payload = payload_of(raw)
    assert len(payload["conflicts"]) == 1
    conflict = payload["conflicts"][0]
    assert conflict["kind"] == "conflicting_stated_level"
    languages = [
        proposal
        for proposal in payload["proposals"]
        if proposal["category"] == "language"
    ]
    assert len(languages) == 2
    for proposal in languages:
        assert conflict["conflict_id"] in proposal["conflicts"]


def test_profile_returns_the_optional_resolution_hint(app_server):
    first = make_document("doc_a", "Languages\nEnglish (C1)\n", index=0)
    second = make_document("doc_b", "Languages\nEnglish (B2)\n", index=1)
    status, _, raw = post_profile(
        app_server.server_port, profile_body([first, second])
    )

    assert status == 200
    payload = payload_of(raw)
    hint = payload["conflicts"][0]["resolution_hint"]
    assert hint["strategy"] == "prefer_higher_cefr_claim"
    assert hint["requires_user_confirmation"] is True
    assert len(hint["keep_proposal_ids"]) == 1
    assert set(payload) == {
        "profile_schema_version",
        "parser_schema_version",
        "job_id",
        "documents",
        "proposals",
        "conflicts",
        "warnings",
    }


def test_profile_only_ever_returns_proposed_facts(app_server):
    document = make_document("doc_status", SKILLS_SECTION)
    status, _, raw = post_profile(app_server.server_port, profile_body([document]))

    assert status == 200
    payload = payload_of(raw)
    assert payload["proposals"]
    assert {proposal["status"] for proposal in payload["proposals"]} == {"proposed"}


@pytest.mark.parametrize(
    "injected",
    [
        {"proposals": []},
        {"approvals": [{"proposal_id": "prop_x", "status": "approved"}]},
        {"status": "approved"},
        {"schema_version": "1.1"},
    ],
)
def test_profile_rejects_a_request_that_carries_review_decisions(app_server, injected):
    document = make_document("doc_inject", SKILLS_SECTION)
    response = make_response([document], job_id="job_synthetic")
    payload = {"job_id": response["job_id"], "documents": response["documents"]}
    payload.update(injected)

    status, _, raw = post_profile(
        app_server.server_port, json.dumps(payload).encode("utf-8")
    )

    assert status == 400
    error = payload_of(raw)["error"]
    assert error["code"] == "invalid_request"
    assert "Unexpected field" in error["message"]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda body: {**body, "job_id": ""}, "job_id"),
        (lambda body: {**body, "job_id": 7}, "job_id"),
        (lambda body: {"documents": body["documents"]}, "job_id"),
        (lambda body: {**body, "documents": "nope"}, "documents"),
        (lambda body: {**body, "documents": []}, "documents"),
        (lambda body: {**body, "documents": body["documents"] * 6}, "documents"),
    ],
)
def test_profile_rejects_a_malformed_top_level_request(app_server, mutate, expected):
    document = make_document("doc_bad", SKILLS_SECTION)
    body = json.loads(profile_body([document]).decode("utf-8"))
    status, _, raw = post_profile(
        app_server.server_port, json.dumps(mutate(body)).encode("utf-8")
    )

    assert status == 400
    error = payload_of(raw)["error"]
    assert error["code"] == "invalid_request"
    assert expected in error["message"]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda document: {**document, "document_id": ""}, "document_id"),
        (lambda document: {**document, "document_id": 3}, "document_id"),
        (lambda document: {**document, "index": 4}, "index"),
        (lambda document: {**document, "index": "0"}, "index"),
        (lambda document: {**document, "filename": None}, "filename"),
        (lambda document: {**document, "status": ""}, "status"),
        (lambda document: {**document, "format": []}, "format"),
        (lambda document: {**document, "segments": {}}, "segments"),
        (lambda document: {**document, "segments": ["text"]}, "segments"),
        (
            lambda document: {
                **document,
                "segments": [{"locator": {"kind": "page", "page": 1}}],
            },
            "text",
        ),
        (
            lambda document: {
                **document,
                "segments": [{"text": "body"}],
            },
            "locator",
        ),
    ],
)
def test_profile_rejects_a_malformed_document(app_server, mutate, expected):
    document = make_document("doc_bad", SKILLS_SECTION)
    body = json.loads(profile_body([document]).decode("utf-8"))
    body["documents"][0] = mutate(body["documents"][0])

    status, _, raw = post_profile(
        app_server.server_port, json.dumps(body).encode("utf-8")
    )

    assert status == 400
    error = payload_of(raw)["error"]
    assert error["code"] == "invalid_request"
    assert expected in error["message"]


def test_profile_rejects_duplicated_document_ids(app_server):
    first = make_document("doc_same", SKILLS_SECTION, index=0)
    second = make_document("doc_same", SKILLS_SECTION, index=1)
    status, _, raw = post_profile(
        app_server.server_port, profile_body([first, second])
    )

    assert status == 400
    assert "duplicated" in payload_of(raw)["error"]["message"]


def test_profile_rejects_a_body_that_is_not_json(app_server):
    status, _, raw = post_profile(app_server.server_port, b"{not json")

    assert status == 400
    assert payload_of(raw)["error"]["code"] == "invalid_json"


def test_profile_rejects_a_non_json_content_type(app_server):
    body = profile_body([make_document("doc_ct", SKILLS_SECTION)])
    status, _, raw = post_profile(
        app_server.server_port,
        body,
        {"Content-Type": "text/plain"},
    )

    assert status == 415
    assert payload_of(raw)["error"]["code"] == "invalid_content_type"


def test_profile_requires_content_length(app_server):
    port = app_server.server_port
    request_bytes = (
        "POST /api/cv/profiles HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{port}\r\n"
        f"Origin: http://127.0.0.1:{port}\r\n"
        "X-JobLens-Request: 1\r\n"
        "Content-Type: application/json\r\n"
        "Connection: close\r\n\r\n"
    ).encode()
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        connection.sendall(request_bytes)
        connection.settimeout(5)
        response = b""
        while True:
            chunk = connection.recv(4096)
            if not chunk:
                break
            response += chunk

    assert b"411" in response
    assert b"length_required" in response


def test_profile_rejects_an_oversized_body(app_server):
    port = app_server.server_port
    request_bytes = (
        "POST /api/cv/profiles HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{port}\r\n"
        f"Origin: http://127.0.0.1:{port}\r\n"
        "X-JobLens-Request: 1\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {webapp.PROFILE_MAX_BODY + 1}\r\n"
        "Connection: close\r\n\r\n"
    ).encode()
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        connection.sendall(request_bytes)
        connection.settimeout(5)
        response = b""
        while True:
            chunk = connection.recv(4096)
            if not chunk:
                break
            response += chunk

    assert b"413" in response
    assert b"request_too_large" in response


def test_profile_requires_the_same_origin_and_token(app_server):
    port = app_server.server_port
    body = profile_body([make_document("doc_guard", SKILLS_SECTION)])

    status, _, raw = request(
        port,
        "POST",
        PROFILE_PATH,
        body,
        {
            "Content-Type": "application/json",
            "Origin": f"http://127.0.0.1:{port}",
        },
    )
    assert status == 403
    assert payload_of(raw)["error"] == "Invalid origin or request token"

    status, _, raw = request(
        port,
        "POST",
        PROFILE_PATH,
        body,
        {
            "Content-Type": "application/json",
            "Origin": "https://example.invalid",
            "X-JobLens-Request": "1",
        },
    )
    assert status == 403
    assert payload_of(raw)["error"] == "Invalid origin or request token"


def test_profile_uses_the_real_engine_once(app_server, monkeypatch):
    calls: list[dict] = []
    original = webapp.build_profile_proposals

    def capturing(response):
        calls.append(response)
        return original(response)

    monkeypatch.setattr(webapp, "build_profile_proposals", capturing)
    document = make_document("doc_engine", SKILLS_SECTION)
    status, _, raw = post_profile(app_server.server_port, profile_body([document]))

    assert status == 200
    assert len(calls) == 1
    assert calls[0]["schema_version"] == "1.1"
    assert calls[0]["job_id"] == "job_synthetic"
    assert calls[0]["documents"][0]["document_id"] == "doc_engine"
    assert payload_of(raw)["profile_schema_version"] == "0.1"


def test_profile_get_is_not_allowed(app_server):
    status, headers, raw = request(app_server.server_port, "GET", PROFILE_PATH)

    assert status == 405
    assert headers.get("allow") == "POST"
    assert payload_of(raw)["error"]["code"] == "method_not_allowed"


def test_profile_accepts_the_full_transport_document(app_server):
    document = make_document("doc_full", SKILLS_SECTION)
    document["text"] = SKILLS_SECTION
    document["warnings"] = [{"code": "pages_without_text", "message": "One page."}]
    document["metadata"] = {"size_bytes": 12, "page_count": 1, "paragraph_count": None}
    status, _, raw = post_profile(app_server.server_port, profile_body([document]))

    assert status == 200
    assert payload_of(raw)["proposals"]


def test_profile_education_and_language_documents(app_server):
    document = make_document(
        "doc_full",
        "\n".join([EDUCATION_SECTION.rstrip("\n"), LANGUAGES_SECTION.rstrip("\n")]),
    )
    status, _, raw = post_profile(app_server.server_port, profile_body([document]))

    assert status == 200
    payload = payload_of(raw)
    categories = {proposal["category"] for proposal in payload["proposals"]}
    assert "education" in categories
    assert "language" in categories


def test_workspace_profile_assets_are_allowlisted(app_server, tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "profile-adapter.js").write_text("// synthetic adapter")
    (workspace / "profile-review.js").write_text("// synthetic review")
    fixtures = workspace / "fixtures"
    fixtures.mkdir()
    (fixtures / "batch-completed.json").write_text('{"secret_fixture": true}')
    monkeypatch.setattr(webapp, "WEB_DIR", tmp_path)

    port = app_server.server_port
    for name in ("profile-adapter.js", "profile-review.js"):
        status, headers, raw = request(port, "GET", f"/workspace/{name}")
        assert status == 200
        assert headers["content-type"].startswith("text/javascript")

    status, _, raw = request(port, "GET", "/workspace/fixtures/batch-completed.json")
    assert status == 404
    assert b"secret_fixture" not in raw


def test_workspace_profile_assets_report_a_missing_bundle(app_server, tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "WEB_DIR", tmp_path)
    status, _, raw = request(app_server.server_port, "GET", "/workspace/profile-adapter.js")

    assert status == 404
    assert "not assembled" in payload_of(raw)["error"]


def test_the_demo_routes_are_untouched(app_server):
    port = app_server.server_port
    status, _, _ = request(port, "GET", "/")
    assert status == 200
    status, _, raw = request(port, "GET", "/api/status")
    assert status == 200
    assert payload_of(raw)["mode"] == "local"
    status, _, _ = request(port, "GET", "/api/bootstrap")
    assert status == 200
