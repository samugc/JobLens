#!/usr/bin/env python3
"""Serve only the isolated CV evidence workspace for manual inspection.

This preview server exists so the workspace can be reviewed without touching the
public demo server in ``src/joblens_public/webapp.py``. It is deliberately
incomplete:

* It serves files from ``web/workspace/`` only.
* Every extraction request under ``/api/cv/`` is refused with HTTP 503 and
  ``parser_unavailable``. It never synthesises extraction output, never marks a
  document as extracted and never fabricates page or paragraph references.

Use it to inspect loading, error and empty states. To inspect populated states,
point the ``joblens-cv-api-base`` meta tag at a real parser service that speaks
the provisional contract in ``docs/cv-workspace-contract.md``.

Examples:
    python scripts/serve_cv_workspace.py
    python scripts/serve_cv_workspace.py --host 127.0.0.1 --port 8765
"""

from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "web" / "workspace"
ASSET_PREFIX = "/workspace/"
API_PREFIX = "/api/cv"

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "form-action 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'"
)

PARSER_UNAVAILABLE = {
    "error": {
        "code": "parser_unavailable",
        "message": (
            "This preview server does not run the CV parser. Extraction "
            "requests are refused instead of returning synthetic text."
        ),
    }
}


class CvWorkspaceHandler(BaseHTTPRequestHandler):
    """Serve workspace assets and refuse extraction requests honestly."""

    server_version = "JobLensCvWorkspacePreview/0.1"
    protocol_version = "HTTP/1.1"

    # Directory is injected by build_server so tests can point elsewhere.
    asset_root = WORKSPACE

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        self._route(head=False)

    def do_HEAD(self) -> None:  # noqa: N802 - http.server naming
        self._route(head=True)

    def do_POST(self) -> None:  # noqa: N802 - http.server naming
        self._route(head=False)

    def do_PUT(self) -> None:  # noqa: N802 - http.server naming
        self._drain_body()
        self._method_not_allowed()

    def do_DELETE(self) -> None:  # noqa: N802 - http.server naming
        self._drain_body()
        self._method_not_allowed()

    def _route(self, *, head: bool) -> None:
        self._drain_body()
        path = unquote(urlsplit(self.path).path)

        if path in ("", "/", "/workspace"):
            self._redirect("/workspace/", head=head)
            return

        if path == API_PREFIX or path.startswith(f"{API_PREFIX}/"):
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, PARSER_UNAVAILABLE, head=head)
            return

        if path.startswith(ASSET_PREFIX):
            self._serve_asset(path[len(ASSET_PREFIX) :], head=head)
            return

        self._send_json(
            HTTPStatus.NOT_FOUND,
            {
                "error": {
                    "code": "not_found",
                    "message": "This preview server only serves /workspace/.",
                }
            },
            head=head,
        )

    def _drain_body(self) -> None:
        """Read and discard a small request body so keep-alive stays coherent.

        The preview never inspects uploads; it only needs to consume them before
        answering so the bytes are not parsed as the next request line.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0

        if length <= 0:
            return

        limit = 1024 * 1024
        self.rfile.read(min(length, limit))
        if length > limit:
            self.close_connection = True

    def _serve_asset(self, relative: str, *, head: bool) -> None:
        if self.command not in ("GET", "HEAD"):
            self._method_not_allowed()
            return

        if relative in ("", "/"):
            relative = "index.html"

        target = (self.asset_root / relative).resolve()
        root = self.asset_root.resolve()
        if not target.is_relative_to(root) or not target.is_file():
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {
                    "error": {
                        "code": "not_found",
                        "message": "Workspace asset not found.",
                    }
                },
                head=head,
            )
            return

        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or target.suffix in {".js", ".json", ".svg"}:
            content_type = f"{content_type}; charset=utf-8"

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _redirect(self, location: str, *, head: bool) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        del head

    def _send_json(self, status: HTTPStatus, payload: dict, *, head: bool) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _method_not_allowed(self) -> None:
        self._send_json(
            HTTPStatus.METHOD_NOT_ALLOWED,
            {
                "error": {
                    "code": "method_not_allowed",
                    "message": f"{self.command} is not supported by the workspace preview.",
                }
            },
            head=False,
        )

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[cv-workspace] {self.address_string()} {fmt % args}", flush=True)


def build_server(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    handler = type(
        "BoundCvWorkspaceHandler",
        (CvWorkspaceHandler,),
        {"asset_root": WORKSPACE},
    )
    return ThreadingHTTPServer((host, port), handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    server = build_server(args.host, args.port)
    url = f"http://{args.host}:{server.server_port}/workspace/"
    print(f"Serving the isolated CV workspace preview at {url}", flush=True)
    print(
        "Extraction requests under /api/cv/ return 503 parser_unavailable by design.",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping the CV workspace preview.", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
