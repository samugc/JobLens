import http.client
import json
import socket
import threading

import pytest

from joblens_public.data import load_demo_data
from joblens_public.webapp import MAX_BODY, create_server


@pytest.fixture
def web_server():
    candidates, jobs = load_demo_data()
    server = create_server(candidates, jobs, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_port
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def request(port, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    raw = response.read()
    result = (response.status, response.headers, raw)
    connection.close()
    return result


def json_headers(port):
    return {
        "Content-Type": "application/json",
        "Origin": f"http://127.0.0.1:{port}",
        "X-JobLens-Request": "1",
    }


def analyze(port, candidate_id, job):
    body = json.dumps({"candidate_id": candidate_id, "job": job}).encode()
    status, headers, raw = request(
        port, "POST", "/api/analyze", body, json_headers(port)
    )
    return status, headers, raw


def test_ui_and_assets_are_served(web_server):
    port = web_server
    status, headers, html = request(port, "GET", "/")
    assert status == 200
    assert b"JobLens" in html
    assert b"Analyze evidence" in html
    assert b"/assets/app.js" in html
    assert "no-store" in headers.get("Cache-Control")
    assert "script-src 'self'" in headers.get("Content-Security-Policy")

    status, _, css = request(port, "GET", "/assets/styles.css")
    assert status == 200
    assert b"--accent" in css
    status, _, js = request(port, "GET", "/assets/app.js")
    assert status == 200
    assert b"/api/analyze" in js


def test_bootstrap_exposes_metadata_and_postings_not_the_bank(web_server):
    port = web_server
    status, _, raw = request(port, "GET", "/api/bootstrap")
    assert status == 200
    payload = json.loads(raw)
    assert len(payload["candidates"]) == 2
    assert len(payload["jobs"]) == 3
    assert payload["meta"] == {
        "mode": "local",
        "evaluator": "python",
        "synthetic": True,
        "candidate_count": 2,
        "job_count": 3,
    }
    serialized = json.dumps(payload)
    assert "attested_by_user" not in serialized
    assert '"facts"' not in serialized
    assert '"bank"' not in serialized


def test_browser_endpoint_calls_the_real_python_evaluator(web_server):
    port = web_server
    candidates, jobs = load_demo_data()
    job = jobs["junior-ai-engineer-aster"]

    status, headers, raw = analyze(port, "alex-rivera", job)
    assert status == 200
    assert "no-store" in headers.get("Cache-Control")
    payload = json.loads(raw)
    assert payload["evaluator"] == "python"
    assert payload["candidate"]["name"] == "Alex Rivera"
    assert payload["report"]["required_coverage"]["documented"] == 5

    status, _, raw = analyze(port, "jordan-lee", job)
    assert status == 200
    payload = json.loads(raw)
    assert payload["report"]["required_coverage"]["documented"] == 2
    assert payload["report"]["fit_assessment"]["status"] == "EVIDENCE_GAPS"


def test_invalid_candidate_and_empty_description_are_rejected(web_server):
    port = web_server
    _, jobs = load_demo_data()
    job = jobs["data-analyst-harbor"]
    status, _, raw = analyze(port, "not-a-candidate", job)
    assert status == 400
    assert "valid fictional candidate" in json.loads(raw)["error"]

    empty = dict(job)
    empty["description"] = ""
    status, _, raw = analyze(port, "alex-rivera", empty)
    assert status == 400
    assert "nonempty" in json.loads(raw)["error"]


def test_cross_origin_and_missing_token_are_rejected(web_server):
    port = web_server
    _, jobs = load_demo_data()
    body = json.dumps({
        "candidate_id": "alex-rivera",
        "job": jobs["junior-ai-engineer-aster"],
    }).encode()
    status, _, _ = request(port, "POST", "/api/analyze", body, {
        "Content-Type": "application/json",
        "Origin": "https://example.net",
        "X-JobLens-Request": "1",
    })
    assert status == 403
    status, _, _ = request(port, "POST", "/api/analyze", body, {
        "Content-Type": "application/json",
        "Origin": f"http://127.0.0.1:{port}",
    })
    assert status == 403
    status, _, _ = request(port, "GET", "/", headers={"Host": "evil.example"})
    assert status == 403
    status, _, _ = request(port, "GET", "/api/unknown")
    assert status == 404
    status, _, _ = request(port, "OPTIONS", "/api/analyze")
    assert status == 403


def test_malformed_and_invalid_unicode_bodies_return_json_errors(web_server):
    port = web_server
    headers = json_headers(port)
    candidates, jobs = load_demo_data()

    malformed = b'{"candidate_id": "alex-rivera", "job": '
    status, _, raw = request(port, "POST", "/api/analyze", malformed, headers)
    assert status == 400
    assert "valid JSON" in json.loads(raw)["error"]

    invalid_utf8 = (
        b'{"candidate_id":"alex-rivera","job":{"title":"x","company":"x",'
        b'"location":"x","description":"\xff"}}'
    )
    status, _, raw = request(port, "POST", "/api/analyze", invalid_utf8, headers)
    assert status == 400
    assert "valid UTF-8" in json.loads(raw)["error"]

    body = json.dumps({
        "candidate_id": "alex-rivera",
        "job": {**jobs["data-analyst-harbor"], "description": "\ud800"},
    }).encode()
    status, _, raw = request(port, "POST", "/api/analyze", body, headers)
    assert status == 400
    assert "valid UTF-8" in json.loads(raw)["error"]

    oversized = b"x" * (MAX_BODY + 1)
    status, _, raw = request(port, "POST", "/api/analyze", oversized, headers)
    assert status == 413
    assert "too large" in json.loads(raw)["error"]


def test_incomplete_request_times_out_without_holding_a_thread():
    candidates, jobs = load_demo_data()
    server = create_server(candidates, jobs, 0)
    server.RequestHandlerClass.timeout = 0.2
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
            connection.sendall(
                (
                    "POST /api/analyze HTTP/1.1\r\n"
                    f"Host: 127.0.0.1:{port}\r\n"
                    f"Origin: http://127.0.0.1:{port}\r\n"
                    "X-JobLens-Request: 1\r\n"
                    "Content-Type: application/json\r\n"
                    "Content-Length: 100\r\n\r\n"
                ).encode()
            )
            connection.sendall(b'{"candidate_id": "alex-rivera", "job": {')
            connection.settimeout(2)
            response = b""
            while True:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                response += chunk
        assert b"408" in response
        assert b"Request timed out" in response
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_frontend_invalidates_stale_reports_and_shows_claim_text(web_server):
    _, _, raw = request(web_server, "GET", "/assets/app.js")
    javascript = raw.decode("utf-8")
    assert "function invalidateReport" in javascript
    assert "analysisRevision" in javascript
    assert 'addEventListener("input", invalidateReport)' in javascript
    assert "reference.claim" in javascript
