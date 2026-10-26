"""Loopback-only web server for the public JobLens demo.

The browser sends a synthetic posting to this process. Python performs the
skill triage and evidence matching; no report is precomputed in JavaScript.

The same process also serves the local CV parser on
``POST /api/cv/extractions``, the candidate profile engine on
``POST /api/cv/profiles`` and the approved CV workspace assets under
``/workspace/``. Both CV routes are mounted from the parser's own modules, so
the browser keeps talking to a single origin and no CORS header is needed.
The demo routes are unchanged.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .core.real_fit import evaluate_real_fit
from .cv import (
    CvDraft,
    generate_cv_draft,
)
from .cv_parser.http_transport import DEFAULT_LIMITS as CV_LIMITS
from .cv_parser.http_transport import EXTRACTION_PATH as CV_EXTRACTION_PATH
from .cv_parser.http_transport import (
    ExtractionGate,
    TransportError,
    default_extract_fn,
    error_payload,
    new_job_id,
    serve_extraction_request,
)
from .data import public_candidates, public_jobs
from .decisions import build_decision_report, trace_from_approved_profile
from .jobs import parse_job_posting
from .profile import (
    PARSER_SCHEMA_VERSION,
    PROFILE_SCHEMA_VERSION,
    build_profile_proposals,
)
from .profile.approved import (
    ApprovedProfileError,
    validate_approved_profile,
)
from .provisional import draft_from_source
from .reconcile import RECONCILIATION_SCHEMA_VERSION, reconcile_documents
from .release_guard import ReviewGuard, ReviewValidationError

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"
MAX_BODY = 65_536
REQUEST_TIMEOUT = 5.0
CV_MAX_CONCURRENT = 2

# The profile route carries the extracted source documents as JSON. The parser
# allows 200,000 characters per document and five documents per batch, so the
# body is bounded well above that, and well below the multipart limit of the
# extraction route.
PROFILE_MAX_BODY = 8 * 1024 * 1024
PROFILE_MAX_DOCUMENTS = 5
PROFILE_PATH = "/api/cv/profiles"
RECONCILIATION_PATH = "/api/cv/reconciliations"
JOBS_PATH = "/api/cv/jobs"
APPROVED_PROFILES_PATH = "/api/cv/approved-profiles"
CV_DRAFTS_PATH = "/api/cv/cv-drafts"
CV_DRAFT_EDIT_PATH = "/api/cv/cv-drafts/edit"
CV_DRAFT_APPROVE_PATH = "/api/cv/cv-drafts/approve"
CV_EXPORT_PDF_PATH = "/api/cv/cv-drafts/export/pdf"
CV_EXPORT_DOCX_PATH = "/api/cv/cv-drafts/export/docx"

ASSETS: dict[str, tuple[str, str]] = {
    "/": ("simple.html", "text/html; charset=utf-8"),
    "/index.html": ("simple.html", "text/html; charset=utf-8"),
    "/assets/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
    "/demo/": ("index.html", "text/html; charset=utf-8"),
    "/simple.js": ("simple.js", "text/javascript; charset=utf-8"),
    "/simple.css": ("simple.css", "text/css; charset=utf-8"),
    # Synthetic, clearly fictional documents used by the "Try a sample"
    # action. They go through the same extraction and draft pipeline as a
    # user upload; no generated result is shipped here.
    "/samples/alex-rivera-cv.pdf": ("samples/alex-rivera-cv.pdf", "application/pdf"),
    "/samples/alex-rivera-cv-2.docx": (
        "samples/alex-rivera-cv-2.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
}

# The CV workspace bundle is assembled in a separate worktree and is not part
# of this checkout yet. Only these files may ever be served: the request path
# is matched exactly, so `/workspace/fixtures/...`, source files and traversal
# paths can never reach the filesystem.
WORKSPACE_DIR_NAME = "workspace"
WORKSPACE_PREFIX = f"/{WORKSPACE_DIR_NAME}/"
WORKSPACE_ASSETS: dict[str, tuple[str, str]] = {
    f"{WORKSPACE_PREFIX}": ("index.html", "text/html; charset=utf-8"),
    f"{WORKSPACE_PREFIX}index.html": ("index.html", "text/html; charset=utf-8"),
    f"{WORKSPACE_PREFIX}app.js": ("app.js", "text/javascript; charset=utf-8"),
    f"{WORKSPACE_PREFIX}api-adapter.js": (
        "api-adapter.js",
        "text/javascript; charset=utf-8",
    ),
    f"{WORKSPACE_PREFIX}styles.css": ("styles.css", "text/css; charset=utf-8"),
    f"{WORKSPACE_PREFIX}favicon.svg": ("favicon.svg", "image/svg+xml"),
    f"{WORKSPACE_PREFIX}profile-adapter.js": (
        "profile-adapter.js",
        "text/javascript; charset=utf-8",
    ),
    f"{WORKSPACE_PREFIX}profile-review.js": (
        "profile-review.js",
        "text/javascript; charset=utf-8",
    ),
    f"{WORKSPACE_PREFIX}reconciliation-adapter.js": (
        "reconciliation-adapter.js", "text/javascript; charset=utf-8",
    ),
    f"{WORKSPACE_PREFIX}tailor-adapter.js": (
        "tailor-adapter.js", "text/javascript; charset=utf-8",
    ),
}


def validate_profile_request(payload: Any) -> tuple[str, list[dict[str, Any]]]:
    """Validate a candidate profile request.

    The request carries the extracted source documents, not review decisions:
    only ``job_id`` and ``documents`` are accepted at the top level, so a
    client can never present an approval as authoritative.

    Returns the job id and the documents in the shape the profile engine
    expects. Raises ``ValueError`` with a fixed message when the request is
    not valid.
    """
    if not isinstance(payload, dict):
        raise ValueError("The request body must be a JSON object")
    unexpected = sorted(set(payload) - {"job_id", "documents"})
    if unexpected:
        raise ValueError(f"Unexpected field: {unexpected[0]}")
    job_id = payload.get("job_id")
    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("job_id must be a non-empty string")
    documents = payload.get("documents")
    if not isinstance(documents, list):
        raise ValueError("documents must be an array")
    if not documents:
        raise ValueError("documents must contain at least one document")
    if len(documents) > PROFILE_MAX_DOCUMENTS:
        raise ValueError(
            f"documents must contain at most {PROFILE_MAX_DOCUMENTS} documents"
        )

    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for position, document in enumerate(documents):
        if not isinstance(document, dict):
            raise ValueError(f"documents[{position}] must be an object")
        document_id = document.get("document_id")
        if not isinstance(document_id, str) or not document_id.strip():
            raise ValueError(
                f"documents[{position}].document_id must be a non-empty string"
            )
        if document_id in seen:
            raise ValueError(f"documents[{position}].document_id is duplicated")
        seen.add(document_id)
        index = document.get("index")
        if not isinstance(index, int) or isinstance(index, bool) or index != position:
            raise ValueError(
                f"documents[{position}].index must equal the document position"
            )
        filename = document.get("filename")
        if not isinstance(filename, str):
            raise ValueError(f"documents[{position}].filename must be a string")
        status = document.get("status")
        if not isinstance(status, str) or not status.strip():
            raise ValueError(f"documents[{position}].status must be a non-empty string")
        document_format = document.get("format")
        if not isinstance(document_format, str):
            raise ValueError(f"documents[{position}].format must be a string")
        segments = document.get("segments")
        if not isinstance(segments, list):
            raise ValueError(f"documents[{position}].segments must be an array")
        cleaned_segments: list[dict[str, Any]] = []
        for segment_index, segment in enumerate(segments):
            if not isinstance(segment, dict):
                raise ValueError(
                    f"documents[{position}].segments[{segment_index}] must be an object"
                )
            text = segment.get("text")
            if not isinstance(text, str):
                raise ValueError(
                    f"documents[{position}].segments[{segment_index}].text "
                    "must be a string"
                )
            locator = segment.get("locator")
            if not isinstance(locator, dict):
                raise ValueError(
                    f"documents[{position}].segments[{segment_index}].locator "
                    "must be an object"
                )
            cleaned_segments.append({"locator": dict(locator), "text": text})
        validated.append(
            {
                "document_id": document_id,
                "index": index,
                "filename": filename,
                "status": status,
                "format": document_format,
                "segments": cleaned_segments,
            }
        )
    return job_id, validated


def profile_error(code: str, message: str, job_id: str | None = None) -> dict[str, Any]:
    """Build the error body of the profile route."""
    return {
        "profile_schema_version": PROFILE_SCHEMA_VERSION,
        "parser_schema_version": PARSER_SCHEMA_VERSION,
        "job_id": job_id,
        "error": {"code": code, "message": message},
    }


def reconciliation_error(code: str, message: str, job_id: str | None = None) -> dict[str, Any]:
    """Build the error body of the reconciliation route."""
    return {
        "reconciliation_schema_version": RECONCILIATION_SCHEMA_VERSION,
        "parser_schema_version": PARSER_SCHEMA_VERSION,
        "job_id": job_id,
        "error": {"code": code, "message": message},
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

    # The CV transport owns the extraction rules. The application only lends
    # it the socket, the origin checks and the response writer.
    review_guard = ReviewGuard()
    cv_gate = ExtractionGate(CV_MAX_CONCURRENT)
    cv_extract = default_extract_fn(CV_LIMITS)

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

        def _send(
            self,
            status: int,
            data: bytes,
            kind: str,
            extra: dict[str, str] | None = None,
        ) -> None:
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
                for name, value in (extra or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(data)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

        def _json(
            self,
            status: int,
            obj: dict[str, Any],
            extra: dict[str, str] | None = None,
        ) -> None:
            self._send(
                status,
                json.dumps(obj, ensure_ascii=True).encode("utf-8"),
                "application/json; charset=utf-8",
                extra,
            )

        def _redirect(self, location: str) -> None:
            self._send(302, b"", "text/plain; charset=utf-8", {"Location": location})

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
            if path == f"/{WORKSPACE_DIR_NAME}":
                self._redirect(f"{WORKSPACE_PREFIX}")
                return
            if path.startswith(WORKSPACE_PREFIX):
                self._workspace(path)
                return
            if path == CV_EXTRACTION_PATH:
                self._json(
                    405,
                    error_payload("method_not_allowed", None, new_job_id()),
                    {"Allow": "POST"},
                )
                return
            if path == PROFILE_PATH:
                self._json(405, profile_error("method_not_allowed", "Use POST for this endpoint."),
                           {"Allow": "POST"})
                return
            if path == RECONCILIATION_PATH:
                self._json(405, reconciliation_error("method_not_allowed", "Use POST for this endpoint."),
                           {"Allow": "POST"})
                return
            if path in (JOBS_PATH, APPROVED_PROFILES_PATH, CV_DRAFTS_PATH, CV_DRAFT_EDIT_PATH,
                        CV_DRAFT_APPROVE_PATH, CV_EXPORT_PDF_PATH, CV_EXPORT_DOCX_PATH):
                self._json(405, {"error": {"code": "method_not_allowed", "message": "Use POST for this endpoint."}},
                           {"Allow": "POST"})
                return
            if path.startswith(f"{CV_EXTRACTION_PATH}/"):
                self._json(404, error_payload("job_not_found", None, new_job_id()))
                return
            asset = ASSETS.get(path)
            if asset is None:
                self._json(404, {"error": "Not found"})
                return
            filename, kind = asset
            self._send(200, (WEB_DIR / filename).read_bytes(), kind)

        def _workspace(self, path: str) -> None:
            """Serve the approved CV workspace assets only.

            The bundle lives in a separate worktree and is not part of this
            checkout yet. The route is safe either way: only allow-listed
            files are read, so fixtures, source files, test files and
            traversal paths can never be served.
            """
            asset = WORKSPACE_ASSETS.get(path)
            if asset is None:
                self._json(404, {"error": "Not found"})
                return
            filename, kind = asset
            file_path = WEB_DIR / WORKSPACE_DIR_NAME / filename
            if not file_path.is_file():
                self._json(404, {
                    "error": (
                        "The CV workspace assets are not assembled in this checkout."
                    )
                })
                return
            self._send(200, file_path.read_bytes(), kind)

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
            path = urlparse(self.path).path
            if path in (CV_EXTRACTION_PATH, f"{CV_EXTRACTION_PATH}/"):
                self._cv_extraction()
                return
            if path == PROFILE_PATH:
                self._cv_profile()
                return
            if path == RECONCILIATION_PATH:
                self._cv_reconciliation()
                return
            if path in ("/api/cv/draft", "/api/cv/confirm"):
                self._simple_flow(path)
                return
            if path == JOBS_PATH:
                self._cv_jobs()
                return
            if path == APPROVED_PROFILES_PATH:
                self._cv_approved_profiles()
                return
            if path == CV_DRAFTS_PATH:
                self._cv_generate_draft()
                return
            if path == CV_DRAFT_EDIT_PATH:
                self._cv_edit_draft_item()
                return
            if path == CV_DRAFT_APPROVE_PATH:
                self._cv_approve_draft_item()
                return
            if path == CV_EXPORT_PDF_PATH:
                self._cv_export("pdf")
                return
            if path == CV_EXPORT_DOCX_PATH:
                self._cv_export("docx")
                return
            if path != "/api/analyze":
                self._json(404, {"error": "Not found"})
                return
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                self._json(415, {"error": "Expected application/json"})
                return
            if len(self.headers.get_all("Content-Length", [])) != 1:
                self._json(400, {"error": "Exactly one Content-Length is required"})
                return None
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

        def _cv_extraction(self) -> None:
            """Serve the CV extraction route mounted on this application.

            The transport owns the multipart parsing, the bounded read, the
            request validation, the identifiers and the error mapping. The
            64 KiB JSON limit of ``/api/analyze`` does not apply here: the CV
            limits do. The response is terminal, so no job is stored and
            ``GET`` on a job id answers ``404``.
            """
            job_id = new_job_id()
            try:
                with cv_gate.slot():
                    status, payload = serve_extraction_request(
                        headers=self.headers,
                        stream=self.rfile,
                        extract_fn=cv_extract,
                        limits=CV_LIMITS,
                        job_id=job_id,
                    )
            except TransportError as error:
                status = error.status
                payload = error_payload(error.code, error.message, job_id)
            except ImportError:
                status = 503
                payload = error_payload("parser_unavailable", None, job_id)
            except ConnectionError:
                self.close_connection = True
                return
            except Exception:
                status = 500
                payload = error_payload("internal_error", None, job_id)
            self._json(status, payload)

        def _cv_profile(self) -> None:
            """Serve the candidate profile route mounted on this application.

            The route is a bridge, not a second engine: it validates the
            request, rebuilds the parser response shape and hands it to
            ``build_profile_proposals``. The reply is the canonical profile
            envelope, and every proposal in it is ``proposed``: the request
            has no field that could carry a review decision.
            """
            job_id: str | None = None
            try:
                content_type = self.headers.get("Content-Type", "").split(";")[0].strip()
                if content_type != "application/json":
                    raise TransportError(
                        415, "invalid_content_type", "Expected application/json"
                    )
                raw_size = self.headers.get("Content-Length", "")
                if not raw_size.isascii() or not raw_size.isdecimal():
                    raise TransportError(
                        411, "length_required", "Content-Length required"
                    )
                size = int(raw_size)
                if size > PROFILE_MAX_BODY:
                    self.close_connection = True
                    raise TransportError(
                        413, "request_too_large", "The profile request is too large"
                    )
                try:
                    raw = self.rfile.read(size)
                except TimeoutError:
                    self.close_connection = True
                    raise TransportError(
                        408, "request_timeout", "The request timed out"
                    ) from None
                if len(raw) != size:
                    raise TransportError(
                        400, "incomplete_body", "The request body was truncated"
                    )
                try:
                    payload = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise TransportError(
                        400, "invalid_json", "The request body must be valid JSON"
                    ) from None
                job_id, documents = validate_profile_request(payload)
                envelope = build_profile_proposals(
                    {
                        "schema_version": PARSER_SCHEMA_VERSION,
                        "job_id": job_id,
                        "documents": documents,
                    }
                )
            except TransportError as error:
                self._json(error.status, profile_error(error.code, error.message, job_id))
                return
            except ValueError as error:
                self._json(400, profile_error("invalid_request", str(error)[:200], job_id))
                return
            except ConnectionError:
                self.close_connection = True
                return
            except Exception:
                self._json(
                    500,
                    profile_error("internal_error", "The profile request failed", job_id),
                )
                return
            self._json(200, envelope.as_dict())

        def _cv_reconciliation(self) -> None:
            job_id: str | None = None
            try:
                content_type = self.headers.get("Content-Type", "").split(";")[0].strip()
                if content_type != "application/json":
                    raise TransportError(415, "invalid_content_type", "Expected application/json")
                if self.headers.get("Transfer-Encoding"):
                    raise TransportError(400, "unsupported_transfer_encoding")
                if self.headers.get("Content-Encoding", "identity") != "identity":
                    raise TransportError(415, "unsupported_content_encoding")
                if len(self.headers.get_all("Content-Length", [])) > 1:
                    raise TransportError(400, "invalid_content_length")
                raw_size = self.headers.get("Content-Length", "")
                if not raw_size.isascii() or not raw_size.isdecimal():
                    raise TransportError(411, "length_required", "Content-Length required")
                size = int(raw_size)
                if size > PROFILE_MAX_BODY:
                    self.close_connection = True
                    raise TransportError(413, "request_too_large", "The reconciliation request is too large")
                try:
                    raw = self.rfile.read(size)
                except TimeoutError:
                    self.close_connection = True
                    raise TransportError(408, "request_timeout", "The request timed out") from None
                if len(raw) != size:
                    raise TransportError(400, "incomplete_body", "The request body was truncated")
                try:
                    payload = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise TransportError(400, "invalid_json", "The request body must be valid JSON") from None
                job_id, documents = validate_profile_request(payload)
                report = reconcile_documents(
                    {
                        "schema_version": PARSER_SCHEMA_VERSION,
                        "job_id": job_id,
                        "documents": documents,
                    }
                )
            except TransportError as error:
                self._json(error.status, reconciliation_error(error.code, error.message, job_id))
                return
            except ValueError as error:
                self._json(400, reconciliation_error("invalid_request", str(error)[:200], job_id))
                return
            except ConnectionError:
                self.close_connection = True
                return
            except Exception:
                self._json(
                    500,
                    reconciliation_error("internal_error", "The reconciliation request failed", job_id),
                )
                return
            self._json(200, report.as_dict())

        def _read_json_body(self, max_body: int) -> dict[str, Any] | None:
            content_type = self.headers.get("Content-Type", "").split(";")[0].strip()
            if content_type != "application/json":
                self._json(415, {"error": "Expected application/json"})
                return None
            if self.headers.get("Transfer-Encoding"):
                self._json(400, {"error": "Unsupported transfer encoding"})
                return None
            if self.headers.get("Content-Encoding", "identity") != "identity":
                self._json(415, {"error": "Unsupported content encoding"})
                return None
            if len(self.headers.get_all("Content-Length", [])) != 1:
                self._json(400, {"error": "Exactly one Content-Length is required"})
                return None
            raw_size = self.headers.get("Content-Length", "")
            if not raw_size.isascii() or not raw_size.isdecimal():
                self._json(411, {"error": "Content-Length required"})
                return None
            size = int(raw_size)
            if size > max_body:
                self.close_connection = True
                self._json(413, {"error": "Request too large"})
                return None
            try:
                raw = self.rfile.read(size)
            except TimeoutError:
                self.close_connection = True
                self._json(408, {"error": "Request timed out"})
                return None
            except ConnectionError:
                self.close_connection = True
                return None
            if len(raw) != size:
                self._json(400, {"error": "Incomplete body"})
                return None
            try:
                payload = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._json(400, {"error": "Invalid JSON"})
                return None
            if not isinstance(payload, dict):
                self._json(400, {"error": "Request must be a JSON object"})
                return None
            return payload

        def _simple_flow(self, path):
            payload = self._read_json_body(PROFILE_MAX_BODY)
            if payload is None:
                return
            try:
                if path.endswith('/confirm'):
                    value = review_guard.confirm_all(payload.get('draft'), payload.get('confirmed'), payload.get('attested'))
                else:
                    job_id, documents = validate_profile_request(payload.get('source'))
                    text = payload.get('text')
                    if not isinstance(text, str) or not 40 <= len(text.strip()) <= 20000:
                        raise ValueError('Paste a job posting between 40 and 20,000 characters')
                    job = parse_job_posting(text)
                    trace = []
                    analysis = {}
                    draft, evidence, omitted = draft_from_source(
                        {"job_id": job_id, "documents": documents},
                        job,
                        trace=trace,
                        analysis=analysis,
                    )
                    value = review_guard.issue_draft(draft)
                    value['review']['baseline']['review_mode'] = 'provisional'
                    value['review']['baseline']['evidence'] = evidence
                    value['review']['receipt'] = review_guard.sign('baseline', value['review']['baseline'])
                    value['omitted_count'] = omitted
                    value['decision_report'] = build_decision_report(
                        job=job,
                        draft=draft,
                        trace=trace,
                        conflicts=analysis.get('conflicts', ()),
                        documents=analysis.get('documents'),
                        redundant_fact_ids=analysis.get('redundant_fact_ids', ()),
                    ).as_dict()
                self._json(200, {'draft': value})
            except ReviewValidationError as error:
                self._json(400, {"code": error.code, "error": str(error)})
            except (ValueError, TypeError, KeyError, AttributeError, TransportError):
                self._json(400, {"code": "invalid_request", "error": "Invalid request. Check the uploaded documents, job posting (40–20,000 characters), and accuracy confirmation."})

        def _cv_jobs(self) -> None:
            payload = self._read_json_body(PROFILE_MAX_BODY)
            if payload is None:
                return
            text = payload.get("text")
            if not isinstance(text, str) or not text.strip():
                self._json(400, {"error": "Job posting text is required"})
                return
            if len(text) > 20000:
                self._json(400, {"error": "Job posting text is too long"})
                return
            title = payload.get("title")
            company = payload.get("company")
            location = payload.get("location")
            for name, value in (("title", title), ("company", company), ("location", location)):
                if value is not None and not isinstance(value, str):
                    self._json(400, {"error": f"{name} must be a string or null"})
                    return
            try:
                job = parse_job_posting(text, title=title, company=company, location=location)
            except Exception as exc:
                self._json(400, {"error": str(exc)[:200]})
                return
            self._json(200, job.as_dict())

        def _cv_approved_profiles(self) -> None:
            payload = self._read_json_body(PROFILE_MAX_BODY)
            if payload is None:
                return
            job_id = payload.get("job_id")
            documents = payload.get("documents")
            approved_profile = payload.get("approved_profile")
            if not isinstance(job_id, str) or not job_id.strip():
                self._json(400, {"error": "job_id must be a non-empty string"})
                return
            if not isinstance(documents, list) or not documents:
                self._json(400, {"error": "documents must be a non-empty array"})
                return
            if len(documents) > PROFILE_MAX_DOCUMENTS:
                self._json(400, {"error": "Too many documents"})
                return
            try:
                job_id, documents = validate_profile_request({"job_id": job_id, "documents": documents})
                profile = review_guard.profile(approved_profile,
                    {"job_id": job_id, "documents": documents}, payload.get("confirmed"))
            except (ValueError, TransportError):
                self._json(400, {"error": "Profile approval or source validation failed. Rebuild and explicitly review canonical proposals."})
                return
            self._json(200, {"approved_profile": profile})

        def _cv_generate_draft(self) -> None:
            payload = self._read_json_body(PROFILE_MAX_BODY)
            if payload is None:
                return
            approved_profile_payload = payload.get("approved_profile")
            job_posting_payload = payload.get("job_posting")
            if not isinstance(approved_profile_payload, (dict, str)):
                self._json(400, {"error": "approved_profile is required"})
                return
            if not isinstance(job_posting_payload, dict):
                self._json(400, {"error": "job_posting must be an object"})
                return
            try:
                profile = review_guard.trusted_profile(approved_profile_payload)
            except Exception as exc:
                self._json(400, {"error": f"invalid approved profile: {exc}"[:300]})
                return
            try:
                job = parse_job_posting(
                    str(job_posting_payload.get("raw_text") or job_posting_payload.get("text") or ""),
                    title=job_posting_payload.get("title"),
                    company=job_posting_payload.get("company"),
                    location=job_posting_payload.get("location"),
                )
            except Exception as exc:
                self._json(400, {"error": str(exc)[:200]})
                return
            source = payload.get("source")
            if not (isinstance(source, dict) and source.get("documents")) and isinstance(
                approved_profile_payload, dict
            ):
                embedded = approved_profile_payload.get("source")
                if isinstance(embedded, dict) and embedded.get("documents"):
                    source = embedded
            if isinstance(source, dict) and source.get("documents"):
                try:
                    validate_approved_profile(profile, source)
                except ApprovedProfileError as exc:
                    self._json(400, {"error": f"profile does not match source: {exc}"[:300]})
                    return
            try:
                draft = generate_cv_draft(
                    profile,
                    job,
                    ollama=False,
                    source_response=source if isinstance(source, dict) else None,
                )
            except Exception as exc:
                self._json(500, {"error": str(exc)[:300]})
                return
            issued = review_guard.issue_draft(draft)
            if isinstance(source, dict) and source.get("documents"):
                documents = {
                    str(document.get("document_id")): str(
                        document.get("filename") or f"document {index + 1}"
                    )
                    for index, document in enumerate(source["documents"])
                    if isinstance(document, dict)
                }
                envelope = build_profile_proposals({"schema_version": "1.1", **source})
                trace = trace_from_approved_profile(
                    profile, envelope, documents=documents
                )
                conflicts = [conflict.as_dict() for conflict in envelope.conflicts]
            else:
                documents = {}
                trace = trace_from_approved_profile(profile)
                conflicts = []
            issued["decision_report"] = build_decision_report(
                job=job,
                draft=draft,
                trace=trace,
                conflicts=conflicts,
                documents=documents,
            ).as_dict()
            self._json(200, {"draft": issued, "job": job.as_dict()})

        def _cv_edit_draft_item(self) -> None:
            payload = self._read_json_body(PROFILE_MAX_BODY)
            if payload is None:
                return
            draft_payload = payload.get("draft")
            item_id = payload.get("item_id")
            new_text = payload.get("text")
            if not isinstance(draft_payload, dict):
                self._json(400, {"error": "draft must be an object"})
                return
            if not isinstance(item_id, str) or not item_id:
                self._json(400, {"error": "item_id must be a non-empty string"})
                return
            if not isinstance(new_text, str):
                self._json(400, {"error": "text must be a string"})
                return
            try:
                CvDraft.from_dict(draft_payload)
            except Exception as exc:
                self._json(400, {"error": f"invalid draft: {exc}"[:300]})
                return
            try:
                updated = review_guard.edit(draft_payload, item_id, new_text)
            except ValueError as exc:
                self._json(400, {"error": str(exc)[:300]})
                return
            self._json(200, {"draft": updated})

        def _cv_approve_draft_item(self) -> None:
            payload = self._read_json_body(PROFILE_MAX_BODY)
            if payload is None:
                return
            draft_payload = payload.get("draft")
            item_id = payload.get("item_id")
            if not isinstance(draft_payload, dict):
                self._json(400, {"error": "draft must be an object"})
                return
            if not isinstance(item_id, str) or not item_id:
                self._json(400, {"error": "item_id must be a non-empty string"})
                return
            try:
                CvDraft.from_dict(draft_payload)
            except Exception as exc:
                self._json(400, {"error": f"invalid draft: {exc}"[:300]})
                return
            try:
                updated = review_guard.approve(draft_payload, item_id, payload.get("confirmed"), payload.get("attested"))
            except ValueError as exc:
                self._json(400, {"error": str(exc)[:300]})
                return
            self._json(200, {"draft": updated})

        def _cv_export(self, kind: str) -> None:
            payload = self._read_json_body(PROFILE_MAX_BODY)
            if payload is None:
                return
            draft_payload = payload.get("draft")
            if not isinstance(draft_payload, dict):
                self._json(400, {"error": "draft must be an object"})
                return
            try:
                CvDraft.from_dict(draft_payload)
            except Exception as exc:
                self._json(400, {"error": f"invalid draft: {exc}"[:300]})
                return
            try:
                draft, evidence_support = review_guard.export(
                    draft_payload, payload.get("confirmed"), payload.get("contact"))
            except ReviewValidationError as error:
                self._json(400, {"code": error.code, "error": str(error)})
                return
            except (ValueError, KeyError, TypeError):
                self._json(400, {"code": "invalid_request", "error": "Export requires valid current wording approvals and explicit contact confirmation"})
                return
            try:
                from .export import export_cv_docx_bytes, export_cv_pdf_bytes
            except ImportError:
                self._json(503, {"error": "Export dependencies are not installed"})
                return
            try:
                if kind == "pdf":
                    data = export_cv_pdf_bytes(draft, evidence_support=evidence_support)
                    mime = "application/pdf"
                    ext = "pdf"
                else:
                    data = export_cv_docx_bytes(draft, evidence_support=evidence_support)
                    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    ext = "docx"
            except Exception as exc:
                self._json(400, {"error": str(exc)[:300]})
                return
            filename = f"tailored-cv.{ext}"
            self._send_bytes(200, data, mime, filename)

        def _send_bytes(self, status: int, data: bytes, content_type: str, filename: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

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
