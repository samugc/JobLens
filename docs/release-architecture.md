# Local product contract

## Routes

- `GET /`: main upload → posting → draft → review → download application.
- `GET /workspace/`: optional advanced evidence/profile tools.
- `GET /demo/`: historical synthetic evaluator; `/api/bootstrap` and `/api/analyze` retained.
- `POST /api/cv/extractions`: existing multipart transport 1.0, parser schema 1.1.
- `POST /api/cv/draft`: `{source: {job_id, documents}, text}`. Returns `{draft}` with CvDraft 0.1 fields and a signed review baseline. Claims remain provisional; no ApprovedFact is created.
- `POST /api/cv/confirm`: `{draft, confirmed: true, attested: true}`. Explicitly confirms all current wording and contacts. Changed/new wording is recorded as candidate-attested, not documentary. Returns a signed final receipt bound to the canonical complete draft.
- `POST /api/cv/cv-drafts/export/pdf` and `/docx`: `{draft, confirmed: true, contact}`. Reject missing/forged/stale receipts, changed content, unreviewed items and mismatched contacts. Return actual bytes, appropriate MIME type and attachment filename.

Existing profile, reconciliation, approved-profile, draft/edit/approve routes remain
available for advanced review. Advanced profiles carry source evidence, are regenerated
against canonical proposals on import and require explicit confirmation. The public
main flow does not need these screens.

## Integrity boundary

`provisional.py` builds typed provisional source records, using the existing deterministic
generator without pretending they are approved facts. Profile conflicts and nontrivial
reconciliation relationships block overlapping evidence. Recommendations do not choose
an impressive claim automatically. Experience entry citations retain full source lines
so employer and dates survive export. Exact evidence remains available in the signed
baseline. Legacy `approved_fact_ids` is retained for CvDraft/export compatibility; in a
provisional baseline these identifiers denote source proposals, not prior approvals.

`release_guard.py` signs canonical JSON with an ephemeral HMAC key. Individual review
receipts bind content, section identity and evidence references. Main-flow final receipts
also bind contacts and order. No personal data or signing key is persisted. A changed
item needs a new confirmation, and its changed wording is explicitly candidate-attested.
The app cannot establish the real-world truth of a statement or prove who clicked a button.

The browser never supplies authority merely by setting `review_status` or supplying an
ID. Sources are untrusted local input; schema, exact citations, canonical reconstruction
and conservative conflict checks are applied before issuing a baseline. Pasted postings
are data and never executed as instructions. No external model is called.

## Release checks

Run the README commands. Then in Safari: upload two fictional files, paste a posting,
generate, check quotations and omitted details, edit an entry, enter fictional contacts,
confirm, download and open both files. Edit again and verify downloads are disabled
until reconfirmed. Reload and confirm the session clears. Check the network panel for
same-origin requests only. Do not use real candidate files for public screenshots.
