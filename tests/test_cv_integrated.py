"""Integration-only regressions using synthetic inputs and real local HTTP."""
import os
import subprocess
import sys
from pathlib import Path

import test_cv_mount
from cv_builders import make_docx, make_pdf
from test_cv_mount import post_cv, request

app_server = test_cv_mount.app_server
ROOT = Path(__file__).resolve().parents[1]


def test_real_workspace_adapter_against_mounted_parser(app_server, tmp_path):
    pdf = tmp_path / 'synthetic.pdf'
    docx = tmp_path / 'synthetic.docx'
    pdf.write_bytes(make_pdf([['INTEGRATION-SYNTHETIC-MARKER', 'Experience'], ['Education']]))
    docx.write_bytes(make_docx([('Experience', 'Heading1'), ('Synthetic evidence', None),
                                ('Education', 'Heading1'), ('Synthetic course', None)]))
    completed = subprocess.run(
        ['node', str(ROOT / 'tests/ui/cv-integrated-http.mjs'),
         f'http://127.0.0.1:{app_server.server_port}', str(pdf), str(docx)],
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_real_workspace_assets_are_present(app_server):
    status, _, body = request(app_server.server_port, 'GET', '/workspace/')
    assert status == 200
    assert body == (ROOT / 'web/workspace/index.html').read_bytes()


def test_mount_rejects_wrong_token(app_server):
    status, _, _ = post_cv(app_server.server_port,
                          [('files', 'synthetic.pdf', make_pdf([['Synthetic']]))],
                          headers={'X-JobLens-Request': 'wrong'})
    assert status == 403


def test_absent_dependency_keeps_demo_available():
    # -S really excludes site-packages, rather than mocking the parser result.
    # Keep the child stdlib-only and give every wait a bounded timeout so a
    # macOS scheduling stall produces diagnostics instead of an opaque timeout.
    code = '''
import faulthandler, http.client, importlib.util, json, threading
faulthandler.dump_traceback_later(45, exit=True)

def stage(name):
    print(f"[joblens-ci] {name}", flush=True)

stage("checking-pypdf")
assert importlib.util.find_spec("pypdf") is None

stage("importing-app")
from joblens_public.data import load_demo_data
from joblens_public.webapp import create_server

def request(port, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=15.0)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()

def post_cv(port, files):
    body = b'--synthetic\\r\\nContent-Disposition: form-data; name="files"; filename="synthetic.pdf"\\r\\n\\r\\n%PDF-synthetic\\r\\n--synthetic--\\r\\n'
    return request(port, "POST", "/api/cv/extractions", body, {
        "Origin": f"http://127.0.0.1:{port}", "X-JobLens-Request": "1",
        "Content-Type": "multipart/form-data; boundary=synthetic"})

stage("creating-server")
server = create_server(*load_demo_data(), 0)
t = threading.Thread(target=server.serve_forever, daemon=True)
stage("starting-server")
t.start()
cleanup_problem = None
try:
    stage("request-root")
    assert request(server.server_port, "GET", "/")[0] == 200
    stage("request-workspace")
    assert request(server.server_port, "GET", "/workspace/")[0] == 200
    stage("request-extraction")
    status, _, raw = post_cv(server.server_port, [("files", "synthetic.pdf", b"%PDF-synthetic")])
    stage("assert-extraction")
    assert status == 503, (status, raw)
    assert json.loads(raw)["error"]["code"] == "parser_unavailable"
finally:
    stage("cleanup-start")
    stopper = threading.Thread(target=server.shutdown, daemon=True)
    stopper.start()
    stopper.join(timeout=5)
    server.server_close()
    t.join(timeout=5)
    if stopper.is_alive():
        cleanup_problem = "server.shutdown() did not finish within 5s"
    if t.is_alive():
        cleanup_problem = (cleanup_problem + "; " if cleanup_problem else "") + "server thread did not stop within 5s"
    stage("cleanup-complete")
if cleanup_problem:
    raise RuntimeError(cleanup_problem)
'''
    try:
        result = subprocess.run(
            [sys.executable, '-S', '-c', code],
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')},
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or ''
        stderr = error.stderr or ''
        if isinstance(stdout, bytes):
            stdout = stdout.decode('utf-8', 'replace')
        if isinstance(stderr, bytes):
            stderr = stderr.decode('utf-8', 'replace')
        raise AssertionError(
            'No-parser child process timed out after 60s.\\n'
            f'stdout:\\n{stdout}\\nstderr:\\n{stderr}'
        ) from error
    assert result.returncode == 0, (
        f'No-parser child process exited {result.returncode}.\\n'
        f'stdout:\\n{result.stdout}\\nstderr:\\n{result.stderr}'
    )


def test_mounted_size_limits(app_server):
    import json

    from joblens_public.cv_parser.http_transport import max_body_bytes

    port = app_server.server_port
    # No oversized body is sent: the declared size must be rejected before reading.
    status, _, raw = request(port, 'POST', '/api/cv/extractions', b'', {
        'Origin': f'http://127.0.0.1:{port}', 'X-JobLens-Request': '1',
        'Content-Type': 'multipart/form-data; boundary=synthetic',
        'Content-Length': str(max_body_bytes() + 1),
    })
    assert status == 413
    assert json.loads(raw)['error']['code'] == 'request_too_large'
    # Under transport cap, above parser aggregate cap: canonical rejected envelope.
    chunk = b'x' * (9 * 1024 * 1024)
    status, _, raw = post_cv(port, [('files', 'one.pdf', chunk),
                                   ('files', 'two.pdf', chunk),
                                   ('files', 'three.pdf', b'x' * (7 * 1024 * 1024 + 1))])
    payload = json.loads(raw)
    assert status == 413
    assert payload['error']['code'] == 'batch_too_large'
    assert payload['batch']['document_count'] == 3
    assert payload['documents'] == []
    status, _, raw = post_cv(port, [('files', 'large.pdf', b'x' * (10 * 1024 * 1024 + 1))])
    assert status == 200
    assert json.loads(raw)['documents'][0]['status'] == 'too_large'
