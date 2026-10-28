# JobLens Pre-Merge Gate Review — `research/evidence-quality-2026`

Date: 2026-10-28. Reviewer: independent (Lead-style) pre-merge review. Read-only; no merge, push, tag or publish was performed. No implementation was changed during the review itself.

## 1. Verified Git state (final)

- Repository: `~/Desktop/JobLens`
- Branch: `research/evidence-quality-2026`
- HEAD: `77a421b` (5 commits ahead of `main` at `d8ff1b8`)
- Working tree: one untracked file, `evaluation/results.json` (generated release-evaluation artifact, not part of the diff). No other local changes. No worktrees created.
- Commits under review:
  1. `42ff5e2` — `fix(experience): preserve every source-stated achievement in an entry`
  2. `81f4aec` — `fix(requirements): typed alias-aware requirement assessment`
  3. `b48c690` — `docs(report): complete JobLens evidence-quality research report`
  4. `77a421b` — `fix(requirements): require qualifier/tenure to co-occur with substantive evidence`
- Diff vs base: 27 files changed, +6,800 / −237. No secrets, private archives, or real CVs in the diff. `src/joblens_public/webapp.py` is untouched.
- `evaluation/results.json` is explicitly excluded from the source distribution by `MANIFEST.in` and is not committed.

## 2. Reviewed commits and file changes

- **Commit 1** touches `cv.py`, `profile/engine.py`, `provisional.py`, plus new tests and the research harness. Core change: replace the verb-whitelist contribution extraction with structural `contribution_lines()` that reads until a section heading, a new entry header, or a 12-line cap; provisional facts are grouped by entry header instead of a verb regex.
- **Commit 2** adds `requirements.py` (702 lines) with typed, alias-aware, element-wise assessment; rewrites `cv.py` gap reporting to use it; adds `supports`/`supports_partially` to `decisions.py`; extends `CvDraft` with `requirement_coverage` (serialized in `as_dict`/`from_dict`, preserved through edit/approve/contact edits); updates `jobs.py` importance parsing and `ui/simple-http.mjs`.
- **Commit 3** is documentation only (`docs/agent_reports/JOBLENS.md`).
- **Commit 4** fixes the gate-review blocking defect: qualifiers and tenure must co-occur with a substantive element of the same requirement; regenerates the committed result JSONs; adds 5 regression tests.

## 3. Independent findings

### 3.1 Achievement preservation — verified

Synthetic entry with a non-whitelisted first contribution ("Increased checkout conversion by 18%") followed by whitelisted and non-standard lines: the real profile engine retains all four source lines as exact evidence slices; the real draft generator emits all of them. Numerical values survive extraction (PDF segment text verified) and drafting. No leakage between entries (entry stops at the next section heading or entry header; 12-line cap prevents runaway). Provisional grouping now keys on the role line, so two positions with the same generic role are not merged (the old code merged by role). **Finding: improvement is real and the old defect is fixed.**

### 3.2 Typed requirement assessment — verified; blocking defect found and fixed

Strengths: alias table (Postgres/PostgreSQL, GCP/Google Cloud, Go/golang with short-token boundary protection), element decomposition (technology, tenure, qualifier, content), stemmer for irregular verbs, `partial` state, importance preserved, single assessment function shared by draft and decision report (no disagreement).

**Blocking latent defect found during review — cross-evidence conflation of qualifiers and tenure.** `assess_requirement` pooled all evidence strings and computed tenure as the global `max` and qualifiers as a global membership test. Consequently "Production PostgreSQL" was reported `covered` when evidence was `["PostgreSQL in development", "Docker in production"]`, and "4+ years of Terraform" was reported `covered` when evidence was `["Terraform", "6 years of Python experience"]`. The frozen holdout did not exercise this because its cases were authored with per-requirement evidence isolation.

**Fixed in commit `77a421b`.** Qualifiers and tenure are now evidenced only when stated in the same evidence string as a substantive element (technology or content term) of the same requirement. Technologies and content terms remain assessed as a union across evidence, so genuine multi-document support (e.g. "PostgreSQL and Airflow" across two documents) is unaffected. Five permanent regression tests cover the original false positive, the corrected partial behavior, the genuine co-occurrence case, the tenure case, and legitimate multi-document support.

### 3.3 Parsing noise (non-blocking)

- A line "Technologies:" appearing inside a Responsibilities block is captured as a responsibility requirement. Minor noise; reported as `uncovered`.
- Negated requirements ("not required to have Kubernetes") are handled only lexically: "not" becomes a content element that is missing, so the state is `partial` rather than `uncovered`. Safe (not falsely covered) but semantically weak.
- Certification level is not distinguished ("AWS Certified Solutions Architect" covered by "Certified Solutions Architect - Associate"). Cosmetic.

### 3.4 Compatibility — verified

`CvDraft` gains `requirement_coverage` with a default empty tuple; `as_dict`/`from_dict` round-trip verified; field preserved through `edit_cv_item`, `approve_cv_item`, `update_candidate_contact`. Decision report adds additive `supports_partially` (backward-compatible). `DECISION_REPORT_VERSION` and `CV_DRAFT_VERSION` unchanged. Older clients can ignore the new fields. No API breakage observed.

### 3.5 Research reproducibility — verified after regeneration

