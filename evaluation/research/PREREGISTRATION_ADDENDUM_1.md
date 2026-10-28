# Preregistration addendum 1 — coherent support metrics

**Date:** 2026-10-28. Written during implementation of Experiment 2 and
**before the first Experiment 2 holdout run**. No holdout result for
Experiment 2 exists at the time of writing. The candidate implementation was
not yet complete, so the addendum cannot have been informed by holdout output.

## Why an addendum is needed

The original preregistration defined two gates that are mutually exclusive as
soon as `partial` coverage is representable:

- `report_support_false_claims == 0`, where a false claim was defined as a
  decision report listing a requirement whose gold state is `partial` **or**
  `uncovered` in `supports`;
- `coverage_report_inconsistent == 0`, where a requirement predicted `partial`
  must appear in `supports`.

If any genuine partial requirement is predicted `partial` (required by
`partial_recalled > 0`), the two definitions force the same observation to be
both a false claim and a required support. The contradiction did not appear in
the baseline because the old matcher could not represent `partial` at all
(`partial_recalled` was 0/2 on the holdout).

The root cause is a conflation of two different statements:

1. "this content contributes evidence to the requirement" (element-level
   support; true for a partial requirement);
2. "the draft claims the requirement is fully satisfied" (whole-requirement
   support; must be false for a partial or uncovered requirement).

A flat `supports` list cannot express both. Experiment 2 therefore adds an
additive `supports_partially` field to each decision. `supports` keeps its
strong meaning: the requirement is fully covered by the draft's evidence as a
whole **and** the decision contributes at least one of its elements.

## Corrected metric definitions (holdout)

These replace only the support-related definitions. Every other gate in
`PREREGISTRATION.md` is unchanged.

- `supported_in_report`: the requirement text appears in a decision's
  `supports` **or** `supports_partially`.
- `fully_supported_in_report`: the requirement text appears in `supports`
  only.
- `report_support_false_claims`: gold state is `partial` or `uncovered` **and**
  `fully_supported_in_report`. A partial contribution recorded in
  `supports_partially` is not a claim of full support.
- `report_support_missing`: gold state is `covered` **and** not
  `fully_supported_in_report`.
- `coverage_report_inconsistent`: predicted `covered` without
  `fully_supported_in_report`, predicted `partial` without
  `supported_in_report`, or predicted `uncovered` with `supported_in_report`.

Unchanged gates:

- `unsafe_cover == 0`
- `covered_recalled == covered_requirements`
- `partial_recalled > 0`
- `uncovered_recalled >= 3/4`
- `report_support_false_claims == 0`
- `coverage_report_inconsistent == 0`
- `duplicate_gap_entries == 0`
- Experiment 1 achievement checks 38/38 holdout, 62/62 development
- full test suite and release evaluation pass; parity does not decrease

## Disclosure

This is a change to a preregistered measurement definition, not to the
experimental treatment. It was made after observing development results and
before any Experiment 2 holdout run. Both the original definitions and this
addendum remain in the repository; the final report will state that the
original support metric was internally inconsistent and that the corrected
definition distinguishes partial contributions from full support claims.
