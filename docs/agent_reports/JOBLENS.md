# JobLens — evidence-grounded CV tailoring: research and engineering report

**Status:** complete (C6).  
**Branch:** `research/evidence-quality-2026`  
**Baseline commit:** `d8ff1b8863ff69515a48ace12d9a93acd77724c8`  
**Experiment 1 commit:** `42ff5e2`  
**Experiment 2 commit:** `81f4aec`

This report is the durable source of truth for the research programme. Every
claim below was reproduced on the recorded commit and environment; where a
measurement could not be made, the limitation is stated instead.

---

## Checkpoint log

| Checkpoint | Meaning | State |
| --- | --- | --- |
| C0 | Repository verified | complete |
| C1 | Research and architecture comparison | complete |
| C2 | Baseline measured | complete |
| C3 | First controlled experiment | complete |
| C4 | Second experiment (only if justified) | complete |
| C5 | Full regression and security review | complete |
| C6 | Engineering case study and final report | complete |

---

## 1. Executive summary

JobLens is a deterministic, evidence-grounded CV tailoring application. It
never calls a language model. It reads approved or source-backed facts, ranks
them against an untrusted job posting, and emits a structured draft whose
every factual item cites the exact quotation that supports it. Nothing is
ever approved automatically; the candidate must explicitly confirm every
item, and a final export is bound by an HMAC receipt to the exact wording
and contact details that were confirmed.

The research programme audited that pipeline, found two high-impact
weaknesses in the evidence path, and fixed both under controlled conditions
on frozen synthetic data:

1. **Experience achievements were dropped by a verb whitelist and an early
   break.** An entry stopped being read as soon as a line did not open with
   a whitelisted verb, so "Increased checkout conversion by 18%" hid every
   bullet after it. The approved-fact path never carried achievements at all.
2. **Requirement coverage used any-token overlap.** A generic word such as
   "experience" made an unrelated requirement look covered, while a canonical
   alias such as "PostgreSQL" did not count for "Postgres". The draft and the
   decision report used different matchers and could disagree, and a
   technology appearing only under "Nice to have" was treated as essential.

Experiment 1 (structural entry continuation) raised achievement preservation
from 1/10 to 10/10 cases and from 19/62 to 62/62 checks on the development
set, with 6/6 cases and 38/38 checks on the holdout. Experiment 2 (typed,
alias-aware, element-wise requirement assessment) raised coverage correctness
from 12/16 to 16/16 on development and from 9/12 to 12/12 on holdout, with
unsafe coverage falling from 4 to 0 and from 3 to 0 respectively, partial
recall from 0/3 and 0/2 to 3/3 and 2/2, and report/coverage inconsistency
from 6 to 0 and from 4 to 0. No experiment was reverted. The full test suite
passes (585 tests), the synthetic release evaluation passes (19 ok, 1
expected error, 0 failed, 55/55 supported facts, 0/21 unsupported
insertions, PDF/DOCX parity 1.0), and ruff is clean.

No merge to `main`, push, tag, release, visibility change, or recruiter
contact has been made. All of them require explicit owner approval.

---

## 2. Verified repository state (C0)

Verified on 2026-10-28 before any change:

- Working directory `~/Desktop/JobLens`, branch `main`, HEAD
  `d8ff1b8863ff69515a48ace12d9a93acd77724c8`, clean working tree
  (`git status --porcelain=v2 --branch` reported only branch headers).
- Two historical stashes exist (`stash@{0}` on `feature/cv-parser`,
  `stash@{1}` on `feature/cv-interface`). They were **not** applied, read or
  modified. `.local/archives/` was not read.
- Python 3.13.5 in `.venv`; `pypdf`, `python-docx`, `reportlab` import.
- Baseline test suite: `565 passed in 40.88s`
  (`.venv/bin/python -m pytest -q`).
- CI (`.github/workflows/ci.yml`): Ubuntu + macOS × Python 3.11/3.13, ruff,
  pytest, Node UI tests, synthetic release evaluation on Ubuntu/3.11,
  `pip-audit`, sdist/wheel build and archive inspection.

