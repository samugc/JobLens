# JobLens — Evidence Authority & Export Security (Follow-up)

Date: 2026-10-29
Predecessor: `2026-10-29-traceability-followup.md`
Branch: `fix/evidence-provenance`
Commits: `3e29e98` (prior, unmodified) → **`625a9fa`** (this cycle)
Base main: `0061c2b` (untouched)

---

## 1. Initial Git state

```
branch: fix/evidence-provenance
HEAD:   3e29e98  fix(provenance): invalidate stale citations and fail closed on unverifiable export
main:   0061c2b  docs(gate): finalize pre-merge closure and supersede blocking verdict
worktree: clean except pre-existing untracked evaluation/results.json
stashes: stash@{0} (feature/cv-parser), stash@{1} (feature/cv-interface) — untouched
```

No merge, push, tag, deploy or publish. No stashes, archives, private CVs or untracked results were read or modified.

## 2. Audit of the prior cycle

The previous commit was re-read and attacked. Two problems survived it:

1. **`evidence_mode: "unverified"` was data-driven.** The flag lived inside the draft JSON. The HTTP handler rebuilds the payload through `CvDraft.from_dict`/`as_dict`, so it was inert there — but any integration forwarding untrusted JSON to the library could activate the bypass by adding one field. Requirement: the bypass must require code, not data.
2. **The export "support" set was self-derived.** `release_guard.export` built `support` from `out_item["approved_fact_ids"]` — the very list the adapter then validated. Even with a profile present, the cross-check proved nothing; it was a signed whitelist derived from the draft it was checking.

The `source` / `stale` / `attested` model itself held: stale wording cannot be approved without attestation, and attested output is labelled `attestation:<item_id>`. It was kept unchanged.

## 3. Confirmed vulnerabilities and scope

| ID | Issue | Reachable via HTTP? | Severity |
|----|-------|--------------------|----------|
| V1 | Export evidence support derived from the draft's own ids (tautological check) | Integrity only: HMAC item receipts still bound ids to the signed baseline, so no fabrication path was found *today*. It is a latent failure: one refactor that relaxes receipts and the contract becomes decorative. | High (defence in depth) |
| V2 | `unverified` rendering could be enabled by a JSON field rather than code | No in-repo HTTP path (payload is rebuilt); yes for third-party library callers forwarding untrusted JSON | Medium |
| V3 | No independent record of which fact ids were authorised for a draft | No — but it is the missing primitive behind V1 | High |

No remote code execution, data exfiltration, or fabricated-export path was demonstrated through the HTTP app. Reported as such; no HTTP vulnerability is claimed.

## 4. Trust model

**Trusted:** server process memory, `ReviewGuard.key` (32 random bytes per process), the validated `ApprovedProfile` (imported and evidence-checked against source), the provisional evidence built by `draft_from_source`, and code-level call arguments.

**Untrusted:** every byte of the draft JSON returned to and resent by the browser, including `sections`, `approved_fact_ids`, `review`, `evidence_mode`, and any extra fields.

**Rule:** anything read from the draft can only be *checked*, never *trusted*. Export therefore needs a record created on the trusted side, bound to the untrusted content:

```
authority = HMAC("authority", {
    session_id,                     # process/session binding
    basis: "approved_profile" | "provisional_source" | "none",
    fact_ids: [...],                # server-validated ids only
    items: {item_id: [fact_id]}     # documentary citation issued for that item
})
```

- `fact_ids` comes from `approved_profile.facts` or `provisional_evidence.keys()` — never from the draft.
- `items` binds each item to the ids issued for it, so swapping ids between items fails.
- The session id makes an old record unusable after restart.
- Candidate attestations are deliberately *outside* this record; they are authorised by the per-item HMAC (`content` + `mode` + `contact`) and materialise as `attestation:<item_id>`.

## 5. Implemented corrections (`625a9fa`)

| File | Change |
|------|--------|
| `release_guard.py` | `issue_draft(draft, *, approved_profile=None, provisional_evidence=None)` builds and signs the authority record; `_trusted_authority` verifies it at export; documentary items must match the signed per-item mapping and be a subset of the authorised ids; `support` returned to the renderer is the authority set plus confirmed attestations. |
| `webapp.py` | Passes the validated profile (`/api/cv/cv-drafts`) or the provisional evidence (`/api/cv/draft`) at issuance. Two call sites, no flow changes. |
| `export/adapter.py` | `evidence_mode` removed from payload parsing; `validate_export(..., allow_unverified=False)`; data can no longer disable verification. |
| `export/api.py` | `allow_unverified` added as a keyword-only argument to all four renderers, default `False`, shared by PDF and DOCX. |
| `export/models.py` | Unused `evidence_mode` field removed. |
| Tests | New `tests/test_evidence_authority.py`; exported fixtures now pass `allow_unverified=True` explicitly. |

