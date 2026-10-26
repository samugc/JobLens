"""Isolation and honesty checks for the CV evidence workspace.

These tests pin the workspace boundaries that matter for review:

* the public demo files are not the workspace files,
* the workspace HTML has no inline scripts or styles,
* every DOM id used by ``app.js`` exists in ``index.html``,
* the workspace JS never writes inline styles or raw HTML,
* the committed fixtures follow parser schema 1.1 over transport 1.0 and are
  synthetic and honest,
* the preview server serves workspace assets only and refuses extraction.
"""

from __future__ import annotations

import http.client
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "web" / "workspace"
FIXTURES = WORKSPACE / "fixtures"
SERVER_SCRIPT = ROOT / "scripts" / "serve_cv_workspace.py"

SCHEMA_VERSION = "1.1"
TRANSPORT_VERSION = "1.0"
PROFILE_SCHEMA_VERSION = "0.1"

BATCH_STATUSES = {"completed", "partial", "rejected"}
PARSER_DOCUMENT_STATUSES = {
    "extracted",
    "partial",
    "empty",
    "scanned_pdf",
    "encrypted",
    "malformed",
    "unsupported_format",
    "too_large",
}
DOCUMENT_FORMATS = {"pdf", "docx", "unknown"}
BATCH_ERROR_CODES = {"empty_batch", "too_many_documents", "batch_too_large"}
LIMIT_KEYS = {
    "max_documents",
    "max_file_bytes",
    "max_batch_bytes",
    "max_text_chars",
    "max_pdf_pages",
    "max_docx_paragraphs",
    "max_docx_xml_bytes",
}
TEXT_STATUSES = {"extracted", "partial"}

PROFILE_CATEGORIES = {
    "skill",
    "experience",
    "education",
    "project",
    "language",
    "certification",
}
PROFILE_STATUSES = {"proposed", "approved", "rejected", "superseded"}
PROFILE_SUPPORT = {"explicit_claim", "keyword_mention"}
PROFILE_VALUES = {
    "skill": {"name"},
    "experience": {"role"},
    "education": {"level", "field"},
    "project": {"name"},
    "language": {"language", "stated_level"},
    "certification": {"name"},
}
DEGREE_LEVELS = {
    "bachelor",
    "master",
    "doctorate",
    "associate",
    "diploma",
    "mba",
}