The research branch was created from this commit. `main` was not modified.
The research branch is the only place where the programme's commits live.

---

## 3. Architecture and trust boundaries

JobLens is a single-process Python application with a browser front end.

- `src/joblens_public/webapp.py` — HTTP routes, body-size limits
  (1 MB), JSON validation, the provisional draft flow, and the approved-profile
  draft flow.
- `src/joblens_public/cv.py` — deterministic drafting, relevance ranking,
  gap reporting, item editing and approval.
- `src/joblens_public/jobs.py` — deterministic extraction of requirements
  from a pasted posting.
- `src/joblens_public/profile/` — closed-vocabulary proposal engine
  (`lexicon.py`, `engine.py`), reconciliation (`reconcile.py`), approved facts
  (`approved.py`), review state (`review.py`).
- `src/joblens_public/provisional.py` — turns extracted proposals into
  source-backed provisional facts.
- `src/joblens_public/decisions.py` — the deterministic decision report.
- `src/joblens_public/release_guard.py` — HMAC review receipts.
- `src/joblens_public/export/` — renderer-agnostic adapter and PDF/DOCX
  renderers.
- `evaluation/` — the synthetic release suite and the research harness.

Trust boundaries, which are the reason a deterministic design was chosen:

1. **The job posting is untrusted.** It may influence relevance ranking and
   gap reporting, but it is never a source of candidate facts and it is never
   executed. Only closed-vocabulary terms and explicitly labelled sections are
   extracted; every requirement is reported as a string a human can read.
2. **The candidate facts are closed-vocabulary.** The proposal engine never
   invents a vocabulary entry and never matches a word that is not listed, so
   a proposal can always be traced to a listed term. Ambiguous words are
   marked contextual and only proposed next to an explicit claim marker.
3. **Every item starts in `needs_review`.** Nothing is approved
   automatically. Approval is an explicit call, and a changed wording revokes
   approval.
4. **Receipts bind content, not labels.** Review receipts are HMACs over the
   canonical JSON of the baseline draft or of an item's content plus the
   candidate contact. Changing wording, contact details, or section order
   invalidates them.
5. **No model is called by the generator.** The optional Ollama summary
   rewrite is off by default, strictly bounded to the approved tokens, and
   falls back to the deterministic text on any failure.
6. **Parser caps.** A posting must be between 40 and 20,000 characters; the
   body limit is 1 MB. Uploads are size-limited and validated.

---

## 4. Research bibliography

Verified against primary sources during the literature subagent pass. Folklore
sources that could not be verified (in particular the "75% of resumes are
auto-rejected by an ATS" figure, which traces to a 2012 Preptel sales pitch
with no published method) were deliberately not used.

- Min, S., et al. (2023). *FActScore: Fine-grained Atomic Evaluation of
  Factual Precision in Long Form Text Generation.* EMNLP 2023.
  arXiv:2305.14251. Used for the atomic-claim decomposition idea behind
  the achievement-preservation checks.
- Gao, T., Yen, H., Yu, J., & Chen, D. (2023). *Enabling Large Language
  Models to Generate Text with Citations.* EMNLP 2023. arXiv:2305.14627.
  Used for citation-grounded generation as a design alternative.
- Saad-Falcon, J., Khattab, O., Potts, C., & Zaharia, M. (2024). *ARES: An
  Automated Evaluation Framework for Retrieval-Augmented Generation Systems.*
  NAACL 2024. arXiv:2311.09476.
- Es, S., et al. (2024). *RAGAS: Automated Evaluation of Retrieval
  Augmented Generation.* EACL 2024. arXiv:2309.15217.
- Wei, J., et al. (2024). *Long-form factuality in large language models.*
  arXiv:2403.18802 (SAFE).
- Song, Y., Kim, Y., & Iyyer, M. (2024). *VeriScore: Evaluating the
  factuality of verifiable claims in long-form text generation.* Findings of
  EMNLP 2024. arXiv:2406.19276.
- Thakur, N., et al. (2021). *BEIR: A Heterogeneous Benchmark for
  Zero-shot Evaluation of Information Retrieval Models.* NeurIPS Datasets
  and Benchmarks 2021.