No frontend change, no new dependency, no storage, no change to semantic matching.

## 6. Attack tests and outcomes

`tests/test_evidence_authority.py` — 16 tests, all passing:

| Attack | Result |
|--------|--------|
| Strip `review.authority` | `missing_authority` |
| Append an id to `authority.fact_ids` | `invalid_request` (HMAC) |
| Replay authority in another guard/session | `session_expired` |
| Add a documentary id to an item | refused (item receipt + mapping) |
| Swap ids between two items | refused |
| Issue without a validated source, export documentary ids | `unknown_evidence` |
| `evidence_mode: "unverified"` in draft JSON (PDF + DOCX) | `EvidenceContractError` |
| `evidence_mode` / `allow_unverified` in an HTTP body | inert; unapproved draft still 400; valid draft unaffected |
| Python `allow_unverified=True` + wrong `evidence_support` | still rejected (membership enforced) |
| Attested item | exported as `attestation:<id>`, never as a fact |
| Support set | equals the authority set, not the item list |

Written before the implementation: 13 of 16 failed against `3e29e98`, confirming they exercise the real gap.

## 7. Verification

```
pytest tests/test_evidence_authority.py                   16 passed
pytest tests/test_evidence_provenance.py                  12 passed
pytest tests/test_release_safety.py tests/test_release_workflow.py \
       tests/test_integrated_release.py \
       tests/test_evidence_provenance.py tests/test_evidence_authority.py
                                                          43 passed
pytest -q                                                 618 passed  (baseline 602; +16)
ruff check src tests                                      All checks passed
python -m evaluation.run_evaluation                       19 ok, 1 expected error, 0 failed
                                                          55/55 facts, 0/21 insertions,
                                                          4/4 conflicts, 22/22 recall,
                                                          0/17 gap contradictions, Jaccard 1.0,
                                                          65/65 review enforcement
```

Covered flows: provisional HTTP draft → edit → confirm → export (PDF and DOCX), approved-profile → draft → approve → export (`test_release_workflow`), release safety/PII scan, and the compiled end-to-end release run. One regression surfaced and was corrected in the test itself: `test_changing_contact_after_confirmation...` exported a draft issued with no validated source; under the new invariant that must fail, so the test now issues with an explicit stub profile. This is the intended behaviour change, not a weakened assertion.

## 8. Compatibility impact

- `issue_draft` gained optional keyword arguments — existing calls keep working (they produce an authority with `basis="none"`, which cannot export documentary ids).
- `export_cv_*` gained `allow_unverified=False`. Calls that rendered unsupported drafts with no `evidence_support` now raise unless they opt in; ~30 test call sites were updated.
- `evidence_mode` is no longer read. Drafts carrying it are unaffected (ignored).
- Drafts issued before this commit (or after a server restart) export with `missing_authority` / `session_expired`; the user regenerates the draft. No persisted state to migrate.
- HTTP status/error shapes unchanged (still 400 with `code` + `error`).

## 9. Remaining limitations

**Semantic entailment is still out of scope.** Identifier validity, evidence attribution and entailment are three different guarantees:

| Layer | Question | Status |
|-------|----------|--------|
| Identifier validity | Was this id issued by the server for this draft/session? | **Guaranteed** by the signed authority. |
| Evidence attribution | Does the id belong to *this* item, and was the wording attested? | **Guaranteed** by the per-item mapping and receipt. |
| Semantic entailment | Does the evidence actually support the sentence? | **Not checked.** |

Canonical example: Evidence A says “5 years of SQL”; Evidence B says “Python experience”. The statement “5 years of Python experience” uses only valid, correctly attributed identifiers and would pass every check in this cycle. It is unsupported. This is a research problem (claim decomposition, unit/subject binding, quote-level entailment) and must not be “fixed” by tightening id matching, which would give a false sense of correctness.

Also residual and deliberately unchanged:
- The whole-document `final_receipt` remains optional for non-provisional drafts (pre-existing); per-item receipts still gate every item.
- Re-editing text back to its original wording still requires re-attestation (conservative by design).
- The library export API trusts its `evidence_support` argument; callers must supply it from the validated profile, not from the draft. Documented in the docstring.

## 10. Final decision

**READY_TO_MERGE** — for the evidence-authority and export-bypass scope only.

The three in-scope gaps are closed and covered by adversarial tests; the full suite, lint, release evaluation, safety scan and both renderers pass; no HTTP fabrication path was ever demonstrated, and none is introduced. Semantic entailment remains a separate, explicitly documented research track and is not a merge blocker for this cycle.
