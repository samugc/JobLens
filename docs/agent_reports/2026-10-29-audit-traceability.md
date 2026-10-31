# JobLens — Bounded Engineering Audit (Traceability & Privacy)

Date: 2026-10-29 · Scope: 8 files read (cv.py, release_guard.py, profile/approved.py, export/adapter.py, export/api.py, requirements.py, webapp.py, tests). Read-only, no test suite run.

## 1. Export evidence check is optional and non-predicating — HIGH

- `src/joblens_public/export/adapter.py:333-368` — `validate_export(..., evidence_support=None)`; cross-check only runs when a support object is passed, and it only asserts that every `approved_fact_ids` string appears in the support set (line 358-368).
- `src/joblens_public/export/api.py:64, 94, 123, 140` — all four public export functions default `evidence_support=None`, so `export_cv_pdf/dcox_bytes(draft)` performs **no fact traceability check at all**.
- Why it matters: "every item cites approved facts" degrades to "every item has a non-empty list of strings". Any caller that builds/loads a `CvDraft` and calls the renderer directly bypasses the whole grounding contract, and the check never verifies that item text is entailed by those facts.
- Existing protections: HTTP path (`webapp.py:969`) always passes support from `release_guard.export`, and per-item HMAC receipts bind text + contact (`release_guard.py:169-181`). Library API has none.
- Regression test: build a draft with `approved_fact_ids=["fact_does_not_exist"]`, approve it, call `export_cv_pdf_bytes(draft)` with no support → currently must *not* silently succeed; assert `EvidenceContractError`. Minimal fix: make `evidence_support` required, or default to rejecting unknown/unlisted ids.

## 2. User edit keeps stale fact citations — HIGH

- `src/joblens_public/cv.py:725-757` — `edit_cv_item` replaces `text` but copies `approved_fact_ids=item.approved_fact_ids` unchanged (line 739).
- `src/joblens_public/cv.py:779-780` — `approve_cv_item` only rejects an empty id list; it never checks that the (possibly arbitrary) new text is supported by those ids.
- Why it matters: a user can edit a factual item to add an unverified claim (e.g. "AWS Certified"), re-approve, and the draft then presents a fabricated claim carrying valid-looking source citations — the exact failure the product must prevent.
- Existing protections: approval is revoked on edit (`needs_review`) and `tests/test_cv_generation.py:150` asserts that; the HTTP guard labels non-baseline wording as `candidate_attested` and rewrites ids to `attestation:<item_id>` at export (`release_guard.py:221-225`), which is a real mitigation for the web path only.
- Regression test: approve an item, `edit_cv_item(draft, id, "AWS Certified Cloud Practitioner")`, `approve_cv_item` → assert either the fact ids are cleared/flagged or export is refused. Minimal fix: on edit, clear `approved_fact_ids` (or attach them only if text ⊆ evidence tokens).

## 3. Optional LLM rewrite is guarded by token-subset only — MEDIUM

- `src/joblens_public/cv.py:711-719` — rewrites are accepted when `rewritten_tokens ⊆ approved_tokens ∪ tokens(original text)`.
- Why it matters: a bag-of-words subset permits reordering, negation, and cross-fact recombination ("5" from one fact + "engineers" from another), and the original summary text tokens are admitted wholesale — so the check is close to vacuous. The rewritten item also inherits the unmodified `approved_fact_ids` (line 645-652), implying support the new sentence may not have.
- Existing protections: opt-in only (`ollama=True`), localhost endpoint, failure falls back to the deterministic item, result returns `needs_review`.
- Regression test: feed `_ollama_rewrite_summary` a fake response `"Managed 40 engineers"` where `40` and `engineers` occur in unrelated facts → must return `None`; additionally assert number tokens map to the same fact as their noun. Minimal fix: require each number/proper noun to appear in a single evidence quote.

## Not a finding (verified)

Localhost-only bind, Host/Origin/`X-JobLens-Request` checks, `Cache-Control: no-store`, CSP (`webapp.py:281-312, 430-437`); PDF/DOCX metadata set only to the user-supplied name (`render_pdf.py:313`, `render_docx.py:152`); evaluation writes metrics only, no PII (`evaluation/harness.py:424`, `results.json`).

## Next action

Make export traceability mandatory: remove the `evidence_support=None` default in `export/` and add the "unknown fact id is rejected" regression test — one change closes the widest gap between the stated invariant and the code.