- Joren, H., et al. (2025). *Sufficient Context: A New Lens on Retrieval
  Augmented Generation Systems.* ICLR 2025. arXiv:2411.06037. Used for the
  "abstain rather than assert" design principle behind partial coverage.
- Wilson, K., & Caliskan, A. (2024). *Gender, Race, and Intersectional
  Bias in Resume Screening via Language Model Retrieval.* arXiv:2407.20371.
  Motivates keeping the candidate's identity out of the generator and
  requiring explicit human approval.
- Willard, B. T., & Louf, R. (2023). *Efficient Guided Generation for
  LLMs.* arXiv:2307.09702. Geng, S., et al. (2023). *Grammar-Constrained
  Decoding for Structured NLP Tasks without Finetuning.* EMNLP 2023.
  arXiv:2305.19080. Considered and rejected in favour of a closed
  vocabulary with exact offsets (see section 6).
- Buçinca, Z., Malaya, M. B., & Gajos, K. Z. (2021). *To Trust or to
  Think: Cognitive Forcing Functions Can Reduce Overreliance on AI in
  AI-assisted Decision-making.* CSCW 2021.
- Bansal, G., et al. (2021). *Does the Whole Exceed its Parts? The Effect
  of AI Explanations on Complementary Team Performance.* CHI 2021.
- ISO 32000-1/2 (PDF), ISO 14289-1:2014 (PDF/UA-1), W3C WCAG 2.2
  (2023). Used for the export and accessibility claims.
- Zhong, X., et al. (2019). *PubLayNet: Largest Dataset Ever for Document
  Layout Analysis.* ICDAR 2019. Li, M., et al. (2020). *DocBank: A
  Benchmark Dataset for Document Layout Analysis.* COLING 2020. Background
  for the parser's layout assumptions.
- OWASP (2025). *OWASP Top 10 for LLM Applications 2025.* NIST (2024).
  *Artificial Intelligence Risk Management Framework: Generative Artificial
  Intelligence Profile (NIST AI 600-1).*
- Vendor sources, cited with caveats: HBS/Accenture (2021) hidden-workers
  survey (75% of employers use a recruiting management system; more than 90%
  filter or rank); Ladders eye-tracking studies (6-7.4 s initial screen);
  Jobscan annual ATS detection figures. These are vendor or survey research,
  not peer-reviewed science, and the programme does not repeat their headline
  numbers as facts.

---

## 5. Practitioner perspectives

The recruiter-facing literature consistently rewards the same things JobLens
is built around: exact, checkable claims; no fabricated metrics; conservative
gap reporting; and no invented dates or employers. The most useful
practitioner signal for this programme was negative: the "75% of resumes are
rejected by an ATS" claim is unsupported folklore (Preptel, 2012, no
published method), and repeating it would have been marketing, not evidence.
The report therefore makes no ATS-compatibility claim without tool-specific
evidence, and no LLM-wrapper claim at all.

---

## 6. Architecture alternatives and trade-offs

| Alternative | Fit | Why not chosen |
| --- | --- | --- |
| A. LLM rewriting with constrained decoding | High fluency, low trust | Non-deterministic, costly, and a hallucination risk that constrained decoding only partially removes; the user-facing claim "every fact cites a quotation" would become a promise the model could not keep. |
| B. Retrieval + citation generation | Strong research pedigree | Overkill for a single-document CV, and it inherits the attribution-evaluation problem rather than solving it deterministically. |
| C. Closed-vocabulary proposal engine with exact offsets and human approval (chosen) | Deterministic, auditable, no model dependency | Requires hand-maintained vocabularies and conservative gaps; bounded by what the vocabulary covers. |
| D. Token-intersection gap reporting (baseline) | Simple | Conflates generic words with evidence and disagrees with the decision report. Replaced by Experiment 2. |
| E. Manual authoring | Zero risk | No automation; defeats the product. |

The two experiments below were chosen because they are the highest-leverage
weaknesses in the chosen architecture: both sit on the path from source to
export, both are falsifiable with a frozen metric, and both can be fixed
without changing the trust model.