- Independent re-runs of development and holdout reproduce the aggregate metrics exactly (unsafe_cover 0, 16/16 and 12/12 three-class, all recall gates met).
- The committed result JSONs were regenerated in commit `77a421b` and now match the final code (detail strings consistent).
- Preregistration and addendum are present and internally consistent; the addendum correctly identifies the original support-metric contradiction and redefines it. The addendum was written before the holdout run per its own statement; I cannot independently verify the exact ordering of the holdout run vs the addendum from repository metadata alone, but the timestamps are consistent with the claim.

## 4. New adversarial cases and results

| Case | Expected | Actual (post-fix) | Verdict |
| --- | --- | --- | --- |
| "Production PostgreSQL" with evidence `["PostgreSQL in development", "Docker in production"]` | partial | partial | PASS (regression test) |
| "4+ years of Terraform" with evidence `["Terraform", "6 years of Python experience"]` | partial | partial | PASS (regression test) |
| "Production experience with Postgres" with co-occurring evidence `["PostgreSQL in production"]` | covered | covered | PASS |
| "4+ years of Terraform" with co-occurring evidence `["6 years of Terraform experience"]` | covered | covered | PASS |
| "PhD in Computer Science" with evidence `["BSc in Computer Science"]` | uncovered/partial | partial (missing 'phd') | OK (not covered) |
| "MySQL" vs requirement "PostgreSQL" | uncovered | uncovered | OK |
| "Python and AWS" with evidence `["Python", "Docker"]` | partial | partial (missing AWS) | OK |
| "Go" with evidence `["go-to-market planning"]` | uncovered | uncovered | OK |
| "Go" with evidence `["Built Go services"]` | covered | covered | OK |
| Negated requirement "not required to have Kubernetes" | uncovered | partial | weak (safe) |
| Cross-document compound requirement | covered | covered | PASS (regression test) |

## 5. Benchmark reproducibility

- Commands run: `python -m evaluation.research.run_research --split development --label repro-dev` and `--split holdout --label repro-holdout`. Both exited 0.
- Development: 10/10 achievement cases, 62/62 checks, 16/16 requirements, 0 unsafe cover, 9/9 + 3/3 + 4/4 recall, 0 false claims, 0 inconsistent, 0 duplicate gaps.
- Holdout: 6/6 achievement cases, 38/38 checks, 12/12 requirements, 0 unsafe cover, 6/6 + 2/2 + 4/4 recall, 0 false claims, 0 inconsistent, 0 duplicate gaps.
- All preregistered gates met on both splits. Metrics and detail strings reproduce exactly after the regeneration.

## 6. Full test results

- `python -m pytest -q` (`.venv`): **590 passed**, 0 failed, 40.10 s.
- `ruff check src tests evaluation`: all checks passed.
- Subsets re-run: `test_fact_preservation`, `test_cv_http_e2e`, `test_experience_preservation`, `test_requirement_assessment`, `test_gap_reporting_regression` — 49 passed (plus 5 new regression tests).
- `pip-audit` on project dependencies (pypdf, reportlab, python-docx): no known vulnerabilities. (pip itself has advisories unrelated to the project.)
- End-to-end extraction verified on a synthetic multi-achievement CV: all source lines and numbers survive PDF extraction and profile proposal generation.
- PDF/DOCX export parity: covered by existing fact-preservation tests (passed).

## 7. Security and privacy findings

- No real CVs, private archives, or personal data in the diff. All fixtures are fictional.
- Hostile-instruction job posting test passes: posting words appear only in the coverage report, never in factual items or decision labels.
- No network access added; loopback-only transport unchanged; `Cache-Control: no-store`, no CORS origin, no Python version in Server header (verified by e2e tests).
- No secrets or credentials in the diff.

## 8. Regression risks

- The cross-evidence conflation is now fixed and covered by 5 permanent regression tests; residual risk is limited to qualifier/tenure co-occurrence logic in future edits.
- Skill ordering in the generated summary is deterministic within a process and depends on fact insertion order; result JSONs are now consistent.
- The 12-line contribution cap could truncate a very long entry; this is a documented safety bound, not a defect.
- Stale committed result JSONs are resolved.

## 9. Compatibility assessment

- Backward compatible: `CvDraft.requirement_coverage` defaults to `()`, `Decision.supports_partially` defaults to `()`. `from_dict` tolerates missing keys. Contract versions unchanged.
- Serialization round-trip verified.
- `edit_cv_item`, `approve_cv_item`, `update_candidate_contact` preserve the new field.
- No breaking change to `JobPosting`, `DecisionReport`, or the HTTP transport.

## 10. Final recommendation

**READY_TO_MERGE**

All blocking findings are resolved:
1. Cross-evidence conflation of qualifiers and tenure — fixed in commit `77a421b`, covered by 5 permanent regression tests.
2. Regeneration of committed research result JSONs — completed in commit `77a421b`.

Non-blocking improvements (not required for merge):
3. Tighten "Technologies:" parsing so a heading line is not captured as a responsibility.
4. Distinguish certification level in exact-name matching (optional).
5. Consider semantic negation handling for negated requirements (currently lexical; safe but weak).

The change set is well-tested (590 passed), reproducible on metrics, backward-compatible, and safe to merge. Proposed merge procedure (do not execute now): review the fix commit, re-run `pytest`, `ruff`, the research harness on both splits, and the release evaluation; then fast-forward `main` to the reviewed tip. No push or tag. No merge performed by this review.