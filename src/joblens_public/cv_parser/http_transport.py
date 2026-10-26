"""Local, loopback-only HTTP transport for the CV parser (schema 1.1).

The transport is a thin shell around :func:`joblens_public.cv_parser.service.extract_batch`.
It never stores a job, never queues work, never writes a temporary file and never
logs document content. A request returns a terminal answer: the final extraction
or a final error.

The parser remains canonical. ``extract_batch`` decides statuses, warnings and
limits; this module only adds transport metadata (``transport_version``,
``job_id``, ``document_id``) and maps a rejected batch to HTTP 400 or 413.

Integration
-----------
The module is usable in two ways:

* as a standalone process, ``python -m joblens_public.cv_parser.http_transport``;
* as a component mounted inside an existing local application, by calling
  :func:`serve_extraction_request` from an existing ``do_POST`` handler.
  Mounting the route on the same origin as the browser keeps the workspace on
  a single origin, so no permissive CORS headers are needed.

:func:`serve_extraction_request` is the single request-serving path used by
both servers. It owns the multipart parsing, the bounded body read, the
request validation, the identifiers and the error mapping, and it calls
:func:`handle_upload_request` exactly once per request.

Only the Python standard library is used.
"""
from __future__ import annotations

import argparse
import contextlib
import ipaddress
import json
import logging
import sys
import threading
import time
import uuid
import warnings
from collections.abc import Callable, Iterator, Mapping, Sequence
from email import policy
from email.message import Message
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, TextIO
from urllib.parse import urlsplit

from .models import DEFAULT_LIMITS, SCHEMA_VERSION, ParseLimits, UploadDocument

__all__ = [
    "CVHTTPServer",
    "DEFAULT_LIMITS",
    "EXTRACTION_PATH",
    "ExtractionGate",
    "JOB_PATH_PREFIX",
    "MAX_PARTS",
    "SCHEMA_VERSION",
    "TRANSPORT_VERSION",
    "TransportError",
    "create_server",
    "decorate_parser_response",
    "default_extract_fn",
    "error_payload",
    "handle_upload_request",
    "main",
    "max_body_bytes",
    "new_document_id",
    "new_job_id",
    "parse_multipart",
    "read_bounded_body",
    "serve_extraction_request",
]

TRANSPORT_VERSION = "1.0"
EXTRACTION_PATH = "/api/cv/extractions"
JOB_PATH_PREFIX = "/api/cv/extractions/"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_PARTS = 64
MULTIPART_OVERHEAD_BYTES = 1024 * 1024
DEFAULT_MAX_CONCURRENT = 2
REQUEST_TIMEOUT = 30.0
REQUEST_TOKEN_HEADER = "X-JobLens-Request"

#: HTTP status for every rejection code the parser can produce.
REJECTION_STATUS: dict[str, int] = {
    "empty_batch": 400,
    "too_many_documents": 400,
    "batch_too_large": 413,
}

#: Fixed, content-free messages. They never interpolate document data, file
#: names, exception text or local paths.
ERROR_MESSAGES: dict[str, str] = {
    "invalid_content_type": "Use multipart/form-data with a boundary.",
    "invalid_multipart": "The multipart body is malformed.",
    "invalid_part": "A file part could not be read.",
    "missing_filename": "Each files part must include a filename.",
    "too_many_parts": "The multipart body contains too many parts.",
    "invalid_content_length": "Content-Length must be a non-negative integer.",
    "length_required": "A Content-Length header is required.",
    "request_too_large": "The request exceeds the local size limit.",
    "incomplete_body": "The request body ended before Content-Length bytes arrived.",
    "request_timeout": "The request timed out.",
    "unsupported_content_encoding": "Encoded request bodies are not supported.",
    "invalid_host": "Localhost access only.",
    "invalid_origin": "Cross-origin requests are disabled.",
    "missing_request_token": "A local request token is required.",
    "cross_site_request": "Cross-site requests are disabled.",
    "not_found": "No such endpoint.",
    "job_not_found": "Extraction results are not stored; use the upload response.",
    "method_not_allowed": "Use POST for this endpoint.",
    "parser_unavailable": "The CV parser is not available on this server.",
    "server_busy": "The server is busy; retry shortly.",
    "internal_error": "The extraction request failed.",
    "invalid_parser_response": "The parser returned an invalid response.",
    "http_error": "The request could not be processed.",
}