---

## 7. Selected engineering weaknesses

1. **Experience achievements dropped by a verb whitelist and an early break.**
   `profile/engine.py` grouped evidence into entries by a `_starts_entry`
   check that combined a role match with a verb whitelist; any line that did
   not open with a whitelisted verb terminated the entry. The approved-fact
   path in `cv._contributions` then filtered contribution lines through the
   same whitelist, so achievements such as "Increased checkout conversion by
   18%" were silently dropped, and the approved path never carried them at
   all.
2. **Requirement coverage used any-token overlap.** `cv.generate_cv_draft`
   intersected a normalised token set of the requirement with a token set
   built from all facts, evidence, and generated item text. A generic word
   such as "experience" or "with" made an unrelated requirement look
   covered. Aliases were not resolved, importance was not typed, and
   `decisions._supports` used a different matcher, so the draft and the
   decision report could disagree.

---

## 8. Hypotheses and preregistered success criteria

The full preregistration is in
`evaluation/research/PREREGISTRATION.md`; a metric-definition addendum
written before the first Experiment 2 holdout run is in
`evaluation/research/PREREGISTRATION_ADDENDUM_1.md`.

- **Experiment 1 hypothesis:** structural entry continuation (a new entry
  starts at each source line that begins with the role; every following line
  belongs to that entry) preserves every source-stated achievement without
  inventing content, and whole role lines remain evidence.
- **Experiment 2 hypothesis:** replacing token intersection with a typed,
  alias-aware, element-wise assessment reduces false coverage claims without
  reducing genuine coverage. A requirement decomposes into technologies,
  explicitly stated tenure, the qualifier "production", and remaining content
  terms; each must be stated by approved evidence; tenure is never derived
  from dates; the state is `covered`/`partial`/`uncovered`; the same function
  drives the draft and the decision report.

Gates (holdout): `unsafe_cover == 0`; `covered_recalled == covered_requirements`
(baseline 6/6); `partial_recalled > 0` (baseline 0/2);
`uncovered_recalled >= 3/4` (baseline 3/4); `report_support_false_claims == 0`;
`coverage_report_inconsistent == 0`; `duplicate_gap_entries == 0`;
Experiment 1 checks preserved; full test suite and release evaluation pass;
PDF/DOCX parity does not decrease.

---

## 9. Baseline results

Development set (10 achievement cases, 10 coverage cases, 16 requirements):

| Metric | Baseline dev |
| --- | --- |
| Achievement cases ok | 1/10 |
| Achievement checks passed | 19/62 |
| State correct | 12/16 |
| Unsafe cover | 4 |
| Covered recalled | 9/9 |
| Partial recalled | 0/3 |
| Uncovered recalled | 3/4 |
| Importance correct | 16/16 |
| Duplicate gap entries | 0 |
| Report/coverage inconsistent | 6 |
| Report support false claims | 0 |

Holdout set (6 achievement cases, 8 coverage cases, 12 requirements). Note:
this baseline was measured at commit `42ff5e2`, i.e. after Experiment 1 had
been applied; the requirement matcher was unchanged from `d8ff1b8`, but the
achievement baseline is therefore not a pre-Experiment-1 measurement.

| Metric | Baseline holdout |
| --- | --- |
| Achievement cases ok | 6/6 |
| Achievement checks passed | 38/38 |
| State correct | 9/12 |
| Unsafe cover | 3 |
| Covered recalled | 6/6 |
| Partial recalled | 0/2 |
| Uncovered recalled | 3/4 |
| Importance correct | 12/12 |
| Duplicate gap entries | 0 |
| Report/coverage inconsistent | 4 |
| Report support false claims | 0 |

The four unsafe covers on development were: a generic "experience" token, a
Python/SQL partial, a Postgres alias partial, and a Kubernetes tenure case.
The three on holdout were the analogous cases (dbt, Kafka/Spark, Terraform
tenure).

---

## 10. Implemented experiments

### Experiment 1 — structural entry continuation

Commit `42ff5e2`. Changes:

