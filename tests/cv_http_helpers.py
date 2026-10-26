"""Small standard-library helpers for CV HTTP transport tests."""
from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from joblens_public.cv_parser.http_transport import CVHTTPServer, create_server

TEST_TOKEN = "synthetic-test-token"
BOUNDARY = "----JobLensSyntheticBoundary"


def build_multipart(
    files: Sequence[tuple[str, bytes]],
    *,
    boundary: str = BOUNDARY,
    fields: Sequence[tuple[str, str]] = (),
) -> tuple[bytes, str]:
    """Build a multipart body with repeated ``files`` parts and extra fields."""
    body = bytearray()
    for name, filename, data in files:
        body.extend(f"--{boundary}\r\n".encode("ascii"))
        body.extend(
            (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"\r\n'
            ).encode("utf-8")
        )
        body.extend(b"Content-Type: application/octet-stream\r\n\r\n")
        body.extend(data)
        body.extend(b"\r\n")
    for name, value in fields:
        body.extend(f"--{boundary}\r\n".encode("ascii"))
        body.extend(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8")
        )
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("ascii"))
    return bytes(body), boundary


def api_headers(
    port: int,
    *,
    token: bool = True,
    origin: bool = True,
    content_type: str | None = None,
    content_length: int | None = None,
) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if token:
        headers["X-JobLens-Request"] = TEST_TOKEN
    if origin:
        headers["Origin"] = f"http://127.0.0.1:{port}"
    if content_type is not None:
        headers["Content-Type"] = content_type
    if content_length is not None:
        headers["Content-Length"] = str(content_length)
    return headers


def request(
    port: int,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    *,
    timeout: float = 10.0,
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


def post_files(
    port: int,
    files: Sequence[tuple[str, bytes]],
    *,
    fields: Sequence[tuple[str, str]] = (),
    headers: dict[str, str] | None = None,
    boundary: str = BOUNDARY,
) -> tuple[int, dict[str, str], bytes]:
    body, boundary = build_multipart(files, boundary=boundary, fields=fields)
    request_headers = api_headers(
        port,
        content_type=f"multipart/form-data; boundary={boundary}",
    )
    if headers:
        request_headers.update(headers)
    return request(port, "POST", "/api/cv/extractions", body, request_headers)


def json_body(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw.decode("utf-8"))
    assert isinstance(value, dict)
    return value


def raw_request(
    port: int,
    request: bytes,
    *,
    timeout: float = 5.0,
) -> bytes:
    import socket

    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as connection:
        connection.sendall(request)
        connection.settimeout(timeout)
        chunks: list[bytes] = []
        while True:
            chunk = connection.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)


@contextmanager
def running_server(**kwargs: Any) -> Iterator[CVHTTPServer]:
    server = create_server(0, **kwargs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