ExtractFn = Callable[[Sequence[UploadDocument]], dict[str, Any]]


class TransportError(Exception):
    """A transport failure with a fixed status, code and message."""

    def __init__(self, status: int, code: str, message: str | None = None) -> None:
        text = message or ERROR_MESSAGES.get(code, ERROR_MESSAGES["http_error"])
        super().__init__(text)
        self.status = status
        self.code = code
        self.message = text


def new_job_id() -> str:
    """Return an opaque, response-scoped job identifier."""
    return f"job_{uuid.uuid4().hex}"


def new_document_id() -> str:
    """Return an opaque, response-scoped document identifier."""
    return f"doc_{uuid.uuid4().hex}"


def max_body_bytes(limits: ParseLimits = DEFAULT_LIMITS) -> int:
    """Largest accepted request body, including multipart framing."""
    return limits.max_batch_bytes + MULTIPART_OVERHEAD_BYTES


def error_payload(
    code: str,
    message: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Build the transport error body. It never contains document data."""
    return {
        "transport_version": TRANSPORT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "job_id": job_id,
        "error": {
            "code": code,
            "message": message or ERROR_MESSAGES.get(code, ERROR_MESSAGES["http_error"]),
        },
        "documents": [],
    }


def _header_values(headers: Mapping[str, str], name: str) -> list[str]:
    """Read every value of a header from a mapping or an email message."""
    getter = getattr(headers, "get_all", None)
    if callable(getter):
        return [value for value in getter(name, []) if isinstance(value, str)]
    value = headers.get(name)
    if value is None:
        return []
    return [value] if isinstance(value, str) else [str(value)]


def _is_loopback_address(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _content_length(headers: Mapping[str, str]) -> int:
    """Return the declared body length, rejecting chunked or missing lengths."""
    encodings = [
        value.strip().casefold() for value in _header_values(headers, "Transfer-Encoding")
    ]
    if encodings and encodings != ["identity"]:
        raise TransportError(411, "length_required")
    values = _header_values(headers, "Content-Length")
    if len(values) != 1:
        raise TransportError(411, "length_required")
    raw = values[0].strip()
    if not raw.isascii() or not raw.isdecimal():
        raise TransportError(400, "invalid_content_length")
    return int(raw)


def _reject_encoded_body(headers: Mapping[str, str]) -> None:
    """Reject a compressed body instead of silently parsing compressed bytes."""
    encodings = [
        value.strip().casefold() for value in _header_values(headers, "Content-Encoding")
    ]
    if encodings and encodings != ["identity"]:
        raise TransportError(415, "unsupported_content_encoding")


def _is_loopback_host(value: str) -> bool:
    """True when a ``Host`` header points at this machine."""
    try:
        hostname = urlsplit("//" + value).hostname
    except ValueError:
        return False
    if not hostname:
        return False
    hostname = hostname.strip().casefold()
    return hostname == "localhost" or _is_loopback_address(hostname)


def _is_loopback_origin(value: str) -> bool:
    """True when an ``Origin`` header points at this machine."""
    try:
        hostname = urlsplit(value).hostname
    except ValueError:
        return False
    if not hostname:
        return False
    hostname = hostname.strip().casefold()
    return hostname == "localhost" or _is_loopback_address(hostname)


def _multipart_boundary(content_type: str) -> str:
    """Validate the request content type and return its boundary."""
    header = Message()
    try:
        header["Content-Type"] = content_type
    except (TypeError, ValueError):
        raise TransportError(400, "invalid_content_type") from None
    if header.get_content_type() != "multipart/form-data":
        raise TransportError(415, "invalid_content_type")
    boundary = header.get_boundary()
    if not boundary or len(boundary) > 70 or not boundary.isascii():
        raise TransportError(400, "invalid_content_type")
    if any(ord(character) < 32 or ord(character) == 127 for character in boundary):
        raise TransportError(400, "invalid_content_type")
    return boundary


def parse_multipart(
    content_type: str,
    body: bytes,
    *,
    max_parts: int = MAX_PARTS,
) -> list[UploadDocument]:
    """Parse a ``multipart/form-data`` body into in-memory uploads.

    The payload of every ``files`` part is preserved byte for byte, including
    NUL bytes and CRLF sequences. Parts with another field name are ignored.
    Nothing is written to disk and no file name is trusted: the parser
    sanitises the basename it receives.
    """
    _multipart_boundary(content_type)
    try:
        encoded_type = content_type.encode("ascii")
    except UnicodeEncodeError:
        raise TransportError(400, "invalid_content_type") from None
    raw = b"Content-Type: " + encoded_type + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
    message = BytesParser(policy=policy.HTTP).parsebytes(raw)
    if message.defects or not message.is_multipart():
        raise TransportError(400, "invalid_multipart")
    if message.get_content_type() != "multipart/form-data":
        raise TransportError(415, "invalid_content_type")
    parts = list(message.iter_parts())
    if len(parts) > max_parts:
        raise TransportError(400, "too_many_parts")

    uploads: list[UploadDocument] = []
    for part in parts:
        if part.defects:
            raise TransportError(400, "invalid_multipart")
        name = part.get_param("name", header="content-disposition")
        if name != "files":
            continue
        if part.is_multipart():
            raise TransportError(400, "invalid_part")
        if part.get_content_disposition() != "form-data":
            raise TransportError(400, "invalid_part")
        filename = part.get_filename()
        if not isinstance(filename, str) or not filename.strip():
            raise TransportError(400, "missing_filename")
        data = part.get_payload(decode=True)
        if not isinstance(data, bytes):
            raise TransportError(400, "invalid_part")
        uploads.append(UploadDocument(filename=filename, data=data))
    return uploads


def _with_identifiers(
    response: Mapping[str, Any],
    documents: Sequence[Mapping[str, Any]],
    job_id: str,
) -> dict[str, Any]:
    payload = dict(response)
    payload["transport_version"] = TRANSPORT_VERSION
    payload["job_id"] = job_id
    payload["documents"] = [
        {**document, "document_id": new_document_id()} for document in documents
    ]
    return payload


def decorate_parser_response(
    response: Any,
    job_id: str,
) -> tuple[int, dict[str, Any]]:
    """Validate a parser response and add the transport identifiers.

    The parser payload is preserved as it is: only ``transport_version``,
    ``job_id`` and one ``document_id`` per document are added. A rejected batch
    keeps its original error code and is mapped to HTTP 400 or 413.
    """
    if not isinstance(response, dict):
        raise TransportError(500, "invalid_parser_response")
    if response.get("schema_version") != SCHEMA_VERSION:
        raise TransportError(500, "invalid_parser_response")
    batch = response.get("batch")
    documents = response.get("documents")
    if not isinstance(batch, dict) or not isinstance(documents, list):
        raise TransportError(500, "invalid_parser_response")
    status = batch.get("status")
    if status not in ("completed", "partial", "rejected"):
        raise TransportError(500, "invalid_parser_response")

    if status == "rejected":
        error = batch.get("error")
        if not isinstance(error, dict):
            raise TransportError(500, "invalid_parser_response")
        code = error.get("code")
        message = error.get("message")
        if not isinstance(code, str) or not isinstance(message, str):
            raise TransportError(500, "invalid_parser_response")
        payload = _with_identifiers(response, documents, job_id)
        payload["error"] = dict(error)
        return REJECTION_STATUS.get(code, 400), payload

    if batch.get("error") is not None:
        raise TransportError(500, "invalid_parser_response")
    if batch.get("document_count") != len(documents):
        raise TransportError(500, "invalid_parser_response")
    for document in documents:
        if not isinstance(document, dict):
            raise TransportError(500, "invalid_parser_response")
    return 200, _with_identifiers(response, documents, job_id)


def handle_upload_request(
    *,
    headers: Mapping[str, str],
    body: bytes,
    extract_fn: ExtractFn,
    limits: ParseLimits = DEFAULT_LIMITS,
    job_id: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Turn a multipart upload into a terminal extraction response.

    This is the reusable entry point for a host application that already owns
    the HTTP layer: it needs no socket and keeps no state. ``TransportError`` is
    raised for transport-level problems so the caller can render its own error
    body with the same code and message.
    """
    identifier = job_id or new_job_id()
    if len(body) > max_body_bytes(limits):
        raise TransportError(413, "request_too_large")
    content_types = _header_values(headers, "Content-Type")
    if len(content_types) != 1:
        raise TransportError(415, "invalid_content_type")
    uploads = parse_multipart(content_types[0], body)
    return decorate_parser_response(extract_fn(uploads), identifier)


def default_extract_fn(limits: ParseLimits = DEFAULT_LIMITS) -> ExtractFn:
    """Return the default extraction callable.

    The parser is imported lazily so that importing this module never
    requires ``pypdf``. A host application can therefore mount the transport
    and answer ``503 parser_unavailable`` instead of failing to start.
    """

    def extract(documents: Sequence[UploadDocument]) -> dict[str, Any]:
        from .service import extract_batch

        return extract_batch(documents, limits=limits)

    return extract


def read_bounded_body(stream: Any, length: int, *, max_bytes: int) -> bytes:
    """Read exactly ``length`` bytes from a binary stream, never more.

    The declared length is checked against ``max_bytes`` before a single byte
    is read, and the loop stops at the declared length, so an oversized or
    lying client cannot make the server buffer an unbounded body.
    """
    if length < 0:
        raise TransportError(400, "invalid_content_length")
    if length > max_bytes:
        raise TransportError(413, "request_too_large")
    if length == 0:
        return b""
    buffer = bytearray()
    while len(buffer) < length:
        try:
            chunk = stream.read(min(65536, length - len(buffer)))
        except TimeoutError:
            raise TransportError(408, "request_timeout") from None
        if not chunk:
            raise TransportError(400, "incomplete_body")
        buffer.extend(chunk)
    return bytes(buffer)


def serve_extraction_request(
    *,
    headers: Mapping[str, str],
    stream: Any,
    extract_fn: ExtractFn,
    limits: ParseLimits = DEFAULT_LIMITS,
    job_id: str | None = None,
    max_body: int | None = None,
) -> tuple[int, dict[str, Any]]:
    """Serve one extraction request and return its terminal ``(status, payload)``.

    This is the single request-serving path shared by the standalone transport
    server and by an application that mounts the transport on its own
    origin. It applies the CV-specific request rules (no encoded body, one
    declared length, a bounded body), parses the multipart upload, runs the
    parser and maps the result.

    ``handle_upload_request`` is called exactly once per request.
    """
    identifier = job_id or new_job_id()
    _reject_encoded_body(headers)
    length = _content_length(headers)
    cap = max_body_bytes(limits) if max_body is None else max_body
    body = read_bounded_body(stream, length, max_bytes=cap)
    return handle_upload_request(
        headers=headers,
        body=body,
        extract_fn=extract_fn,
        limits=limits,
        job_id=identifier,
    )


class ExtractionGate:
    """Bound concurrent extractions without queueing them.

    The gate is shared by the standalone transport server and by an
    application that mounts the transport, so both apply the same limit. An
    excess request is rejected with ``503 server_busy``; it is never queued.
    """

    def __init__(self, max_concurrent: int = DEFAULT_MAX_CONCURRENT) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be at least 1")
        self._slots = threading.BoundedSemaphore(max_concurrent)

    @contextlib.contextmanager
    def slot(self) -> Iterator[None]:
        if not self._slots.acquire(blocking=False):
            raise TransportError(503, "server_busy")
        try:
            yield
        finally:
            self._slots.release()


def _silence_parser_logs() -> None:
    """Keep third-party parser chatter out of the terminal and the log file."""
    logger = logging.getLogger("pypdf")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    warnings.filterwarnings("ignore", module=r"pypdf(\..*)?")


class CVHTTPServer(ThreadingHTTPServer):
    """Loopback-only server that never stores a job and never queues work."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        extract_fn: ExtractFn,
        limits: ParseLimits,
        access_log: bool,
        log_stream: TextIO,
        max_concurrent: int,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.extract_fn = extract_fn
        self.limits = limits
        self.access_log = access_log
        self.log_stream = log_stream
        self.gate = ExtractionGate(max_concurrent)
        self._log_lock = threading.Lock()

    @contextlib.contextmanager
    def slot(self) -> Iterator[None]:
        """Bound concurrent extractions without queueing them."""
        with self.gate.slot():
            yield

    def write_log(self, line: str) -> None:
        with self._log_lock:
            try:
                self.log_stream.write(line)
                self.log_stream.flush()
            except (OSError, ValueError):
                pass

    def handle_error(self, request: Any, client_address: Any) -> None:
        """Log a failure without a traceback, a message or any request data."""
        error = sys.exc_info()[1]
        name = type(error).__name__ if error is not None else "unknown"
        self.write_log(f"cv-transport error {name}\n")


class CVRequestHandler(BaseHTTPRequestHandler):
    """Route the extraction endpoint. Every answer is JSON and terminal."""

    server_version = "JobLensCV/1.0"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = REQUEST_TIMEOUT

    def log_message(self, format: str, *args: Any) -> None:
        # Request metadata can contain document text; keep the terminal quiet.
        return

    def log_error(self, format: str, *args: Any) -> None:
        return

    # -- helpers ---------------------------------------------------------

    def _path(self) -> str:
        return urlsplit(getattr(self, "path", "") or "").path

    def _route(self) -> str:
        path = self._path()
        if path in (EXTRACTION_PATH, EXTRACTION_PATH + "/"):
            return EXTRACTION_PATH
        if path.startswith(JOB_PATH_PREFIX):
            return "job"
        return "other"

    def _require_local_request(self, *, require_token: bool) -> None:
        """Reject anything that is not a same-machine request."""
        if not _is_loopback_address(self.client_address[0]):
            raise TransportError(403, "invalid_host")
        hosts = _header_values(self.headers, "Host")
        if len(hosts) != 1 or not _is_loopback_host(hosts[0]):
            raise TransportError(403, "invalid_host")
        origins = _header_values(self.headers, "Origin")
        if len(origins) > 1:
            raise TransportError(403, "invalid_origin")
        if origins and not _is_loopback_origin(origins[0]):
            raise TransportError(403, "invalid_origin")
        fetch_sites = _header_values(self.headers, "Sec-Fetch-Site")
        if fetch_sites and fetch_sites[0].strip().casefold() not in ("same-origin", "none"):
            raise TransportError(403, "cross_site_request")
        if require_token:
            tokens = _header_values(self.headers, REQUEST_TOKEN_HEADER)
            if len(tokens) != 1 or not tokens[0].strip():
                raise TransportError(403, "missing_request_token")

    def _log_access(self, status: int, job_id: str | None, started: float) -> None:
        server = self.server
        if not getattr(server, "access_log", False):
            return
        duration = int((time.monotonic() - started) * 1000)
        command = getattr(self, "command", "") or "-"
        server.write_log(
            f"cv-transport {command} {self._route()} {status} {duration}ms "
            f"job_id={job_id or '-'}\n"
        )

    def _send_json(
        self,
        status: int,
        payload: Mapping[str, Any],
        job_id: str | None,
        started: float,
    ) -> None:
        try:
            data = json.dumps(payload, ensure_ascii=True, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError):
            status = 500
            data = json.dumps(error_payload("internal_error", None, job_id)).encode("utf-8")
        self.close_connection = True
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
            )
            if status == 405:
                self.send_header("Allow", "POST")
            self.send_header("Connection", "close")
            self.end_headers()
            if getattr(self, "command", "") != "HEAD":
                self.wfile.write(data)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        finally:
            self._log_access(status, job_id, started)

    def _send_error(
        self,
        error: TransportError,
        job_id: str | None,
        started: float,
    ) -> None:
        self._send_json(error.status, error_payload(error.code, error.message, job_id), job_id, started)

    # -- routes ----------------------------------------------------------

    def do_POST(self) -> None:
        started = time.monotonic()
        job_id = new_job_id()
        try:
            self._require_local_request(require_token=True)
            if self._path() not in (EXTRACTION_PATH, EXTRACTION_PATH + "/"):
                raise TransportError(404, "not_found")
            with self.server.slot():
                status, payload = serve_extraction_request(
                    headers=self.headers,
                    stream=self.rfile,
                    extract_fn=self.server.extract_fn,
                    limits=self.server.limits,
                    job_id=job_id,
                )
        except TransportError as error:
            self._send_error(error, job_id, started)
            return
        except ImportError:
            self._send_error(TransportError(503, "parser_unavailable"), job_id, started)
            return
        except ConnectionError:
            self.close_connection = True
            return
        except Exception:
            self._send_error(TransportError(500, "internal_error"), job_id, started)
            return
        self._send_json(status, payload, job_id, started)

    def do_GET(self) -> None:
        started = time.monotonic()
        job_id = new_job_id()
        try:
            self._require_local_request(require_token=False)
            path = self._path()
            if path in (EXTRACTION_PATH, EXTRACTION_PATH + "/"):
                raise TransportError(405, "method_not_allowed")
            if path.startswith(JOB_PATH_PREFIX):
                raise TransportError(404, "job_not_found")
            raise TransportError(404, "not_found")
        except TransportError as error:
            self._send_error(error, job_id, started)
            return
        except Exception:
            self._send_error(TransportError(500, "internal_error"), job_id, started)
            return

    def do_OPTIONS(self) -> None:
        started = time.monotonic()
        job_id = new_job_id()
        try:
            self._require_local_request(require_token=False)
        except TransportError as error:
            self._send_error(error, job_id, started)
            return
        self._send_error(TransportError(403, "cross_site_request"), job_id, started)

    def do_PUT(self) -> None:
        self._method_not_allowed()

    def do_PATCH(self) -> None:
        self._method_not_allowed()

    def do_DELETE(self) -> None:
        self._method_not_allowed()

    def _method_not_allowed(self) -> None:
        started = time.monotonic()
        self._send_error(TransportError(405, "method_not_allowed"), new_job_id(), started)

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """Answer protocol errors with JSON and without echoing the request."""
        status = int(code)
        if status < 400 or status > 599:
            status = 400
        self._send_error(TransportError(status, "http_error"), None, time.monotonic())


def create_server(
    port: int = DEFAULT_PORT,
    *,
    limits: ParseLimits = DEFAULT_LIMITS,
    extract_fn: ExtractFn | None = None,
    access_log: bool = False,
    log_stream: TextIO | None = None,
    max_concurrent: int = DEFAULT_MAX_CONCURRENT,
    host: str = DEFAULT_HOST,
) -> CVHTTPServer:
    """Create the loopback transport server.

    ``limits`` and ``extract_fn`` are injection points for tests and for host
    applications. The default wiring calls the parser's ``extract_batch`` with
    the default limits, and the server binds to loopback only.
    """
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    if not _is_loopback_host(host):
        raise ValueError("host must be a loopback address")
    if max_concurrent < 1:
        raise ValueError("max_concurrent must be at least 1")
    if extract_fn is None:
        extract_fn = default_extract_fn(limits)
    _silence_parser_logs()
    return CVHTTPServer(
        (host, port),
        CVRequestHandler,
        extract_fn=extract_fn,
        limits=limits,
        access_log=access_log,
        log_stream=log_stream if log_stream is not None else sys.stderr,
        max_concurrent=max_concurrent,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the transport as a standalone loopback process."""
    parser = argparse.ArgumentParser(
        prog="python -m joblens_public.cv_parser.http_transport",
        description="Serve the local CV parser over loopback HTTP.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="TCP port on 127.0.0.1 (0 selects a free port).",
    )
    parser.add_argument(
        "--access-log",
        action="store_true",
        help="Log one metadata line per request; never document content.",
    )
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    try:
        from .service import extract_batch  # noqa: F401  (preflight import check)
    except ImportError:
        print("The CV parser is unavailable: install pypdf.", file=sys.stderr)
        return 2

    server = create_server(args.port, access_log=args.access_log)
    host = server.server_address[0]
    port = server.server_address[1]
    print(
        f"JobLens CV transport listening on http://{host}:{port} (schema {SCHEMA_VERSION})",
        file=sys.stderr,
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
