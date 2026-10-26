# CV parser API contract (schema 1.1)

Local, evidence-neutral PDF/DOCX extraction for JobLens 2.0. This document is
the stable response contract for the UI developer. The implementation lives in
`src/joblens_public/cv_parser/` and is not wired into the existing demo UI or
the existing evaluator.

Candidate fact proposals derived from this contract are a separate layer with
their own contract: see
[`docs/cv-profile-proposals.md`](cv-profile-proposals.md). Nothing in this
document changes because of it.

## Scope and privacy

The parser turns an in-memory CV into text plus source locators. It does **not**
verify evidence, infer professional skills, score a candidate, read a job
posting or attest any claim. Extracted text is raw document text.

- No external services, uploads, analytics, persistence or network calls.
- Documents are processed in memory with the locally installed `pypdf` library
  (PDF) and the Python standard library (DOCX). `pypdf` is a **required runtime
  dependency** of the parser, declared in `[project].dependencies` in
  `pyproject.toml`; it is not an optional extra. The demo UI path does not import
  the parser, so the demo can run without it, but any parser use requires it.
- Document contents are never logged.
- The response never contains filesystem paths. `filename` is a sanitized
  basename (for example, `cv.pdf`), never `/home/...`, `C:\\...` or `../...`.
- Only PDF and DOCX are accepted. DOCX macros, embedded media, headers and
  footers are not read. PDF OCR is not performed; images are not inspected.
