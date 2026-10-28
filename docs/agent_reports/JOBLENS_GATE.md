# JobLens Pre-Merge Gate Review — `research/evidence-quality-2026`

Date: 2026-10-28. Reviewer: independent (Lead-style) pre-merge review. Read-only; no merge, push, tag or publish was performed. No implementation was changed.

## 1. Verified Git state

- Repository: `~/Desktop/JobLens`
- Branch: `research/evidence-quality-2026`
- HEAD: `b48c690b48adf3fe69337bcba59203b448f3d9f2`
- Expected base `main`: `d8ff1b8863ff69515a48ace12d9a93acd77724c8` — matches (3 commits ahead).
- Working tree: one untracked file, `evaluation/results.json` (generated release-evaluation artifact, not part of the diff). No other local changes. No worktrees created.
- Commits under review:
  1. `42ff5e2` — `fix(experience): preserve every source-stated achievement in an entry`
  2. `81f4aec` — `fix(requirements): typed alias-aware requirement assessment`
  3. `b48c690` — `docs(report): complete JobLens evidence-quality research report`
- Diff vs base: 26 files changed, +6,643 / −237. No secrets, private archives, or real CVs in the diff. `src/joblens_public/webapp.py` is untouched.

## 2. Reviewed commits and file changes

- **Commit 1** touches `cv.py`, `profile/engine.py`, `provisional.py`, plus new tests and the research harness. Core change: replace the verb-whitelist contribution extraction with structural `contribution_lines()` that reads until a section heading, a new entry header, or a 12-line cap; provisional facts are grouped by entry header instead of a verb regex.
- **Commit 2** adds `requirements.py` (670 lines) with typed, alias-aware, element-wise assessment; rewrites `cv.py` gap reporting to use it; adds `supports`/`supports_partially` to `decisions.py`; extends `CvDraft` with `requirement_coverage` (serialized in `as_dict`/`from_dict`, preserved through edit/approve/contact edits); updates `jobs.py` importance parsing and `ui/simple-http.mjs`.
- **Commit 3** is documentation only (`docs/agent_reports/JOBLENS.md`).

## 3. Independent findings

### 3.1 Achievement preservation — verified

Synthetic entry with a non-whitelisted first contribution ("Increased checkout conversion by 18%") followed by whitelisted and non-standard lines: the real profile engine retains all four source lines as exact evidence slices; the real draft generator emits all of them. Numerical values survive extraction (PDF segment text verified) and drafting. No leakage between entries (entry stops at the next section heading or entry header; 12-line cap prevents runaway). Provisional grouping now keys on the role line, so two positions with the same generic role are not merged (the old code merged by role). **Finding: improvement is real and the old defect is fixed.**

### 3.2 Typed requirement assessment — verified with one latent defect

Strengths: alias table (Postgres/PostgreSQL, GCP/Google Cloud, Go/golang with short-token boundary protection), element decomposition (technology, tenure, qualifier, content), stemmer for irregular verbs, `partial` state, importance preserved, single assessment function shared by draft and decision report (no disagreement).

**Blocking latent defect — cross-evidence conflation of qualifiers and tenure.** `assess_requirement` pools all evidence strings and computes tenure as the global `max` and qualifiers as a global membership test. Consequently:

- "Production PostgreSQL" is reported `covered` when evidence is `["PostgreSQL in development", "Docker in production"]` (production comes from a different technology).
- "4+ years of Terraform" is reported `covered` when evidence is `["Terraform", "6 years of Python experience"]` (years come from a different technology).

Both cases were reproduced independently (§4). This directly violates the gate's criterion that no requirement be declared fully covered without sufficient approved evidence. The frozen holdout did not exercise this because its cases were authored with per-requirement evidence isolation, so the holdout gate (unsafe_cover == 0) did not catch it.

### 3.3 Parsing noise (non-blocking)

- A line "Technologies:" appearing inside a Responsibilities block is captured as a responsibility requirement. Minor noise; reported as `uncovered`.
- Negated requirements ("not required to have Kubernetes") are handled only lexically: "not" becomes a content element that is missing, so the state is `partial` rather than `uncovered`. Safe (not falsely covered) but semantically weak.
- Certification level is not distinguished ("AWS Certified Solutions Architect" covered by "Certified Solutions Architect - Associate"). Cosmetic.

### 3.4 Compatibility — verified

`CvDraft` gains `requirement_coverage` with a default empty tuple; `as_dict`/`from_dict` round-trip verified; field preserved through `edit_cv_item`, `approve_cv_item`, `update_candidate_contact`. Decision report adds additive `supports_partially` (backward-compatible). `DECISION_REPORT_VERSION` and `CV_DRAFT_VERSION` unchanged. Older clients can ignore the new fields. No API breakage observed.

### 3.5 Research reproducibility — mostly verified, one artifact staleness issue

- Independent re-runs of development and holdout reproduce the aggregate metrics exactly (unsafe_cover 0, 16/16 and 12/12 three-class, all recall gates met).
- However, the committed result JSONs (`exp2-dev.json`, `exp2-holdout.json`) contain detail strings that differ from a fresh run (e.g. skill ordering "docker and python" vs "python and docker"). The metrics are identical; the detail strings are stale relative to the final code. The committed artifacts should be regenerated before merge so the repository is self-consistent.
- Preregistration and addendum are present and internally consistent; the addendum correctly identifies the original support-metric contradiction and redefines it. The addendum was written before the holdout run per its own statement; I cannot independently verify the exact ordering of the holdout run vs the addendum from repository metadata alone, but the timestamps are consistent with the claim.

