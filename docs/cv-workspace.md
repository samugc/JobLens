# CV evidence workspace

An isolated, English-language interface for uploading up to five CV PDF or DOCX
files, running the existing parser service and inspecting the text it actually
returned, with the page or paragraph reference the parser gave for each block.

The workspace is intentionally a *viewer*. It does not extract text, does not
score anyone and does not decide whether a CV is good.

## Where it lives

```
web/workspace/
  index.html          markup for the workspace
  styles.css          isolated styling (JobLens look, workspace classes only)
  app.js              DOM wiring: selection, upload, reader, review, reconciliation
  api-adapter.js      the only file that knows the parser wire format
  profile-adapter.js  the only file that knows the profile wire format
  profile-review.js   the review rules: approve, reject, edit, conflicts
  reconciliation-adapter.js  the only file that knows the reconciliation wire format
  favicon.svg         workspace favicon
  fixtures/*.json     synthetic, contract-compliant parser responses for tests
```

The public demo (`web/index.html`, `web/app.js`, `web/styles.css`) and the
backend (`src/joblens_public/`) are untouched. Nothing here is served by the
public demo server unless you mount it yourself (see
[Integration requirements](#integration-requirements)).

The workspace has three views: the **extraction report** described here, the
**candidate profile review** view described in
[docs/cv-profile-workspace.md](cv-profile-workspace.md), and the
**reconciliation** view described in
[docs/cv-reconciliation-workspace.md](cv-reconciliation-workspace.md). The
profile and reconciliation views are reviewer interfaces for the local
profile engine and the local reconciliation engine: the profile view reviews
the proposals of the engine, and the reconciliation view shows the claims a
source states, the relationships the engine infers between them and the
decisions it proposes. Both views never fabricate a proposal, never touch the
extraction flow and never approve anything on their own.

All visible copy is English. Engine output is shown verbatim and is always
labelled as such: `Engine text` for a warning or explanation, and
`The engine explains` when a reconciliation decision is justified.

## Run it

### With the local engine (the real flow)

The demo server mounts the CV routes and this workspace on the same origin, so
the browser never leaves the machine:

```sh
python3 run_demo.py --port 8765
# → http://127.0.0.1:8765/workspace/
```

`POST /api/cv/extractions`, `POST /api/cv/profiles` and
`POST /api/cv/reconciliations` are answered by that server, so the extraction
report, the candidate profile review and the reconciliation report all show
real output of the local engines. The routes require a loopback `Host` and
`Origin` and the `X-JobLens-Request: 1` header, and they send no CORS
headers: a browser has to reach them on their own origin.

`pypdf` is required for the PDF parser. Without it the demo still starts and
the CV routes answer `503 parser_unavailable`.

### Preview with no parser (honest error states)

```sh
python scripts/serve_cv_workspace.py
# → http://127.0.0.1:8765/workspace/
```

This serves `web/workspace/` only and answers every request under `/api/cv/`
with HTTP `503` and `{"error": {"code": "parser_unavailable", ...}}`. That is the
point: the preview proves the workspace cannot fake a successful extraction. You
can inspect the empty, loading and error states here.

### Automation

```sh
node --test tests/ui/           # adapter and contract logic
pytest -q                       # Python tests, including asset and server checks
ruff check .
```

`tests/test_release_safety.py` also scans `web/`, `docs/`, `scripts/` and
`tests/` for private contact data and for inline scripts or styles, so the
workspace stays consistent with the public snapshot rules.

## Guided review

The three views are presented as numbered steps: **1 Documents**, **2 Profile**
and **3 Consistency**. The tabs are an ARIA tablist: Left/Right move between
steps, Home/End jump to the first/last step, and `aria-selected` follows the
active panel. A `Next step` bar states the current action and offers one
button for it (choose files, analyse, create the profile, review proposals or
open what needs attention). The action is derived from the real state; it never
claims a step is complete when it is not.

Once an extraction exists, the introductory hero collapses and the working
area moves up. At 920 px and below the steps and results come before the upload
rail, so a phone user does not have to scroll past the uploader to review the
documents they just analysed. On first load the uploader remains first.

The extraction report shows, in order: the source documents and their statuses,
the batch summary (documents, text blocks, words), the document cards, and the
reader. Counts are counts of parser output, not progress. Engine warnings show a
short English summary followed by the verbatim message labelled `Engine
text`; raw warning codes are not part of the primary path. The reader and any
technical references stay in expandable panels, closed by default.

## What the interface guarantees

- **Up to five documents.** Extra files are rejected with a visible reason.
  `.pdf` and `.docx` only; empty files are rejected.
- **A 25 MiB batch cap.** The aggregate size of the selection is checked before
  a request is built, using the parser's default `max_batch_bytes`. A selection
  over the limit is refused with the parser's own `batch_too_large` code and
  nothing is sent. Per-document limits and every document status stay the
  parser's decision.
- **Honest loading states.** While waiting, the workspace says it is contacting
  the parser. It never shows progress it did not receive.
- **One POST, one result.** The upload returns a terminal batch, so the
  workspace renders the answer without polling.
- **Statuses come from the parser.** The eight parser document statuses
  (`extracted`, `partial`, `empty`, `scanned_pdf`, `encrypted`, `malformed`,
  `unsupported_format`, `too_large`) and the three batch statuses (`completed`,
  `partial`, `rejected`) are the parser's words. The workspace shows its own
  visual status next to the original parser status and never replaces it.
- **Every text block keeps its reference.** A 1-based page or paragraph number
  from the parser is shown on the block and in the reader, including the DOCX
  section heading the parser reported.
- **Warnings and failures stay visible.** A known parser warning gets a short
  English summary on the document card, while the parser's own message is shown
  verbatim and labelled `Engine text` in the reader warning card. A failed
  document says why it failed instead of showing an empty reader.
- **The session mode is named.** The masthead says `No data loaded`, `Your
  local documents` or `Synthetic sample`. An uploaded CV is never called
  synthetic, and the footer says `local, in-memory session`.
- **Every claim stays reachable.** The Consistency view shows every source
  claim: in a decision card, in a joined group, or in the remaining-claims
  group with its exact quote.
- **Claim support and citation matching are named apart.** A claim is an
  `Explicit claim` or a `Keyword mention`; a quotation is a `Citation matched`,
  a `Citation mismatch` or `Citation not checked`. Citation matching is never
  called verification and never proves a claim.
- **No persistence and no repair.** Refreshing loses the session. The workspace
  does not fill in missing text or downgrade a failure.

## Integration requirements

For a real deployment the host application must provide:

1. **Static assets.** Serve `web/workspace/` under a stable base such as
   `/workspace/`. All asset links are relative (`./styles.css`, `./app.js`,
   `./api-adapter.js`), so the directory can move as a unit.
2. **The parser routes.** `POST {base}/extractions` implemented per
   [the contract](cv-workspace-contract.md), and the correct `base` in the
   `joblens-cv-api-base` meta tag. The route must accept `multipart/form-data`
   with repeated `files` parts and must answer with the terminal batch
   envelope. `GET {base}/extractions/{job_id}` is optional: schema 1.1 has no
   non-terminal batch status, so the workspace never polls for the result.
   The two reviewer routes are mounted next to it and take the same source
   documents as JSON: `POST {base}/profiles` answers with the profile envelope
   and `POST {base}/reconciliations` with the reconciliation report. See
   [cv-profile-workspace.md](cv-profile-workspace.md) and
   [cv-reconciliation-workspace.md](cv-reconciliation-workspace.md).
3. **Content Security Policy.** The workspace uses no inline scripts or styles,
   so `script-src 'self'; style-src 'self'` is enough. If the parser lives on a
   different origin, add it to `connect-src` (and decide on CORS/credentials;
   the adapter sends `credentials: "same-origin"`).
4. **Upload size limits.** The workspace refuses a selection over 25 MiB
   (the parser's default `max_batch_bytes`) before sending it. The parser or
   its reverse proxy still enforces that limit authoritatively, and a request
   that reaches the server over the limit must be refused with a JSON error
   body using the parser error codes (`empty_batch`, `too_many_documents`,
   `batch_too_large`). A body over the transport's own request cap is refused
   with `413 request_too_large`; the workspace reports that separately.
5. **Contract alignment.** The adapter already targets parser schema 1.1 over
   transport 1.0. A future schema change stays inside `api-adapter.js`, the
   fixtures, the adapter tests and the contract document.

No other workspace file should need to change when the wire format changes.

## Explicit non-goals

- No second parser and no PDF/DOCX parsing in the browser.
- No synthetic or placeholder extraction. The preview server returns `503`; the
  fixtures are used only by tests and manual inspection.
- No agent, no Ollama, no SQLite, no scoring, no candidate ranking.
- No persistence, accounts, or background jobs of its own.
- No modification of the public demo UI or the backend evaluator.