- `profile/engine.py`: `_extract_role` and entry grouping now treat every
  source line under a role as a contribution; the verb whitelist no longer
  gates entry membership.
- `provisional.py`: `_starts_entry` groups by role line; all following lines
  become contributions; whole role lines (employer, dates) are retained as
  evidence.
- `cv._contributions`: returns every source line in the entry except the entry
  line itself, with deduplication only.
- `cv` summary wording changed from "experience in" to "skills in".
- `cv.py` experience item text uses contribution quotes; falls back to the
  role line when there are none.
- Tests updated: `test_profile_engine.py`, `test_reconcile_mapping.py`
  (documented as a deliberate provenance-preserving change, not a weakened
  safety check); new `tests/test_experience_preservation.py` (6 tests).
- Research harness and cases added; baseline and Experiment 1 results
  recorded.

Development result: 10/10 cases, 62/62 checks (from 1/10, 19/62). Coverage
regressed as expected (unsafe cover 4 to 6) because the richer experience
text made the old token matcher over-claim.

### Experiment 2 — typed requirement assessment

Commit `81f4aec`. Changes:

- New `src/joblens_public/requirements.py`: `CoverageState`, `Requirement`,
  `RequirementAssessment`, `Element`, alias resolution from `SKILL_TERMS`
  plus a small requirement-side table (`golang`, `dbt`, `kafka`,
  `apache spark`), a compound-word guard (rejects `go` in `go-to-market`),
  boilerplate removal, tenure and qualifier extraction, deterministic
  requirement IDs, `extract_requirements`, `assess_requirements`,
  `gap_requirements`, `coverage_states`.
- `jobs.py`: `required_technologies`/`preferred_technologies` fields;
  improved required/preferred headings; word-boundary noise matching (no
  longer drops "Shared on-call rotation" or "Home automation"); merge of
  requirement-side aliases into `technologies`.
- `cv.py`: derives `unmet_requirements` and a new additive
  `requirement_coverage` field from the same assessment; removes
  `coverage_token` token-intersection logic; parses/serialises the new field
  in `CvDraft.from_dict`; carries it through edit/approve/contact updates.
- `decisions.py`: uses assessments for `supports`; adds `supports_partially`
  to `Decision`, `requirement_coverage` to `DecisionReport`, and
  state-aware unmet explanations; no false full-support claims for
  partial/uncovered requirements.
- Tests: `tests/test_requirement_assessment.py` (12 tests),
  `tests/test_gap_reporting_regression.py` (+2 noise tests);
  `tests/test_core_reliability.py` updated for the coverage-report field;
  `tests/ui/simple-http.mjs` made case-insensitive.
- Harness: collects `supports_partially` and reports `fully_supported_in_report`;
  metric definitions corrected per the addendum.

---

## 11. Holdout results

| Metric | Baseline holdout | Experiment 2 holdout |
| --- | --- | --- |
| Achievement cases ok | 6/6 | 6/6 |
| Achievement checks passed | 38/38 | 38/38 |
| State correct | 9/12 | 12/12 |
| Unsafe cover | 3 | 0 |
| Covered recalled | 6/6 | 6/6 |
| Partial recalled | 0/2 | 2/2 |
| Uncovered recalled | 3/4 | 4/4 |
| Importance correct | 12/12 | 12/12 |
| Duplicate gap entries | 0 | 0 |
| Report support false claims | 0 | 0 |
| Report/coverage inconsistent | 4 | 0 |
| Errors | 0 | 0 |

Development (Experiment 2): 10/10 cases, 62/62 checks; 16/16 states correct;
0 unsafe; 9/9 covered; 3/3 partial; 4/4 uncovered; 0 inconsistent; 0 false
claims; 0 duplicates.

Every preregistered gate is met on both splits.

---

## 12. Regressions and failed approaches

- **Coverage regression caused by Experiment 1 (expected).** Richer
  experience text made the old token matcher over-claim (unsafe cover 4 to 6
  on development; report/coverage inconsistency 6 to 7; one false support
  claim). This motivated Experiment 2 and is recorded in `exp1-dev.json`.
