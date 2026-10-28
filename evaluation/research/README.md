# Evidence-quality research harness

This directory contains the frozen synthetic cases and the measurement harness
used by the JobLens evidence-quality programme. Every person, employer, school
and posting is fictional. No real CV, private archive or personal data is used.

## What it measures

Two independent product properties:

1. **Achievement retention.** For each synthetic experience entry, every
   labelled contribution must appear in the draft and in both exported files,
   numbers must be exact, and content must not leak between entries or
   sections. This measures source-to-export coverage, not fluency.
2. **Requirement assessment.** For each labelled job requirement the expected
   state is `covered` (approved evidence states every distinctive element),
   `partial` (some elements are evidenced, others are not), or `uncovered`.
   The harness also checks the importance of each requirement
   (`required`/`preferred`) and whether the decision report agrees with the
   draft's own gap list.

The harness runs the real local HTTP server and the real PDF/DOCX renderers.
It never calls a model.

## Run it

```bash
python -m evaluation.research.run_research --split development --label exp1-dev
python -m evaluation.research.run_research --split holdout --label exp1-holdout
```

Results are written to `evaluation/research/results/<label>.json`. The JSON
contains aggregate metrics, per-case checks and per-requirement predictions.

## Development and holdout

`DEVELOPMENT` cases may be used to diagnose and fix defects. `HOLDOUT` cases
are frozen and are evaluated once per candidate implementation; they are not
used to choose a threshold or a rule. Both sets are in `cases.py` so the split
is auditable. A result obtained on development cases is never reported as a
holdout result.

## Reading the metrics

- `unsafe_cover` is the primary safety metric: a requirement the evidence does
  not fully establish was reported as fully covered. Lower is better; the
  acceptance gate is zero on the holdout.
- `covered_recalled` / `partial_recalled` / `uncovered_recalled` are
  per-class recall with explicit denominators.
- `report_support_false_claims` counts a decision-report statement that claims
  support for a requirement the evidence does not establish.
- `coverage_report_inconsistent` counts disagreement between the draft's gap
  list and the decision report.
- Achievement metrics are check counts, not percentages of a validated
  population; they are regression evidence for these fixtures only.

These numbers are not a general hallucination rate, not an ATS score and not a
benchmark against other tools.