- The caller is responsible for not logging or persisting returned text.
- An optional local HTTP transport (`joblens_public.cv_parser.http_transport`)
  exposes the parser on loopback. It adds no persistence, no queue and no
  temporary file, and it never logs document content. See
  [HTTP transport](#http-transport-local-optional).

## Python API

```python
from joblens_public.cv_parser import UploadDocument, extract_batch

response = extract_batch(
    [
        UploadDocument(filename="cv.pdf", data=pdf_bytes),
        UploadDocument(filename="cover.docx", data=docx_bytes),
    ]
)
```

Single-document helper:

```python
from joblens_public.cv_parser import extract_document

document = extract_document("cv.pdf", pdf_bytes)
```

Local CLI (writes the same JSON to stdout):

```bash
PYTHONPATH=src python -m joblens_public.cv_parser cv.pdf cover.docx
```

The CLI exits `0` only when `batch.status` is `"completed"`. A `"partial"` or
rejected batch still writes the JSON response to stdout and exits `1`, so shell
consumers cannot mistake partial extraction for success.

`extract_batch` accepts an iterable of `UploadDocument`. It returns a plain
`dict` that is safe for `json.dumps`. A batch is limited to five documents by
default. Per-document failures do not raise; they appear in the response with a
status and warnings. Batch-level rejection returns no partial documents.

## Response envelope

```json
{
  "schema_version": "1.1",
  "batch": {
    "status": "completed",
    "document_count": 1,
    "total_bytes": 1148,
    "status_counts": {
      "extracted": 1,
      "partial": 0,
      "empty": 0,
      "scanned_pdf": 0,
      "encrypted": 0,
      "malformed": 0,
      "unsupported_format": 0,
      "too_large": 0
    },
    "limits": {
      "max_documents": 5,
      "max_file_bytes": 10485760,
      "max_batch_bytes": 26214400,
      "max_text_chars": 200000,
      "max_pdf_pages": 100,
      "max_docx_paragraphs": 20000,
      "max_docx_xml_bytes": 10485760
    },
    "error": null
  },
  "documents": [
    {
      "index": 0,
      "filename": "synthetic-cv.pdf",
      "format": "pdf",
      "status": "extracted",
      "text": "Synthetic Candidate\nExperience",
      "segments": [
        {
          "locator": { "kind": "page", "page": 1 },
          "text": "Synthetic Candidate\nExperience"
        }
      ],
      "warnings": [],
      "metadata": {
        "size_bytes": 1148,
        "page_count": 1,
        "paragraph_count": null
      }
    }
  ]
}
```

### Top-level fields

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | string | Contract version. Currently `"1.1"`. |
| `batch` | object | Batch outcome, counts and applied limits. |
| `documents` | array | One object per uploaded document, in input order. |

### `batch`

| Field | Type | Meaning |
| --- | --- | --- |
| `status` | string | `"completed"`, `"partial"` or `"rejected"`. |
| `document_count` | integer | Number of uploads supplied. |
| `total_bytes` | integer | Sum of supplied byte lengths. |
| `status_counts` | object | Count per document status; every status key is always present. |
| `limits` | object | Limits applied to this request. |
| `error` | object or null | `null` when completed or partial; otherwise `{"code", "message"}`. |

`batch.status` is a completeness signal:

- `"completed"` means every document has status `"extracted"`, so every
  document returned complete text.
- `"partial"` means processing finished, but at least one document is not fully
  extracted (`partial`, `empty`, `scanned_pdf`, `encrypted`, `malformed`,
  `unsupported_format` or `too_large`). Inspect `status_counts`, each document's
  `status` and its warnings. A partial batch maps to HTTP 200, not an error.
- `"rejected"` means the batch was not processed; `documents` is empty and
  `error` is set.

Do not treat `"partial"` as a successful complete extraction. A consumer must
not display a document's text as complete unless its status is `"extracted"`.

### `documents[]`

| Field | Type | Meaning |
| --- | --- | --- |
| `index` | integer | Zero-based position in the input batch. |
| `filename` | string | Sanitized basename only. |
| `format` | string | `"pdf"`, `"docx"` or `"unknown"`. |
| `status` | string | Extraction status (see below). |
| `text` | string | Extracted text, or `""` when unavailable. |
| `segments` | array | Text blocks with source locators. |
| `warnings` | array | Fixed warnings; empty when none apply. |
| `metadata` | object | Size and format-specific total counts. |

`text` is always exactly `"\n\n".join(segment["text"] for segment in segments)`.
This invariant lets the UI render either the full text or individual blocks.

### `segments[]` and locators

Each segment has `{"locator": {...}, "text": "..."}`.

PDF locator, with 1-based page numbers:

```json
{ "kind": "page", "page": 2 }
```

DOCX locator, with 1-based paragraph numbers and the nearest preceding heading:

```json
{ "kind": "paragraph", "paragraph": 4, "section": "Experience" }
```

- `paragraph` is the original 1-based body paragraph index, including empty
  paragraphs. Empty paragraphs do not produce segments, so indexes can have
  gaps.
- `section` is `null` before the first heading. A heading paragraph's own
  locator uses the heading text as its section. "Section" means the nearest
  preceding Word heading style or outline level, not a page-layout section
  break.
- DOCX table-cell paragraphs are included in document order.
- DOCX list-item text is included as ordinary paragraphs. Word list numbering,
  bullets and indentation are not synthesized; a segment for a list item
  contains only the text stored in that paragraph.
- DOCX headers and footers are not included.
- PDF segments preserve internal line breaks; pages are joined by a blank line.
- PDF text order follows the PDF content stream, not visual column order. A
  two-column page is not reconstructed into left/right reading order; both
  columns are returned only if the content stream contains both. Consumers must
  not infer visual layout from segment order.

### `metadata`

| Field | Type | Meaning |
| --- | --- | --- |
| `size_bytes` | integer | Supplied document size. |
| `page_count` | integer or null | Total PDF pages; `null` for DOCX, unknown or unreadable input. |
| `paragraph_count` | integer or null | Total DOCX body paragraphs; `null` for PDF, unknown or unreadable input. |

`page_count` and `paragraph_count` are totals, even when `max_pdf_pages`,
`max_docx_paragraphs` or `max_text_chars` limited how much was returned.

## Status values

| Status | Meaning | `text` |
| --- | --- | --- |
| `extracted` | Complete text was extracted: no truncation, no limit was hit, no processed page failed, and every processed PDF page had text. | non-empty |
| `partial` | Some text was returned, but extraction is incomplete (text truncation, page/paragraph limit, unreadable page, or page without text). | non-empty |
| `empty` | A valid or empty document yielded no text (blank pages, no body paragraphs or zero-page PDF). | `""` |
| `scanned_pdf` | Image-only PDF with no extractable text; OCR is required. | `""` |
| `encrypted` | Password-protected PDF; not decrypted. | `""` |
| `malformed` | Corrupt, truncated or structurally unreadable PDF/DOCX. | `""` |
| `unsupported_format` | Not PDF/DOCX, legacy `.doc`, or non-Word OOXML. | `""` |
| `too_large` | Exceeds a per-document or DOCX-part size limit. | `""` |

Statuses are stable strings. New statuses may only be added in a future schema
version.

### What “complete” means

`extracted` is a completeness claim, not merely “some text was found”. A
document is `partial` when it returns non-empty text but any of these warnings
is present:

- `text_truncated` — text was cut at `max_text_chars`.
- `page_limit_reached` — only the first `max_pdf_pages` pages were processed.
- `paragraph_limit_reached` — only the first `max_docx_paragraphs` paragraphs
  were processed.
- `page_extraction_failed` — one or more processed PDF pages could not be read.
- `pages_without_text` — one or more processed PDF pages yielded no text.

`partial` text is still useful for review, but it is not the complete document.
A consumer must treat it as incomplete, request a better source, or ask a human
to review it. It must never label partial text as a complete extraction.

`batch.status == "completed"` only when every document is `extracted`. Any
`partial`, `empty`, scanned, encrypted, malformed, unsupported or too-large
document makes the batch `"partial"`.

### PDF images and mixed pages

Completeness refers to the PDF **text layer**. Images are not OCR'd or
inspected. An image-only page in an otherwise textual PDF produces
`pages_without_text` and makes the document `partial`; if every page is
image-only, the status is `scanned_pdf`. A page that contains both text and an
image is treated as complete when its text layer was read; text that exists only
inside the image is not extracted. This is a known limitation, not a claim that
the visual page contains no other information.

## Warning codes

Warnings are `{"code": "...", "message": "..."}`. Messages are fixed English
text. They contain counts and limits only, never document content, exception
text or filesystem paths.

| Code | Typical status | Meaning |
| --- | --- | --- |
| `empty_document` | `empty` | No extractable text. |
| `empty_pdf` | `empty` | PDF has zero pages. |
| `scanned_pdf` | `scanned_pdf` | Image-only PDF; OCR required. |
| `pdf_encrypted` | `encrypted` | PDF requires a password. |
| `pages_without_text` | `partial` / `scanned_pdf` | Some processed PDF pages had no text. |
| `page_extraction_failed` | `partial` / `malformed` | Some PDF pages could not be read. |
| `page_limit_reached` | `partial` / `empty` / `scanned_pdf` / `malformed` | Only the first `max_pdf_pages` were read. |
| `paragraph_limit_reached` | `partial` / `empty` / `malformed` | Only the first `max_docx_paragraphs` were read. |
| `no_body_paragraphs` | `empty` | DOCX body contains no paragraphs. |
| `text_truncated` | `partial` | Text was cut at `max_text_chars`. |
| `document_too_large` | `too_large` | Per-document or DOCX XML size limit exceeded. |
| `unsupported_format` | `unsupported_format` | Not a supported document type. |
| `non_word_ooxml` | `unsupported_format` | OOXML ZIP that is not Word DOCX. |
| `legacy_doc` | `unsupported_format` | Legacy binary `.doc` is not supported. |
| `malformed_document` | `malformed` | Document could not be parsed safely. |
| `format_mismatch` | any | Extension differs from content; the content parser won. |

Format detection is content-based. A valid DOCX named `cv.pdf` is parsed as
DOCX and receives `format_mismatch`; the response `format` is `"docx"`.

## Compatibility

- This document describes schema `1.1`. It adds document status `partial` and
  batch status `partial`. Under `1.0`, `extracted` could describe text that was
  later truncated or limited; under `1.1`, such documents are `partial`.
  Consumers upgrading from `1.0` must treat unknown statuses as incomplete and
  must not display text as complete unless the status is `extracted`.
- Existing fields, types and locator shapes are stable within `1.1`.
- New optional warning codes may be added. The UI should render an unknown code
  using its `message` rather than assuming a fixed list.
- Removing or renaming a field, or adding a new document or batch status,
  requires a new `schema_version`.
- `warnings` order is deterministic but not semantically significant.

### Workspace integration note

The separate CV workspace adapter is a provisional `v0.1` UI contract, not this
parser-native schema. It must be updated or mapped before it can consume this
response directly. A safe mapping is:

| Parser value | Workspace value |
| --- | --- |
| batch `completed` | job `complete` |
| batch `partial` | job `partial` |
| batch `rejected` | request error, not a job |
| document `extracted` | document `extracted` |
| document `partial` | document `needs_review` |
| document `empty`, `scanned_pdf`, `encrypted` | `needs_review` or `failed`, according to UI policy |
| document `malformed`, `unsupported_format`, `too_large` | document `failed` |

The adapter must not map parser `partial` to `extracted`. This parser branch does
not modify the frontend or the adapter.

## Batch rejection

When the batch itself is rejected, `batch.status` is `"rejected"`,
`documents` is `[]`, all `status_counts` are zero and `batch.error` is set:

| Error code | Meaning | Suggested HTTP mapping |
| --- | --- | --- |
| `empty_batch` | No documents supplied. | 400 |
| `too_many_documents` | More than `max_documents` (default 5). | 400 |
| `batch_too_large` | Total bytes exceed `max_batch_bytes`. | 413 |

The Python module defines no HTTP routes by itself. The optional local
transport described in [HTTP transport](#http-transport-local-optional) returns
this object with only additive transport fields; both `completed` and `partial`
batches map to HTTP 200, even when some documents failed. Per-document
`too_large` is a document status, not a rejected batch.

## HTTP transport (local, optional)

`src/joblens_public/cv_parser/http_transport.py` exposes the parser over
loopback HTTP using only the Python standard library
(`http.server.ThreadingHTTPServer` and `email.parser`). It is a thin shell
around `extract_batch`: it does not re-implement extraction, does not change
the schema and does not keep state.

- Synchronous and terminal. A request returns the final extraction or a final
  error. There is no queue, no worker, no polling store and no persistence.
- Loopback only. The server binds `127.0.0.1`; there is no remote-bind option.
- No temporary file. Bodies, uploads and results live in memory.
- No dependency was added. `pypdf` is still the only runtime dependency, and it
  is required to serve PDF documents.

### Running it

```bash
PYTHONPATH=src python -m joblens_public.cv_parser.http_transport --port 8765
# or, after an editable install:
joblens-cv-server --port 8765
```

The process prints one banner line with the bound address and nothing else. By
default it logs nothing per request; `--access-log` adds a single metadata line
per request (method, route, status, duration, `job_id`) and never document
content, file names, headers or tokens.

### Request

```http
POST /api/cv/extractions HTTP/1.1
Host: 127.0.0.1:8765
Origin: http://127.0.0.1:8765
X-JobLens-Request: 1
Accept: application/json
Content-Type: multipart/form-data; boundary=----Boundary
Content-Length: 24576

------Boundary
Content-Disposition: form-data; name="files"; filename="cv.pdf"
Content-Type: application/pdf

<binary PDF bytes>
------Boundary
Content-Disposition: form-data; name="files"; filename="cover.docx"
Content-Type: application/octet-stream

<binary DOCX bytes>
------Boundary--
```

| Rule | Value |
| --- | --- |
| Route | `POST /api/cv/extractions` |
| Body | `multipart/form-data` with one or more parts named `files` |
| Documents per request | 1 to 5 (the parser rejects more with `too_many_documents`) |
| `filename` | Required on every `files` part; the parser sanitises it to a basename |
| Other fields | Ignored |
| Part `Content-Type` | Ignored; the parser detects PDF/DOCX from the content |
| `Content-Length` | Required. `Transfer-Encoding: chunked` is rejected with 411 |
| `Content-Encoding` | Only identity; `gzip` and others are rejected with 415 |
| Request body cap | `max_batch_bytes + 1 MiB` (26 MiB with the default limits) |
| Parts cap | 64 parts, a defensive bound well above the five-document contract |
| `Host` | Must be a loopback name or address |
| `Origin` | When present, must be loopback |
| `X-JobLens-Request` | Required on `POST`; a CSRF marker, not authentication |
| `Sec-Fetch-Site` | `cross-site` and `same-site` are rejected with 403 |

The multipart parser is strict. A missing boundary, a wrong boundary, a
truncated body, a nested multipart part, a `files` part without `filename` or
more parts than the cap are transport errors, not partial extractions. The
payload of every accepted part is preserved byte for byte.

### Response

A successful extraction is HTTP `200` with the parser object plus three
additive transport fields:

```json
{
  "transport_version": "1.0",
  "schema_version": "1.1",
  "job_id": "job_2f1c...",
  "batch": { "status": "completed", "document_count": 1, "...": "..." },
  "documents": [
    {
      "document_id": "doc_9ab4...",
      "index": 0,
      "filename": "cv.pdf",
      "format": "pdf",
      "status": "extracted",
      "text": "...",
      "segments": [{ "locator": { "kind": "page", "page": 1 }, "text": "..." }],
      "warnings": [],
      "metadata": { "size_bytes": 1148, "page_count": 1, "paragraph_count": null }
    }
  ]
}
```

- `schema_version` stays `"1.1"`. `batch`, `documents[]`, statuses, warnings,
  locators and metadata are exactly what `extract_batch` returned.
- `transport_version` is `"1.0"` and describes the transport additions only.
- `batch.status` is `completed` or `partial` in a `200`. A rejected batch is an
  error response, never a `200`.

A rejected batch keeps the parser object and adds a top-level `error` alias of
`batch.error`:

```json
{
  "transport_version": "1.0",
  "schema_version": "1.1",
  "job_id": "job_2f1c...",
  "batch": { "status": "rejected", "error": { "code": "empty_batch", "message": "..." } },
  "documents": [],
  "error": { "code": "empty_batch", "message": "A batch must contain at least one document." }
}
```

A transport error is a fixed, content-free body:

```json
{
  "transport_version": "1.0",
  "schema_version": "1.1",
  "job_id": "job_2f1c...",
  "error": { "code": "invalid_multipart", "message": "The multipart body is malformed." },
  "documents": []
}
```

### Identifiers

| Identifier | Format | Scope |
| --- | --- | --- |
| `job_id` | `job_` + 32 lowercase hex characters | One per request |
| `document_id` | `doc_` + 32 lowercase hex characters | One per document in the response |

They are random UUID4 values. They never contain a file name, a path or
document text, and they are not derived from the document index. They are
correlation identifiers for a single response: the transport stores nothing, so
they cannot be resolved later and `GET /api/cv/extractions/{job_id}` answers
`404 job_not_found`. Every document in the response has a `document_id`,
including documents that failed. Segment identifiers are left to the consumer,
as before.

### Status mapping

| Condition | HTTP | `error.code` |
| --- | --- | --- |
| `batch.status` is `completed` or `partial` | 200 | — |
| Rejected batch, `empty_batch` | 400 | `empty_batch` |
| Rejected batch, `too_many_documents` | 400 | `too_many_documents` |
| Rejected batch, `batch_too_large` | 413 | `batch_too_large` |
| Rejected batch, unknown code | 400 | the original code, unchanged |
| Document status `too_large`, `malformed`, `unsupported_format`, `empty`, `scanned_pdf`, `encrypted`, `partial` | 200 | — (document status) |
| Body larger than the request cap | 413 | `request_too_large` |
| Missing or chunked `Content-Length` | 411 | `length_required` |
| Invalid `Content-Length` | 400 | `invalid_content_length` |
| Body shorter than `Content-Length` | 400 | `incomplete_body` |
| Read timeout | 408 | `request_timeout` |
| Not `multipart/form-data` | 415 | `invalid_content_type` |
| Encoded body | 415 | `unsupported_content_encoding` |
| Malformed multipart, missing filename, nested part, too many parts | 400 | `invalid_multipart`, `missing_filename`, `invalid_part`, `too_many_parts` |
| Non-loopback `Host` or `Origin`, missing token, cross-site fetch | 403 | `invalid_host`, `invalid_origin`, `missing_request_token`, `cross_site_request` |
| Unknown route | 404 | `not_found` |
| `GET` on the extraction route | 405 | `method_not_allowed` |
| `GET` on a job id | 404 | `job_not_found` |
| Parser not importable | 503 | `parser_unavailable` |
| More concurrent extractions than allowed | 503 | `server_busy` |
| Unexpected failure | 500 | `internal_error` |
| Unexpected parser payload | 500 | `invalid_parser_response` |

### Privacy

- Document content, file names, request headers and tokens are never logged.
  The default is silence; `--access-log` only records metadata.
- Error messages are fixed strings. Exception text, local paths and file names
  never reach a response or a log line, and no traceback is printed.
- No temporary file is created: bodies, uploads, results and the multipart
  parse all stay in memory.
- Nothing is persisted. There is no job store, log of results or cache.
- Responses are sent with `Cache-Control: no-store`, `X-Content-Type-Options:
  nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`,
  `Cross-Origin-Resource-Policy: same-origin` and `Connection: close`.
- The `Server` header does not disclose the Python version.
- The response itself contains the extracted text. The caller must treat it as
  sensitive and must not log or persist it.

### Same-origin integration

The transport sends no CORS headers, so a browser must reach it on its own
origin. There are two supported ways to keep a browser on a single origin
without relaxing anything.

**1. Mount the route in the existing local application (recommended, and
already done in this repository).** `serve_extraction_request` is the shared
request-serving function: it takes the request headers, the binary stream and
a callable that runs `extract_batch`, and returns `(status, payload)`. An
application that already serves the workspace forwards one path to it:

```python
from joblens_public.cv_parser.http_transport import serve_extraction_request

# inside the existing do_POST handler
if self.path == "/api/cv/extractions":
    status, payload = serve_extraction_request(
        headers=self.headers,
        stream=self.rfile,
        extract_fn=extract_batch,      # joblens_public.cv_parser.extract_batch
        limits=DEFAULT_LIMITS,
    )
    self._json(status, payload)
    return
```

Because the route is served by the same process and the same origin as the
workspace, the browser issues a same-origin request and no CORS header is
needed. The host application keeps its own `Host`, `Origin` and
`X-JobLens-Request` checks; the transport's own checks then apply on top.

**2. Run the transport as its own loopback process behind a proxy.**
Start `joblens-cv-server` on `127.0.0.1` and let the existing local
application proxy `/api/cv/*` to it. The browser still talks to its own origin,
so no CORS header is needed. The proxy must forward the request with a
loopback `Host` and `Origin` and preserve `X-JobLens-Request`, because the
transport rejects anything that does not look like a same-machine request.

Either way, do not add `Access-Control-Allow-Origin: *`. The transport is a
local tool: it has no TLS, no authentication and no rate limiting, and it must
never be exposed beyond loopback.

### The permanent mount in the demo application

`src/joblens_public/webapp.py` mounts the transport in the main local
application, which is the launcher used by `run_demo.py`. There is no second
application server.

| Route | Method | Behaviour |
| --- | --- | --- |
| `/api/cv/extractions` | `POST` | The extraction route. Same contract, same limits and same errors as the standalone transport. |
| `/api/cv/extractions/{job_id}` | `GET` | `404 job_not_found`. The mount keeps no state either. |
| `/api/cv/extractions` | `GET` | `405 method_not_allowed` with `Allow: POST`. |
| `/workspace/` | `GET` | The CV workspace page. |
| `/workspace/index.html`, `/workspace/app.js`, `/workspace/api-adapter.js`, `/workspace/styles.css`, `/workspace/favicon.svg` | `GET` | The approved workspace assets. |
| `/workspace` | `GET` | `302` to `/workspace/`, so relative asset URLs resolve. |

Mounting rules:

- The extraction route is handled **before** the JSON-only validation of
  `/api/analyze`, so the CV limits apply to it. The 64 KiB JSON limit of
  `/api/analyze` is unchanged.
- The mount reuses the transport's multipart parsing, bounded body read,
  request validation, identifiers, error mapping and concurrency gate. The
  transport calls `handle_upload_request` exactly once per request.
- The mount inherits the application's own loopback `Host`, `Origin` and
  `X-JobLens-Request` checks, and answers with the application's `no-store`
  security headers.
- The workspace assets are served from an explicit allow-list. The request
  path is matched exactly, so `/workspace/fixtures/...`, source files, test
  files and traversal paths can never be read. Only `index.html`, `app.js`,
  `api-adapter.js`, `styles.css` and `favicon.svg` are reachable.
- The workspace bundle is assembled in a separate worktree. Until it is
  assembled here, `/workspace/` answers `404` with a clear message instead of
  failing. The demo routes are unaffected.
- The application imports the transport, not the parser implementation, so
  the demo still starts without `pypdf`. In that case the extraction route
  answers `503 parser_unavailable`.


### Testing

```bash
python3 -m pytest -q tests/test_cv_http_transport.py tests/test_cv_http_e2e.py
python3 -m pytest -q tests/test_cv_mount.py
```

The end-to-end tests start a real server on an ephemeral loopback port and
talk to it over HTTP with the standard library. They cover multipart binary
integrity, PDF and DOCX extraction, five accepted and six rejected documents,
complete, partial and failed documents, identifier and schema correctness, the
status mapping, the request limits, the privacy guarantees, the absence of
temporary files and the standalone entry point.

The mount tests exercise the same transport through the main application:
the extraction contract, the single call to `handle_upload_request`, the
unchanged demo routes, the unchanged 64 KiB JSON limit, the workspace asset
allow-list and the refusal to serve fixtures, source files or traversal paths.

## Limits

| Limit | Default | Applies to |
| --- | --- | --- |
| `max_documents` | 5 | Batch rejection. Hard maximum is 5; callers may lower it. |
| `max_file_bytes` | 10 MiB | Per-document `too_large` status. |
| `max_batch_bytes` | 25 MiB | Batch rejection before parsing. |
| `max_text_chars` | 200,000 | Returned `text` and segments; adds `text_truncated` and status `partial`. |
| `max_pdf_pages` | 100 | Pages processed; adds `page_limit_reached` and status `partial` when text remains. |
| `max_docx_paragraphs` | 20,000 | Paragraphs processed; adds `paragraph_limit_reached` and status `partial` when text remains. |
| `max_docx_xml_bytes` | 10 MiB | Uncompressed `word/document.xml`; adds `document_too_large`. |

Limits are included in every response under `batch.limits`. Applications may
pass a `ParseLimits` instance to `extract_batch`/`extract_document`; the defaults
are the public contract.

## Non-goals

- No OCR of scanned PDFs. Return `scanned_pdf` (or `partial` when text pages
  are mixed with image-only pages) and let the UI request a text PDF or run a
  separate, explicit OCR step.
- No dependency on the evaluator, evidence bank, candidate profile or job
  posting. The parser package does not import `joblens_public.core`.
- No classification of sections, skills, employers, dates, degrees or contact
  details. Only raw text and structural source locators are returned.
- No visual layout reconstruction. PDF text order follows the content stream;
  two-column pages are not reordered into columns. DOCX list bullets and
  numbering are not synthesized, and table layout is flattened into paragraph
  order.
- No guarantee that a PDF's visual layout matches `text` ordering.

## Verification

```bash
python3 -m pytest -q
ruff check .
```

The tests generate synthetic PDFs and DOCX files in memory. No real CVs or
personal data are committed. The HTTP transport tests also start a real
loopback server and exchange real HTTP requests with it; they use the same
synthetic documents.