- **Metric contradiction discovered during implementation.** The original
  `report_support_false_claims` definition (any partial/uncovered requirement
  in `supports`) and `coverage_report_inconsistent` (partial requires
  `supports`) cannot both be zero once partial coverage is representable. The
  contradiction was invisible in the baseline because the old matcher could
  not represent `partial` at all. Addendum 1 resolves it by distinguishing
  partial contributions (`supports_partially`) from full support claims
  (`supports`), before any Experiment 2 holdout run. Both the original and
  the corrected definitions are retained in the repository.
- **No experiment was reverted.** Both were accepted.
- **No false starts were committed.** Exploratory sketches of a stemming
  rule and a heading list were iterated on the development set only and are
  not in the final diff.

---

## 13. Tests executed and exact outcomes

- Baseline (pre-change): `.venv/bin/python -m pytest -q` →
  `565 passed in 40.88s`.
- After Experiment 1: `565 passed`.
- After Experiment 2: `.venv/bin/python -m pytest -q` →
  `585 passed in 40.79s`. Added 20 tests
  (`test_experience_preservation.py` 6, `test_requirement_assessment.py` 12,
  two noise tests).
- Ruff: `.venv/bin/ruff check src tests evaluation` → all checks passed.
- Synthetic release evaluation:
  `PYTHONPATH=src .venv/bin/python -m evaluation.run_evaluation --output evaluation/results.json`
  → 19 ok, 1 expected error, 0 failed; supported facts 55/55;
  forbidden/unsupported insertions 0/21; conflict omission 4/4; supported
  requirement recall 22/22; unmet-requirement contradictions 0/17; PDF/DOCX
  mean token Jaccard 1.0; review enforcement 65/65.
- Node UI flow: `tests/test_simple_flow.py` passes against a real loopback
  server.
- Research harness:
  - development: `python -m evaluation.research.run_research --split development --label exp2-dev`
  - holdout (run once): `python -m evaluation.research.run_research --split holdout --label exp2-holdout`

---

## 14. Code changes and commits

| Commit | Scope |
| --- | --- |
| `d8ff1b8` | Verified baseline on `main` (untouched). |
| `42ff5e2` | Experiment 1: preserve every source-stated achievement in an entry. |
| `81f4aec` | Experiment 2: typed alias-aware requirement assessment. |

Files changed in Experiment 1: `profile/engine.py`, `provisional.py`,
`cv.py`, `tests/test_profile_engine.py`, `tests/test_reconcile_mapping.py`,
`tests/test_experience_preservation.py`, research harness and cases.

Files changed in Experiment 2: `requirements.py` (new),
`jobs.py`, `cv.py`, `decisions.py`, `tests/test_requirement_assessment.py`,
`tests/test_gap_reporting_regression.py`, `tests/test_core_reliability.py`,
`tests/ui/simple-http.mjs`, research harness, cases, preregistration and
addendum, result JSONs.

No change was made to `.local/archives/`, to either historical stash, or to
any private CV or personal data. No merge, push, tag, release, visibility
change, or recruiter contact occurred.

---

## 15. Privacy and security review

