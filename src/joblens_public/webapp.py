"""Loopback-only web server for the public JobLens demo.

The browser sends a synthetic posting to this process. Python performs the
skill triage and evidence matching; no report is precomputed in JavaScript.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .core.real_fit import evaluate_real_fit
from .data import public_candidates, public_jobs

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"
MAX_BODY = 65_536
REQUEST_TIMEOUT = 5.0

ASSETS: dict[str, tuple[str, str]] = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/assets/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}


def validate_job_request(payload: Any) -> dict[str, str]:
    """Reject invalid fields instead of silently coercing browser input."""
    if not isinstance(payload, dict):
        raise ValueError("Job must be a JSON object")
    limits = {"title": 160, "company": 120, "location": 160, "description": 50_000}
    result: dict[str, str] = {}
    for key, maximum in limits.items():
        value = payload.get(key, "")
        if not isinstance(value, str) or len(value) > maximum:
            raise ValueError(f"{key} must be a string of at most {maximum} characters")
        result[key] = value.strip()
        try:
            result[key].encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError(f"{key} must be valid UTF-8") from error
    if not result["description"]:
        raise ValueError("Paste a nonempty job description")
    return result


def make_handler(
    candidates: dict[str, dict[str, Any]],
    jobs: dict[str, dict[str, Any]],
) -> type[BaseHTTPRequestHandler]:
    """Factory keeps the synthetic banks inside the loopback process."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "JobLensPublic/1.0"
        sys_version = ""
        timeout = REQUEST_TIMEOUT

        def log_message(self, format: str, *args: Any) -> None:
            # Request metadata can contain pasted text; keep the terminal quiet.
            pass

        def _host_ok(self) -> bool:
            port = self.server.server_port
            return (
                self.client_address[0] == "127.0.0.1"
                and self.headers.get("Host") in
                {f"127.0.0.1:{port}", f"localhost:{port}"}
            )

        def _send(self, status: int, data: bytes, kind: str) -> None:
            try:
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")
                self.send_header(
                    "Permissions-Policy",
                    "camera=(), microphone=(), geolocation=()",
                )
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'none'; script-src 'self'; style-src 'self'; "
                    "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
                    "form-action 'self'; frame-ancestors 'none'",
                )
                self.end_headers()
                self.wfile.write(data)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

        def _json(self, status: int, obj: dict[str, Any]) -> None:
            self._send(
                status,
                json.dumps(obj, ensure_ascii=True).encode("utf-8"),
                "application/json; charset=utf-8",
            )

        def _bootstrap(self) -> dict[str, Any]:
            return {
                "candidates": public_candidates(candidates),
                "jobs": public_jobs(jobs),
                "meta": {
                    "mode": "local",
                    "evaluator": "python",
                    "synthetic": True,
                    "candidate_count": len(candidates),
                    "job_count": len(jobs),
                },
            }

        def do_GET(self) -> None:
            if not self._host_ok():
                self._json(403, {"error": "Localhost access only"})
                return
            path = urlparse(self.path).path
            if path == "/api/status":
                self._json(200, {
                    "mode": "local",
                    "evaluator": "python",
                    "synthetic": True,
                    "ready": True,
                    "candidates": len(candidates),
                    "jobs": len(jobs),
                })
                return
            if path == "/api/bootstrap":
                self._json(200, self._bootstrap())
                return
            asset = ASSETS.get(path)
            if asset is None:
                self._json(404, {"error": "Not found"})
                return
            filename, kind = asset
            self._send(200, (WEB_DIR / filename).read_bytes(), kind)

        def do_POST(self) -> None:
            if not self._host_ok():
                self._json(403, {"error": "Localhost access only"})
                return
            origin = self.headers.get("Origin")
            valid_origins = {
                f"http://127.0.0.1:{self.server.server_port}",
                f"http://localhost:{self.server.server_port}",
            }
            if origin not in valid_origins or self.headers.get("X-JobLens-Request") != "1":
                self._json(403, {"error": "Invalid origin or request token"})
                return
            if urlparse(self.path).path != "/api/analyze":
                self._json(404, {"error": "Not found"})
                return
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                self._json(415, {"error": "Expected application/json"})
                return
            raw_size = self.headers.get("Content-Length", "")
            if not raw_size.isascii() or not raw_size.isdecimal():
                self._json(411, {"error": "Content-Length required"})
                return
            try:
                size = int(raw_size)
            except ValueError:
                self._json(400, {"error": "Invalid Content-Length"})
                return
            if size > MAX_BODY:
                self.close_connection = True
                self._json(413, {"error": "Posting too large"})
                return
            try:
                raw = self.rfile.read(size)
            except TimeoutError:
                self.close_connection = True
                self._json(408, {"error": "Request timed out"})
                return
            except ConnectionError:
                self.close_connection = True
                return
            try:
                body = json.loads(raw)
                if not isinstance(body, dict):
                    raise ValueError("Request must be a JSON object")
                candidate_id = body.get("candidate_id")
                if not isinstance(candidate_id, str) or candidate_id not in candidates:
                    raise ValueError("Select a valid fictional candidate")
                posting = validate_job_request(body.get("job"))
                report = evaluate_real_fit(candidates[candidate_id]["bank"], posting)
            except UnicodeError:
                self._json(400, {"error": "Request body must be valid UTF-8"})
                return
            except json.JSONDecodeError:
                self._json(400, {"error": "Request body must be valid JSON"})
                return
            except ValueError as error:
                self._json(400, {"error": str(error)[:200]})
                return
            selected = candidates[candidate_id]
            self._json(200, {
                "report": report,
                "candidate": {
                    "id": selected["id"],
                    "name": selected["name"],
                    "headline": selected["headline"],
                },
                "evaluator": "python",
                "synthetic": True,
            })

        def do_OPTIONS(self) -> None:
            self._json(403, {"error": "Cross-origin requests are disabled"})

    return Handler


def create_server(
    candidates: dict[str, dict[str, Any]],
    jobs: dict[str, dict[str, Any]],
    port: int = 0,
) -> ThreadingHTTPServer:
    if not 0 <= port <= 65_535:
        raise ValueError("Port must be between 0 and 65535")
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(candidates, jobs))
