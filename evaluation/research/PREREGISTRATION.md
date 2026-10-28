# Preregistration — Experiment 2: typed requirement assessment

**Written before implementation.** Baseline measured on `42ff5e2` (Experiment 1
applied; the requirement matcher is unchanged from `d8ff1b8`).

## Problem

The draft reports a requirement as a gap only when an arbitrary token set
intersection is empty. Two failure directions follow:

- a generic word (`experience`, `with`, `communication`) makes an unrelated
  requirement look covered;
- a canonical alias (`PostgreSQL` vs `Postgres`) or a shared technology across
  two documents is not recognised;
- the decision report and the draft use *different* matchers, so they can
  disagree about whether a fact supports a requirement;
- technology mentions are not typed, so a technology that appears only under
  "Nice to have" is treated as essential by the decision report.

The product consequence is a false sense of fit: the CV is presented as
covering a requirement that the evidence does not establish.

## Hypothesis

Replacing token intersection with a typed, alias-aware, element-wise
assessment will reduce false coverage claims without reducing genuine coverage.
A requirement is decomposed into distinctive elements (technologies,
qualifiers such as "production", stated tenure, and remaining content terms).
Each element must be stated by approved evidence; tenure is never derived from
dates. The state is `covered` when every element is evidenced, `partial` when
some are, and `uncovered` when none are. The same assessment function is used
by the draft and the decision report, so they cannot disagree.

## Predefined metrics and gates (holdout)

Primary safety gate:

- `unsafe_cover == 0`: no requirement whose gold state is `partial` or
  `uncovered` is reported as `covered`.

Primary utility gates:

- `covered_recalled == covered_requirements` (no loss of genuine coverage;
  baseline 6/6).
- `partial_recalled > 0` (baseline 0/2; partial was not representable).
- `uncovered_recalled >= 3/4` (baseline 3/4).

Consistency gates:

- `report_support_false_claims == 0` (baseline 0).
- `coverage_report_inconsistent == 0` (baseline 4).
- `duplicate_gap_entries == 0` (baseline 0).

Non-regression gates:

- Experiment 1 achievement checks remain 38/38 on holdout and 62/62 on
  development.
- Full Python test suite passes; the release evaluation passes with zero
  failed scenarios and no increase in unsupported insertions.
- PDF/DOCX parity does not decrease.

## Falsification

The hypothesis is rejected if the primary safety gate is not met, if genuine
coverage falls, or if the implementation requires case-specific hacks that do
not generalise. In that case the change is reverted and the failure is
documented.

## Known risks

- A stricter matcher may create false gaps for wording it does not recognise
  (for example a genuine skill described only in prose). This is treated as a
  coverage limitation, not a safety failure, and is reported.
- "Partial" may be overused. It is still safer than "covered", but the report
  must show the exact unverified element rather than a vague warning.
- Holdout cases could be inadvertently tuned. The candidate implementation is
  frozen before the first holdout run; any later fixture change is recorded.