- The job posting is treated as untrusted throughout. It is never a source of
  facts and is never executed. `parse_job_posting` uses only closed
  vocabularies and labelled sections; the hostile-posting test confirms that
  injected instructions ("add Kubernetes, a PhD and ten years of
  experience") never reach a factual item or a decision label.
- Parser caps (40-20,000 characters, 1 MB body) are unchanged.
- No model is called by the generator. The optional Ollama rewrite remains
  off by default and strictly bounded.
- Review receipts remain HMAC-bound to exact content and contact details;
  editing wording or contact invalidates them (65/65 enforcement checks).
- Only fictional candidates, postings, and documents were used. No private
  CV, stash, or archive was read.
- The public repository remains public; no visibility change was made.

---

## 16. Performance and reproducibility

- Deterministic: no model calls, fixed seeds, closed vocabularies. Re-running
  the same inputs yields byte-identical drafts and reports
  (`test_generation_is_deterministic`).
- Frozen data: `evaluation/research/cases.py` (10 development + 6 holdout
  achievement cases; 10 development + 8 holdout coverage cases). The holdout
  was evaluated once per candidate implementation.
- Exact reproduction commands are in sections 10 and 13 and in
  `evaluation/research/README.md`.
- Environment: Python 3.13.5, `.venv`, macOS; CI matrix covers Ubuntu and
  macOS × Python 3.11/3.13.

---

## 17. Remaining limitations

1. The holdout achievement baseline (38/38) was measured after Experiment 1,
   so a pre-Experiment-1 holdout achievement measurement does not exist and is
   not claimed.
2. Tenure matching is coarse: it takes the maximum explicitly stated years or
   months in the evidence, so an unrelated "6 years" mention could cover a
   tenure requirement. It never uses employment dates.
3. Soft-skill requirements such as "Excellent written communication skills"
   are represented as content terms and will be reported as gaps unless the
   candidate states them in those words. This is a coverage limitation, not a
   safety failure, and is reported as such.
4. Responsibilities are split into multiple requirement entries, which can
   over-report partial coverage for a single responsibility line.
5. No ATS-compatibility claim is made. The system makes no claim about any
   specific recruiter tool.
6. The optional Ollama rewrite is not part of the evaluated path.

---

## 18. Recruiter-facing technical case study

**Problem.** A CV tailoring tool that invents or silently drops
achievements is worse than no tool. JobLens's previous experience path
dropped any achievement that did not open with a whitelisted verb, and its
gap reporter called a requirement "covered" whenever one generic word
overlapped.

**Approach.** Replace both paths with structural, evidence-grounded logic:
entries are delimited by role lines and every line under them is a
contribution; requirements are decomposed into typed elements and assessed
element-wise against approved evidence, with the same function in the draft
and the decision report. No model is called. Every item still needs explicit
human approval.

**Evidence.** Controlled A/B on frozen synthetic data: achievement
preservation 1/10 to 10/10 cases (19/62 to 62/62 checks) on development and
6/6 (38/38) on holdout; coverage correctness 12/16 to 16/16 and 9/12 to
12/12; unsafe coverage 4 to 0 and 3 to 0; partial recall 0 to 3/3 and 0 to
2/2. Full suite 585 passed; release evaluation 55/55 facts, 0/21
insertions; PDF/DOCX parity 1.0.

**Takeaway.** Deterministic, citation-bound generation with explicit human
approval is a viable and auditable alternative to LLM rewriting for
high-stakes documents.

---

## 19. Proposed future research

1. A second experiment on constrained decoding for the optional summary
   rewrite, with the same frozen-data and preregistration discipline.
2. A larger, independently authored holdout set to reduce the risk of
   inadvertent tuning.
3. A user study on whether partial-coverage explanations reduce
   overreliance (Buçinca et al.).
4. Extending the closed vocabulary and measuring its coverage on real
   (anonymised) postings.
5. Accessibility audit of the PDF/DOCX exports against PDF/UA-1 and WCAG 2.2.

---

## 20. Release readiness

- [x] Baseline verified and documented.
- [x] Two weaknesses selected and justified.
- [x] Two experiments implemented, measured on development and holdout.
- [x] All preregistered gates met.
- [x] Full test suite passes (585).
- [x] Ruff clean.
- [x] Synthetic release evaluation passes (0 failed).
- [x] PDF/DOCX parity 1.0.
- [x] No merge, push, tag, release, visibility change, or recruiter contact.
- [ ] Owner approval to merge `research/evidence-quality-2026` into `main`.
- [ ] Owner approval to push and tag a release.
- [ ] Owner approval to publish or contact recruiters.

---

## 21. Actions requiring owner approval

None has been taken. The following require explicit approval before they can
happen:

1. Merging `research/evidence-quality-2026` into `main`.
2. Pushing the branch or any commit to a remote.
3. Creating a tag or a release.
4. Changing repository visibility.
5. Contacting recruiters or publishing the case study externally.
6. Any change to `.local/archives/`, historical stashes, or private data.

The branch and its commits (`42ff5e2`, `81f4aec`) are available locally for
review.