def extraction_fixtures() -> list[Path]:
    return sorted(FIXTURES.glob("batch-*.json"))


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def server_port():
    spec = importlib.util.spec_from_file_location("serve_cv_workspace", SERVER_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Loading the preview script must not leave a __pycache__ next to it.
    dont_write = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = dont_write
    server = module.build_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_port
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def request(port, method, path, body=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request(method, path, body=body)
    response = connection.getresponse()
    payload = response.read()
    result = (response.status, dict(response.getheaders()), payload)
    connection.close()
    return result


def test_workspace_files_exist_and_public_demo_is_untouched():
    for name in (
        "index.html",
        "styles.css",
        "app.js",
        "api-adapter.js",
        "profile-adapter.js",
        "profile-review.js",
        "reconciliation-adapter.js",
        "favicon.svg",
    ):
        assert (WORKSPACE / name).is_file(), name

    assert sorted(path.name for path in extraction_fixtures()) == [
        "batch-completed.json",
        "batch-partial.json",
        "batch-rejected-too-large.json",
        "batch-rejected.json",
        "batch-status-coverage.json",
    ]
    assert (FIXTURES / "profile-synthetic.json").is_file()
    assert (FIXTURES / "profile-synthetic-recommendation.json").is_file()
    assert (FIXTURES / "profile-preview-source.json").is_file()
    assert (FIXTURES / "profile-invalid-samples.json").is_file()
    assert (FIXTURES / "profile-reconciliation-synthetic.json").is_file()
    assert (FIXTURES / "profile-reconciliation-source.json").is_file()

    # The public demo must keep its own entry points.
    assert (ROOT / "web" / "index.html").is_file()
    assert (ROOT / "web" / "app.js").is_file()
    assert (ROOT / "web" / "styles.css").is_file()


def test_workspace_html_has_no_inline_scripts_styles_or_remote_assets():
    html = read(WORKSPACE / "index.html")

    assert "style=" not in html
    assert re.search(r"<style\b", html) is None
    assert re.search(r"<script(?![^>]*\bsrc=)", html) is None
    assert "javascript:" not in html
    assert "onclick=" not in html
    assert "http://" not in html
    assert "https://" not in html

    assert './styles.css' in html
    assert './app.js' in html
    assert './api-adapter.js' in html


def test_every_id_used_by_app_js_exists_in_the_workspace_html():
    app = read(WORKSPACE / "app.js")
    html = read(WORKSPACE / "index.html")
    ids = set(re.findall(r'\$\("([^"]+)"\)', app))

    assert ids
    missing = sorted(name for name in ids if f'id="{name}"' not in html)
    assert missing == []


def test_app_js_avoids_inline_styles_and_raw_html_writes():
    app = read(WORKSPACE / "app.js")

    assert "innerHTML" not in app
    assert "outerHTML" not in app
    assert "insertAdjacentHTML" not in app
    assert "document.write" not in app
    assert re.search(r"\.style\s*[.=]", app) is None
    assert 'setAttribute("style"' not in app


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_workspace_javascript_parses():
    for name in ("app.js", "api-adapter.js", "profile-adapter.js", "profile-review.js"):
        result = subprocess.run(
            ["node", "--check", str(WORKSPACE / name)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def test_fixtures_follow_parser_schema_1_1_and_transport_1_0():
    for path in extraction_fixtures():
        payload = json.loads(read(path))

        assert payload["schema_version"] == SCHEMA_VERSION, path
        assert payload["transport_version"] == TRANSPORT_VERSION, path
        assert isinstance(payload["job_id"], str) and payload["job_id"], path
        assert isinstance(payload["documents"], list), path

        batch = payload["batch"]
        assert batch["status"] in BATCH_STATUSES, path
        assert isinstance(batch["total_bytes"], int) and batch["total_bytes"] >= 0, path

        counts = batch["status_counts"]
        assert set(counts) == PARSER_DOCUMENT_STATUSES, path
        assert all(isinstance(value, int) and value >= 0 for value in counts.values()), path

        limits = batch["limits"]
        assert set(limits) == LIMIT_KEYS, path
        assert all(isinstance(value, int) and value > 0 for value in limits.values()), path
        # The limits are the parser's ParseLimits defaults.
        assert limits["max_batch_bytes"] == 25 * 1024 * 1024, path
        assert limits["max_file_bytes"] == 10 * 1024 * 1024, path
        assert limits["max_documents"] == 5, path

        if batch["status"] == "rejected":
            # A rejected batch has no results and no processed counts, but it
            # keeps the number of documents that were submitted.
            assert payload["documents"] == [], path
            assert sum(counts.values()) == 0, path
            assert isinstance(batch["document_count"], int), path
            assert batch["document_count"] >= 0, path
            assert batch["error"]["code"] in BATCH_ERROR_CODES, path
            assert isinstance(batch["error"]["message"], str), path
        else:
            assert batch["error"] is None, path
            assert batch["document_count"] == len(payload["documents"]), path
            assert sum(counts.values()) == len(payload["documents"]), path


def test_a_rejected_fixture_keeps_the_submitted_document_count():
    payload = json.loads(read(FIXTURES / "batch-rejected-too-large.json"))
    batch = payload["batch"]

    assert batch["status"] == "rejected"
    assert batch["document_count"] == 3
    assert payload["documents"] == []
    assert sum(batch["status_counts"].values()) == 0
    assert batch["error"]["code"] == "batch_too_large"


def test_the_frontend_batch_limit_matches_the_parser_default():
    adapter = read(WORKSPACE / "api-adapter.js")

    # The workspace refuses an oversized batch before sending it, using the
    # same limit and the same code as the parser.
    assert "MAX_BATCH_BYTES = 25 * 1024 * 1024" in adapter
    assert '"batch_too_large"' in adapter


def test_fixture_documents_keep_their_identity_status_and_metadata():
    seen_statuses = set()

    for path in extraction_fixtures():
        payload = json.loads(read(path))
        seen_ids = set()

        for position, document in enumerate(payload["documents"]):
            assert isinstance(document["document_id"], str) and document["document_id"], path
            assert document["document_id"] not in seen_ids, path
            seen_ids.add(document["document_id"])

            assert document["index"] == position, path
            assert isinstance(document["filename"], str) and document["filename"], path
            assert document["format"] in DOCUMENT_FORMATS, path
            assert document["status"] in PARSER_DOCUMENT_STATUSES, path
            seen_statuses.add(document["status"])

            assert isinstance(document["text"], str), path
            assert isinstance(document["segments"], list), path
            assert isinstance(document["warnings"], list), path

            metadata = document["metadata"]
            assert isinstance(metadata["size_bytes"], int), path
            assert metadata["size_bytes"] >= 0, path
            for key in ("page_count", "paragraph_count"):
                value = metadata[key]
                assert value is None or (isinstance(value, int) and value >= 0), path

            # The parser text is exactly the concatenation of the segments.
            joined = "\n\n".join(segment["text"] for segment in document["segments"])
            assert document["text"] == joined, path

            if document["status"] in TEXT_STATUSES:
                assert document["segments"], f"{path}: {document['status']} needs text"
            else:
                assert document["text"] == "", f"{path}: {document['status']} returns no text"
                assert document["segments"] == [], f"{path}: {document['status']} has no segments"

            for warning in document["warnings"]:
                assert isinstance(warning["code"], str) and warning["code"], path
                assert isinstance(warning["message"], str) and warning["message"], path

            for segment in document["segments"]:
                assert isinstance(segment["text"], str), path
                locator = segment["locator"]
                if locator["kind"] == "page":
                    assert isinstance(locator["page"], int) and locator["page"] >= 1
                elif locator["kind"] == "paragraph":
                    assert (
                        isinstance(locator["paragraph"], int)
                        and locator["paragraph"] >= 1
                    )
                    section = locator.get("section")
                    assert section is None or isinstance(section, str)
                else:  # pragma: no cover - defensive
                    pytest.fail(f"{path}: unexpected locator kind {locator['kind']}")

    # The fixture set covers every parser document status.
    assert seen_statuses == PARSER_DOCUMENT_STATUSES


def test_fixtures_contain_no_real_world_contact_details():
    forbidden = (
        re.compile(r"\+\d{1,3}[\s.-]?\d{2,4}[\s.-]?\d{3,4}"),
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
        re.compile("linkedin" + r"[.]com", re.IGNORECASE),
    )
    for path in FIXTURES.glob("*.json"):
        text = read(path)
        for pattern in forbidden:
            assert not pattern.search(text), f"{pattern.pattern!r} in {path.name}"


def test_the_profile_fixture_follows_the_canonical_contract():
    payload = json.loads(read(FIXTURES / "profile-synthetic.json"))
    source = json.loads(read(FIXTURES / "profile-preview-source.json"))

    assert payload["profile_schema_version"] == PROFILE_SCHEMA_VERSION
    assert payload["parser_schema_version"] == SCHEMA_VERSION
    assert isinstance(payload["job_id"], str) and payload["job_id"]
    assert isinstance(payload["warnings"], list)
    assert isinstance(payload["documents"], list)
    assert isinstance(payload["proposals"], list) and payload["proposals"]
    assert isinstance(payload["conflicts"], list)

    documents = {document["document_id"]: document for document in source["documents"]}
    assert len(documents) >= 2, "the sample must show more than one source document"

    conflict_ids = {conflict["conflict_id"] for conflict in payload["conflicts"]}
    seen_categories = set()
    for proposal in payload["proposals"]:
        assert proposal["proposal_id"], proposal
        assert proposal["category"] in PROFILE_CATEGORIES, proposal
        seen_categories.add(proposal["category"])
        assert proposal["status"] in PROFILE_STATUSES, proposal

        value = proposal["value"]
        assert isinstance(value, dict) and value, proposal
        assert set(value) == PROFILE_VALUES[proposal["category"]], proposal
        if proposal["category"] == "education":
            assert value["level"] in DEGREE_LEVELS, proposal

        assert isinstance(proposal["evidence"], list) and proposal["evidence"], proposal
        assert isinstance(proposal["conflicts"], list), proposal
        for conflict_id in proposal["conflicts"]:
            assert conflict_id in conflict_ids, proposal

        for evidence in proposal["evidence"]:
            assert evidence["support"] in PROFILE_SUPPORT, proposal
            assert evidence["document_id"] in documents, proposal
            segment = documents[evidence["document_id"]]["segments"][
                evidence["segment_index"]
            ]
            # Python indices are code points, exactly like the contract.
            assert segment["text"][evidence["start"] : evidence["end"]] == evidence["quote"]

    assert seen_categories == PROFILE_CATEGORIES
    assert conflict_ids, "the sample must show a conflict"


def test_the_profile_source_fixture_is_a_valid_parser_response():
    source = json.loads(read(FIXTURES / "profile-preview-source.json"))

    assert source["schema_version"] == SCHEMA_VERSION
    assert source["transport_version"] == TRANSPORT_VERSION
    assert isinstance(source["job_id"], str) and source["job_id"]
    assert source["documents"], "the sample needs source documents"

    for document in source["documents"]:
        assert document["document_id"], document
        assert isinstance(document["segments"], list) and document["segments"], document
        for segment in document["segments"]:
            assert isinstance(segment["text"], str), document
            assert segment["locator"]["kind"] in {"page", "paragraph"}, document


def test_the_recommendation_fixture_carries_a_valid_backend_suggestion():
    payload = json.loads(read(FIXTURES / "profile-synthetic-recommendation.json"))
    canonical = json.loads(read(FIXTURES / "profile-synthetic.json"))

    assert payload["profile_schema_version"] == PROFILE_SCHEMA_VERSION
    assert payload["parser_schema_version"] == SCHEMA_VERSION
    # The recommendation fixture is the canonical envelope with one project
    # contradiction added, so it holds one proposal more.
    assert len(payload["proposals"]) == len(canonical["proposals"]) + 1

    hinted = [conflict for conflict in payload["conflicts"] if "resolution_hint" in conflict]
    assert hinted, "the fixture must show a suggestion"

    for conflict in hinted:
        hint = conflict["resolution_hint"]
        assert isinstance(hint["strategy"], str) and hint["strategy"]
        assert isinstance(hint["keep_proposal_ids"], list) and hint["keep_proposal_ids"]
        assert isinstance(hint["explanation"], str)
        assert isinstance(hint["requires_user_confirmation"], bool)
        # A suggestion may only speak about the proposals of its own conflict.
        for proposal_id in hint["keep_proposal_ids"]:
            assert proposal_id in conflict["proposal_ids"], conflict

    # The canonical envelope carries the suggestion of the engine itself.
    assert any(
        "resolution_hint" in conflict for conflict in canonical["conflicts"]
    )


def test_the_invalid_profile_samples_are_marked_and_broken():
    payload = json.loads(read(FIXTURES / "profile-invalid-samples.json"))

    assert "INVALID" in payload["note"].upper(), "the file must say it is invalid"
    assert payload["proposals"], "the file must show broken examples"

    source = json.loads(read(FIXTURES / "profile-preview-source.json"))
    documents = {document["document_id"]: document for document in source["documents"]}

    def evidence_of(proposal_id):
        proposal = next(
            item for item in payload["proposals"] if item["proposal_id"] == proposal_id
        )
        return proposal, proposal["evidence"]

    # A quotation that does not match the text.
    _, entries = evidence_of("prop_invalid_quote")
    segment = documents[entries[0]["document_id"]]["segments"][0]
    assert segment["text"][entries[0]["start"] : entries[0]["end"]] != entries[0]["quote"]

    # A reference that points at the wrong place.
    _, entries = evidence_of("prop_invalid_locator")
    segment = documents[entries[0]["document_id"]]["segments"][0]
    assert segment["text"][entries[0]["start"] : entries[0]["end"]] == entries[0]["quote"]
    assert entries[0]["locator"] != segment["locator"]

    # A document that is not loaded.
    _, entries = evidence_of("prop_invalid_document")
    assert entries[0]["document_id"] not in documents

    # A block that does not exist.
    _, entries = evidence_of("prop_invalid_segment")
    document = documents[entries[0]["document_id"]]
    assert entries[0]["segment_index"] >= len(document["segments"])

    # A proposal without evidence.
    proposal, entries = evidence_of("prop_invalid_no_evidence")
    assert entries == []

    # A conflict the response does not contain.
    proposal, _ = evidence_of("prop_invalid_unknown_conflict")
    assert proposal["conflicts"] == ["conf_does_not_exist"]

    # A suggestion that names a proposal of another conflict.
    malformed = next(
        conflict
        for conflict in payload["conflicts"]
        if conflict["conflict_id"] == "conf_malformed_hint"
    )
    hint = malformed["resolution_hint"]
    assert hint["keep_proposal_ids"] == ["prop_not_in_this_conflict"]
    for proposal_id in hint["keep_proposal_ids"]:
        assert proposal_id not in malformed["proposal_ids"]


def test_the_profile_request_only_sends_the_two_accepted_top_level_keys():
    adapter = read(WORKSPACE / "profile-adapter.js")
    request_block = adapter.split("function buildProfileRequest", 1)[1].split(
        "class CvProfileAdapter", 1
    )[0]

    # The endpoint refuses any other top-level key with HTTP 400.
    for forbidden in ("transport_version", "schema_version", "batch:"):
        assert forbidden not in request_block, forbidden

    assert "job_id" in request_block
    assert "documents" in request_block


def test_the_reconciliation_example_covers_several_documents_and_categories():
    envelope = json.loads(read(FIXTURES / "profile-reconciliation-synthetic.json"))
    source = json.loads(read(FIXTURES / "profile-reconciliation-source.json"))

    assert envelope["profile_schema_version"] == PROFILE_SCHEMA_VERSION
    assert envelope["parser_schema_version"] == SCHEMA_VERSION
    assert len(source["documents"]) >= 3, "the example needs several CVs"
    assert len(envelope["proposals"]) >= 15, "the example needs many statements"

    documents = {document["document_id"]: document for document in source["documents"]}
    categories = {proposal["category"] for proposal in envelope["proposals"]}
    assert categories == PROFILE_CATEGORIES

    # Several statements are supported by more than one document.
    multi = [
        proposal
        for proposal in envelope["proposals"]
        if len({reference["document_id"] for reference in proposal["evidence"]}) > 1
    ]
    assert multi, "the example needs a statement with several sources"

    for proposal in envelope["proposals"]:
        for evidence in proposal["evidence"]:
            segment = documents[evidence["document_id"]]["segments"][
                evidence["segment_index"]
            ]
            assert segment["text"][evidence["start"] : evidence["end"]] == evidence["quote"]


def test_the_workspace_never_persists_or_exfiltrates_review_data():
    for name in (
        "app.js",
        "api-adapter.js",
        "profile-adapter.js",
        "profile-review.js",
        "reconciliation-adapter.js",
    ):
        text = read(WORKSPACE / name)
        for marker in (r"(?:window\.)?localStorage\s*[.\[]", r"(?:window\.)?sessionStorage\s*[.\[]", r"indexedDB\s*[.\[]", r"sendBeacon\s*\("):
            assert not re.search(marker, text), f"{marker} in {name}"
        # No absolute origin: every request stays on the configured base.
        assert "http://" not in text, name
        assert "https://" not in text, name


def test_preview_server_serves_only_the_workspace(server_port):
    port = server_port

    status, headers, html = request(port, "GET", "/workspace/")
    assert status == 200
    assert b"CV evidence workspace" in html
    assert b"./api-adapter.js" in html
    assert headers["Cache-Control"] == "no-store"
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert headers["X-Content-Type-Options"] == "nosniff"

    status, _, css = request(port, "GET", "/workspace/styles.css")
    assert status == 200
    assert b":" in css

    status, _, script = request(port, "GET", "/workspace/app.js")
    assert status == 200
    assert b"use strict" in script

    status, _, adapter = request(port, "GET", "/workspace/api-adapter.js")
    assert status == 200
    assert b"CONTRACT_VERSION" in adapter
    assert b'SCHEMA_VERSION = "1.1"' in adapter
    assert b'TRANSPORT_VERSION = "1.0"' in adapter

    status, _, fixture = request(port, "GET", "/workspace/fixtures/batch-completed.json")
    assert status == 200
    payload = json.loads(fixture)
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["batch"]["status"] == "completed"


def test_preview_server_does_not_serve_the_public_demo(server_port):
    port = server_port

    status, headers, _ = request(port, "GET", "/")
    assert status == 302
    assert headers["Location"] == "/workspace/"

    for path in (
        "/web/index.html",
        "/web/app.js",
        "/index.html",
        "/workspace/../index.html",
        "/workspace/%2e%2e/index.html",
        "/etc/hosts",
    ):
        status, _, body = request(port, "GET", path)
        assert status == 404, path
        assert json.loads(body)["error"]["code"] == "not_found"


def test_preview_server_refuses_extraction_instead_of_faking_it(server_port):
    port = server_port

    for method, path in (
        ("GET", "/api/cv/extractions/job-1"),
        ("POST", "/api/cv/extractions"),
        ("GET", "/api/cv"),
    ):
        status, headers, body = request(port, method, path, body=b"files=ignored")
        assert status == 503, path
        payload = json.loads(body)
        assert payload["error"]["code"] == "parser_unavailable"
        assert "job_id" not in body.decode()
        assert "documents" not in body.decode()
        assert headers["Content-Type"].startswith("application/json")


def test_preview_server_rejects_unsupported_methods(server_port):
    status, _, body = request(server_port, "PUT", "/workspace/index.html")
    assert status == 405
    assert json.loads(body)["error"]["code"] == "method_not_allowed"


def test_preview_server_head_requests_have_no_body(server_port):
    status, headers, body = request(server_port, "HEAD", "/workspace/index.html")
    assert status == 200
    assert body == b""
    assert int(headers["Content-Length"]) > 0


def test_workspace_docs_describe_the_provisional_contract_and_isolation():
    contract = read(ROOT / "docs" / "cv-workspace-contract.md")
    guide = read(ROOT / "docs" / "cv-workspace.md")

    for phrase in (
        "POST {base}/extractions",
        "GET {base}/extractions/{job_id}",
        "needs_review",
        "1-based",
        "schema_version",
        "transport_version",
        "document_id",
    ):
        assert phrase in contract, phrase

    for phrase in (
        "web/workspace",
        "parser_unavailable",
        "Integration requirements",
        "non-goal",
    ):
        assert phrase in guide, phrase
