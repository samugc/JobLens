# JobLens — evidence-grounded CV tailoring: research and engineering report

**Status:** in progress (checkpoint log below).
**Branch:** `research/evidence-quality-2026`
**Baseline commit:** `d8ff1b8863ff69515a48ace12d9a93acd77724c8`

This report is the durable source of truth for the research programme. It is
updated after every milestone. Nothing in this file should be read as a claim
that has not been reproduced on the recorded commit and environment.

---

## Checkpoint log

| Checkpoint | Meaning | State |
| --- | --- | --- |
| C0 | Repository verified | complete |
| C1 | Research and architecture comparison | in progress |
| C2 | Baseline measured | pending |
| C3 | First controlled experiment | pending |
| C4 | Second experiment (only if justified) | pending |
| C5 | Full regression and security review | pending |
| C6 | Engineering case study and final report | pending |

---

## 1. Executive summary

_To be completed at C6._

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

---

## 3. Architecture and trust boundaries

_To be completed at C1/C2._

---

## 4. Research bibliography

_To be completed at C1._

---

## 5. Practitioner perspectives

_To be completed at C1._

---

## 6. Architecture alternatives and trade-offs

_To be completed at C1._

---

## 7. Selected engineering weaknesses

_To be completed at C2._

---

## 8. Hypotheses and preregistered success criteria

_To be completed before each experiment is run._

---

## 9. Baseline results

_To be completed at C2._

---

## 10. Implemented experiments

_To be completed at C3/C4._

---

## 11. Holdout results

_To be completed at C4._

---

## 12. Regressions and failed approaches

_To be completed at C4/C5._

---

## 13. Tests executed and exact outcomes

_To be completed at C5._

---

## 14. Code changes and commits

_To be completed at C5._

---

## 15. Privacy and security review

_To be completed at C5._

---

## 16. Performance and reproducibility

_To be completed at C5._

---

## 17. Remaining limitations

_To be completed at C6._

---

## 18. Recruiter-facing technical case study

_To be completed at C6._

---

## 19. Proposed future research

_To be completed at C6._

---

## 20. Release readiness

_To be completed at C6._

---

## 21. Actions requiring owner approval

None yet. No merge, push, tag, release, visibility change or external contact
has been made or is proposed without explicit approval.
