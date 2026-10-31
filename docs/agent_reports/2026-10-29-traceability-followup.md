# JobLens — Traceability Follow-up (Verification + Minimal Remediation)

Date: 2026-10-29
Base commit: `0061c2b` (main, untouched)
Work branch: `fix/evidence-provenance`
Report: `docs/agent_reports/2026-10-29-traceability-followup.md` (migrated from the private AI-CAREER-LAB JOBLENS reports tree)

## 1. Findings: reproduced or disproved

| # | Finding | Verdict | Where it is real |
|---|---------|---------|------------------|
| 2 | Edited items keep misleading evidence references | **Reproduced** | Library/CLI (`cv.py`): edit kept the original ids, `approve_cv_item` accepted fabricated wording, and the draft exported as fact-supported. |
| 1 | Unsupported fact ids bypass the export evidence contract | **Reproduced, scoped** | Library/API: `evidence_support=None` skipped all checks; foreign `attestation:<other>` ids passed. In the HTTP app, per-item HMAC receipts already bound ids to content, so it was not an app exploit — but the adapter cross-check is fed a support list derived from the very item ids it validates, so it proved nothing. |
| 3 | LLM rewrite guard accepts unsupported semantic changes | **Reproduced** | Token-subset check accepted “Data engineer with 5 years Python” when the tenure fact belonged to SQL (cross-fact conflation). Not exploitable via the app: `webapp.py` always passes `ollama=False`. |

Reproduction scripts (throwaway, outside the repo) produced before/after evidence:

```
before: re-approved fabricated text → export b'%PDF'
        bogus fact id, no support    → b'%PDF'
        foreign attestation id       → b'%PDF'
after:  approve without attest        → ValueError (needs candidate attestation)
        no support                   → EvidenceContractError
        foreign attestation id       → EvidenceContractError
```

## 2. Design

One provenance model, no semantic claims:

- `CvDraftItem.provenance` ∈ `source` | `stale` | `attested`.
  - `source`: unaltered generated wording, backed by the cited fact ids.
  - `stale`: wording changed by `edit_cv_item` or an accepted model rewrite; the ids are retained only as an audit trail.
  - `attested`: candidate vouched for non-baseline wording; citation is `attestation:<item_id>`, so it can never be confused with a real fact id.
- `approve_cv_item(..., attest=False)`: stale items require explicit attestation, which rewrites the citation. Unedited items behave exactly as before.
- Export fails closed when citations cannot be checked. Renderer-only input must say so: `evidence_mode: "unverified"`. Passing `evidence_support` still checks **id membership only** — that is stated in the docstring and is not presented as entailment.
- Attestation ids must name their own item and cannot be mixed with approved-fact citations.

## 3. Changes made

| File | Change |
|------|--------|
| `src/joblens_public/cv.py` | Provenance constants/field; `as_dict` emits it only when ≠ `source` (legacy shape preserved); `from_dict` validates it; edit and accepted rewrite mark `stale`; `approve_cv_item` gains keyword-only `attest`; eligibility reports stale items; honest docstring on the token guard. |
| `src/joblens_public/export/models.py` | `CanonicalItem.provenance`, `CanonicalDraft.evidence_mode` (appended, defaulted). |
| `src/joblens_public/export/adapter.py` | Parse/validate provenance and evidence mode; `_validate_item_citations` rejects stale wording, empty/duplicate ids, foreign attestations, mixed citations; fail closed when support is absent. |
| `tests/test_evidence_provenance.py` | **New**, 12 regression tests. |
| `tests/export/test_helpers.py` | Fixtures declare `evidence_mode: "unverified"` (they test rendering only). |
| `tests/export/test_parser_integration.py` | Real-draft export now passes support, documenting the required contract. |

Not touched: `webapp.py`, `release_guard.py`, renderers, evaluation harness, any user data.

## 4. Tests and results

```
pytest tests/test_evidence_provenance.py tests/export tests/test_cv_generation.py tests/test_simple_flow.py
  53 passed in 2.65s
pytest -q            → 602 passed in 40.08s   (was 590 before; +12 new)
ruff check (changed files) → All checks passed
python -m evaluation.run_evaluation --output <temp>
  19 ok, 1 expected error, 0 failed · facts 55/55 · insertions 0/21 · gaps 0/17 · Jaccard 1.0 · enforcement 65/65
```

`tests/test_simple_flow.py` still exports a `candidate_attested` item end to end through HTTP, confirming the app path is unchanged.

## 5. Compatibility notes

- `CvDraftItem`: field appended last — positional construction unchanged; JSON shape unchanged for `source` items.
- `approve_cv_item`: existing calls keep working; only stale items need the new `attest=True`.
- Export: **behaviour change** — source-cited drafts now require `evidence_support`. Callers that render drafts directly must pass support or declare `evidence_mode="unverified"`. No in-repo caller other than two test fixtures was affected.
- No schema version bump: an old JSON without `provenance`/`evidence_mode` loads as `source` / `cited_facts`.

## 6. Remaining limitations

- **No semantic verification.** Matching fact ids proves only that an id is registered, never that a sentence is entailed by it. A fabricated sentence approved with `attest=True` exports as attested, which is the product's intended escape hatch, but "attested" is not "verified".
- The app's `evidence_support` is still assembled from receipt-verified item ids (`release_guard.py:225`), not from a stored fact catalogue. In-app integrity rests on the HMAC receipts; a future change could embed the trusted fact-id set in the issued draft to make the cross-check independent.
- Re-editing text back to its original wording still leaves the item `stale` (conservative; requires re-attestation).
- No UI change: the web workspace keeps its own receipt-based attestation flow and does not display item-level provenance.

## 7. Git status

```
Branch: fix/evidence-provenance  (created from 0061c2b / main)
Commit: 3e29e98 fix(provenance): invalidate stale citations and fail closed on unverifiable export
main: unmodified, nothing pushed
Untracked (pre-existing, not mine): evaluation/results.json
```

## 8. Recommendation

Merge after review as one focused commit; it removes the silent “edited text still cites source facts” failure and makes unverifiable exports impossible by default without touching the HTTP flow. Before merge, decide whether the `evidence_mode="unverified"` opt-out should be documented in `README.md`, and schedule the independent-support follow-up (embed trusted fact ids at draft issuance).