## 4. New adversarial cases and results

| Case | Expected | Actual | Verdict |
| --- | --- | --- | --- |
| "Production PostgreSQL" with evidence `["PostgreSQL in development", "Docker in production"]` | partial/uncovered | **covered** | **FAIL — false cover** |
| "4+ years of Terraform" with evidence `["Terraform", "6 years of Python experience"]` | partial | **covered** | **FAIL — false cover** |
| "PhD in Computer Science" with evidence `["BSc in Computer Science"]` | uncovered/partial | partial (missing 'phd') | OK (not covered) |
| "MySQL" vs requirement "PostgreSQL" | uncovered | uncovered | OK |
| "Python and AWS" with evidence `["Python", "Docker"]` | partial | partial (missing AWS) | OK |
| "Go" with evidence `["go-to-market planning"]` | uncovered | uncovered | OK |
| "Go" with evidence `["Built Go services"]` | covered | covered | OK |
| "Production experience with Postgres" (existing test) | partial | partial | OK |
| Negated requirement "not required to have Kubernetes" | uncovered | partial | weak (safe) |
| Cross-document compound requirement | covered | covered | OK |

## 5. Benchmark reproducibility

- Commands run: `python -m evaluation.research.run_research --split development --label repro-dev` and `--split holdout --label repro-holdout`. Both exited 0.
- Development: 10/10 achievement cases, 62/62 checks, 16/16 requirements, 0 unsafe cover, 9/9 + 3/3 + 4/4 recall, 0 false claims, 0 inconsistent, 0 duplicate gaps.
- Holdout: 6/6 achievement cases, 38/38 checks, 12/12 requirements, 0 unsafe cover, 6/6 + 2/2 + 4/4 recall, 0 false claims, 0 inconsistent, 0 duplicate gaps.
- All preregistered gates met on both splits. Metrics reproduce exactly. Achievement detail strings are stale (§3.5).

## 6. Full test results

- `python -m pytest -q` (`.venv`): **585 passed**, 0 failed, 40.88 s.
- `ruff check src tests`: all checks passed.
- Subsets re-run: `test_fact_preservation`, `test_cv_http_e2e`, `test_experience_preservation`, `test_requirement_assessment`, `test_gap_reporting_regression` — 49 passed.
- `pip-audit` on project dependencies (pypdf, reportlab, python-docx): no known vulnerabilities. (pip itself has advisories unrelated to the project.)
- End-to-end extraction verified on a synthetic multi-achievement CV: all source lines and numbers survive PDF extraction and profile proposal generation.
- PDF/DOCX export parity: covered by existing fact-preservation tests (passed).

## 7. Security and privacy findings

- No real CVs, private archives, or personal data in the diff. All fixtures are fictional.
- Hostile-instruction job posting test passes: posting words appear only in the coverage report, never in factual items or decision labels.
- No network access added; loopback-only transport unchanged; `Cache-Control: no-store`, no CORS origin, no Python version in Server header (verified by e2e tests).
- No secrets or credentials in the diff.

## 8. Regression risks

- The cross-evidence conflation (§3.2) is the primary regression risk: it can turn a partial requirement into `covered` whenever evidence for another technology mentions the qualifier or tenure.
- Skill ordering in the generated summary is non-deterministic across... actually it is deterministic within a process but depends on fact insertion order; the committed result JSONs are stale. Low impact (cosmetic) but should be regenerated.
- The 12-line contribution cap could truncate a very long entry; this is a documented safety bound, not a defect.
- Stale committed result JSONs reduce the credibility of the reproducibility claim.

## 9. Compatibility assessment

- Backward compatible: `CvDraft.requirement_coverage` defaults to `()`, `Decision.supports_partially` defaults to `()`. `from_dict` tolerates missing keys. Contract versions unchanged.
- Serialization round-trip verified.
- `edit_cv_item`, `approve_cv_item`, `update_candidate_contact` preserve the new field.
- No breaking change to `JobPosting`, `DecisionReport`, or the HTTP transport.

## 10. Final recommendation

**CHANGES_REQUESTED**

Blocking findings:
1. Cross-evidence conflation of qualifiers and tenure in `assess_requirement` (`src/joblens_public/requirements.py`): qualifiers (e.g. "production") and tenure must be evaluated against evidence for the *same* technology (or the specific element), not pooled across all evidence strings. As written, "Production PostgreSQL" can be reported `covered` from evidence that only mentions PostgreSQL in development and production elsewhere. This must be fixed and covered by a regression test before merge.
2. Regenerate the committed research result JSONs so they match the final code (detail strings currently stale).

Non-blocking improvements:
3. Tighten "Technologies:" parsing so a heading line is not captured as a responsibility.
4. Distinguish certification level in exact-name matching (optional).
5. Consider semantic negation handling for negated requirements (currently lexical; safe but weak).
6. Add a regression test for the cross-evidence conflation case.

If the blocking finding is fixed and the result JSONs regenerated, the change set is otherwise well-tested, reproducible on metrics, backward-compatible, and safe to merge. Proposed merge procedure (do not execute now): review the fix commit, re-run `pytest`, `ruff`, the research harness on both splits, and the release evaluation; then fast-forward `main` to the reviewed tip. No push or tag.
