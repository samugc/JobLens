# Core reliability contract (P0)

This document records the additive contracts added for the JobLens 1.0
reliability pass. Nothing in this pass changes an existing field, removes a
route or relaxes a receipt check.

## 1. Contact suggestions

Version: `contact_suggestions_version: "0.1"`.

Source: `joblens_public.profile.contact.extract_contact_suggestions(response)`.
Placement: `CvDraft.contact_suggestions` and therefore every draft response.

Fields: `full_name`, `email`, `phone`, `location`, `github`, `linkedin`,
`website`.

```json
{
  "contact_suggestions_version": "0.1",
  "suggestions": [
    {
      "field": "email",
      "status": "supported",
      "selected": "alex@example.com",
      "values": [
        {
          "value": "alex@example.com",
          "normalized": "alex@example.com",
          "evidence": [
            {
              "document_id": "doc_0",
              "segment_index": 0,
              "locator": { "kind": "paragraph", "paragraph": 1 },
              "quote": "alex@example.com",
              "start": 0,
              "end": 16,
              "support": "explicit_claim"
            }
          ]
        }
      ]
    }
  ]
}
```

Rules:

| Situation | Result |
| --- | --- |
| Same value in several documents | One `ContactValue`; every evidence reference is kept |
| Different values for `full_name`, `email`, `phone` or `location` | `status: "conflict"`, `selected: null`, all values listed |
| Several GitHub/LinkedIn/website links | `status: "supported"`, all links listed, `selected` only when exactly one |
| No source text for a field | `status: "missing"`, `selected: null`, no values |
| Source text has a date range | Never treated as a phone number |

The suggestion object is advisory. It is never copied into `candidate` and
never approves a fact. `update_candidate_contact(draft, contact)` is the
explicit reducer for a candidate correction.

## 2. Decision report

Version: `decision_report_version: "0.1"`.

Placement: `draft.decision_report` on the HTTP draft responses. It is derived
from the actual generation trace by
`joblens_public.decisions.build_decision_report`. No model is called.

```json
{
  "decision_report_version": "0.1",
  "counts": { "included": 13, "omitted": 7, "insufficient": 1 },
  "decisions": [
    {
      "decision_id": "decision_0002",
      "outcome": "included",
      "reason": "selected_essential",
      "scope": "cv",
      "category": "skill",
      "label": "Python",
      "explanation": "Python was included because it supports the essential job requirement “python”.",
      "supports": ["python"],
      "alternatives": [],
      "documents": ["synthetic-0.pdf"]
    },
    {
      "decision_id": "decision_0021",
      "outcome": "insufficient",
      "reason": "excluded_conflict",
      "scope": "cv",
      "category": "language",
      "label": "Language",
      "explanation": "The documents state English at C1 and B2. No value was selected automatically; confirm the correct value if it matters.",
      "supports": [],
      "alternatives": ["English (C1)", "English (B2)"],
      "documents": ["synthetic-0.pdf", "synthetic-1.pdf"]
    }
  ],
  "unmet_requirements": [
    {
      "requirement": "kubernetes",
      "explanation": "No approved fact supports this job requirement; it was not added to the CV."
    }
  ],
  "warnings": []
}
```

Reason vocabulary:

- `selected_essential` — included and matches `technologies` or `required`.
- `selected_relevant` — included and matches `preferred`/`responsibilities`,
  or included as approved professional content with no specific match.
- `excluded_conflict` — omitted because the sources disagree, or
  `insufficient` for a conflict that still needs a candidate decision.
- `excluded_unsupported` — omitted because there is no explicit claim or the
  candidate did not approve it.
- `excluded_redundant` — duplicate wording; all evidence merged into the
  included entry.
- `excluded_lower_priority` — a summary candidate that ranked below the facts
  actually used in the summary; it remains in its full section.

The report intentionally contains no `prop_`/`fact_` identifiers, offsets,
segment indexes or internal paths. `documents` contains filenames only.
`counts` counts decisions, not unique facts: a fact used in both the CV and the
professional summary yields two `included` decisions with different `scope`.

The report is additive and advisory:

- `CvDraft.from_dict` ignores it.
- Export eligibility and receipts do not depend on it.
- A client may discard it without changing any review or export behaviour.

## 3. Review and export invariants

- An item approval signs the exact item content, the baseline receipt, the
  approval mode **and the exact contact object**.
- A final confirmation signs the whole normalized draft, including
  `candidate` and `contact_suggestions`.
- `ReviewGuard.export` verifies the final receipt whenever one is present, and
  always requires `contact == draft.candidate.as_dict()`.
- Therefore changing `full_name`, `email`, `phone`, `location` or `links`
  after confirmation invalidates the final receipt; changing the contact
  after item approvals invalidates every item receipt. The user must confirm
  again.
- Forged approval tokens, stale baselines and edited wording continue to be
  rejected exactly as before.

## 4. Before/after synthetic fact trace

Fixture: `tests/fact_preservation_fixtures.py` (`SMALL_A`, `SMALL_B`, `JOB`).
Two synthetic documents, one job posting. All values below come from the real
engine.

### Before (release candidate)

- The draft contained the selected facts but no contact suggestions and no
  explanation of why anything was included, omitted or unresolved.
- The job parser treated the shorthand `ts` as a substring of `tests` and
  reported a TypeScript requirement that neither CV contained.
- The gap list reported `rest api` as unmet even though the selected
  experience entry contained “REST APIs”.

### After

Job technologies: `python`, `sql`, `docker`, `kubernetes`, `git`,
`rest api` (no `typescript`).

Unmet requirements: `kubernetes` only.

Contact suggestions: `full_name = "Alex Rivera"` (evidence from both
documents would be merged when both state the name).

Selected sections:

| Section | Items |
| --- | --- |
| summary | `Software Engineer using Python and SQL. Built a local Python service with REST APIs and automated tests.` |
| experience | `Software Engineer; Built a local Python service with REST APIs and automated tests.` and `Software Engineer; Documented backend APIs and tested ingestion workflows.` |
| projects | `Prototyped document retrieval and evaluation.` |
| education | `BSc in Computer Science.` |
| skills | `Python`, `SQL`, `Git`, `Docker`, `JavaScript` |
| languages | `Spanish (Native)` |
| certifications | `AWS Certified Cloud Practitioner.` |

Decision counts: `included: 13`, `omitted: 7`, `insufficient: 1`.

Omitted/insufficient decisions:

| Scope | Outcome | Reason | Label | Alternatives |
| --- | --- | --- | --- | --- |
| summary | omitted | `excluded_lower_priority` | `Git` | – |
| summary | omitted | `excluded_lower_priority` | `Docker` | – |
| summary | omitted | `excluded_lower_priority` | `JavaScript` | – |
| cv | omitted | `excluded_conflict` | `English (C1)` | – |
| cv | omitted | `excluded_conflict` | `English (B2)` | – |
| cv | omitted | `excluded_conflict` | `Project Atlas` | – |
| cv | omitted | `excluded_unsupported` | `AWS` | – |
| cv | insufficient | `excluded_conflict` | `Language` | `English (C1)`, `English (B2)` |

Key facts preserved:

- Python contributions, BSc, Project Boreal, Spanish (Native) and the AWS
  certification remain.
- Project Atlas is excluded only because its two descriptions contradict; the
  report explains the conflict.
- Neither C1 nor B2 is selected; both appear as alternatives.
- The AWS certification remains a certification. A keyword-only AWS skill
  proposal is explicitly reported as `excluded_unsupported`.
- Kubernetes is absent and reported as an unmet requirement, not invented.

## 5. Integration

Backend callers:

```python
from joblens_public.profile.contact import extract_contact_suggestions
from joblens_public.decisions import build_decision_report, trace_from_approved_profile
from joblens_public.cv import generate_cv_draft, update_candidate_contact
```

Provisional path (already wired in `POST /api/cv/draft`):

```python
trace, analysis = [], {}
draft, evidence, omitted = draft_from_source(source, job, trace=trace, analysis=analysis)
report = build_decision_report(
    job=job, draft=draft, trace=trace,
    conflicts=analysis["conflicts"], documents=analysis["documents"],
    redundant_fact_ids=analysis["redundant_fact_ids"],
)
payload = {"draft": guard.issue_draft(draft), "decision_report": report.as_dict()}
```

Approved-profile path (already wired in `POST /api/cv/cv-drafts`):

```python
draft = generate_cv_draft(profile, job, source_response=source)
trace = trace_from_approved_profile(profile, envelope, documents=filenames)
report = build_decision_report(job=job, draft=draft, trace=trace,
                               conflicts=conflicts, documents=filenames)
```

Frontend/editor integration (implemented in `web/simple.js`):

- `applyContactPrefill(draft)` fills only `supported` suggestions whose
  `selected` value is present and whose target field is currently empty. It
  never overwrites an existing value, never selects conflicting or missing
  fields, and never changes `draft.candidate` unless the value is supported.
- GitHub, LinkedIn and portfolio links are kept as three separate fields and
  mapped back into the existing `candidate.links` tuple. Multiple links for
  the same service leave that field empty when no unique link is selected.
- `contactSuggestionDetail(draft, field)` drives the “from your CV” tag, the
  “Your CVs show different values: …” conflict notice and the source
  quotation disclosure. Evidence quotes and document names are real backend
  data; no source offsets are required in the UI.
- `decisionReport(draft)` renders only the backend report’s counts, labels,
  explanations, requirements, alternatives and document names. No
  percentages or invented rationales are calculated in JavaScript.
- In-flight confirmation and download responses are discarded when the action
  token (`state.actionSeq`) changes or the draft reference changes. Edits,
  reordering, removal, regeneration, confirmation and **Start over** all bump
  that token.
- Send the final `draft.candidate` back unchanged on confirm/export.
- After any contact edit, call confirm again; export will reject a stale
  confirmation.

## 6. Integration handoff for shared files

These files are also being changed independently by other agents. Reconcile
the listed functions manually; do not copy whole files from this snapshot.

### `src/joblens_public/webapp.py`

- Imports `build_decision_report` and `trace_from_approved_profile` from
  `joblens_public.decisions`.
- `_simple_flow`: creates `trace`/`analysis`, passes them to
  `draft_from_source`, then adds `value["decision_report"]` after
  `review_guard.issue_draft`. It does not change the route or its request
  shape.
- `_cv_generate_draft`: falls back to `approved_profile_payload["source"]`
  when the request has no `source`; passes `source_response` to
  `generate_cv_draft`; builds a trace from the approved profile plus the
  canonical envelope; adds `decision_report` to the issued draft. It does not
  change the route or its request shape.

### `web/simple.js`

- `applyContactPrefill(draft)`: writes supported, non-conflicting, empty
  contact values into `draft.candidate`; conflict and missing fields stay
  empty.
- `renderContactAndItems()`: renders seven editable contact inputs, conflict
  notices, “from your CV” tags and source wording disclosures.
- `renderNotes()`: renders the backend decision report without internal IDs
  or fabricated percentages.
- `invalidateConfirmation(reason)`: clears the local confirmation and bumps
  `state.actionSeq` so stale async confirm/download replies are discarded.

### `src/joblens_public/jobs.py`

- Adds `_surface_matches(surface, text)` and uses it in
  `_extract_technologies` instead of substring matching. The `JobPosting`
  schema and the canonical lowercase technology names are unchanged.

### `src/joblens_public/cv.py`

- `CvDraft`: additive `contact_suggestions` field; `as_dict` and `from_dict`
  preserve it and accept drafts that omit it.
- `generate_cv_draft(..., source_response=None)`: attaches exact contact
  suggestions and adjusts the missing-contact warnings. It never fills
  `profile.candidate`.
- `edit_cv_item` and `approve_cv_item`: preserve `contact_suggestions`.
- New `update_candidate_contact(draft, contact)`: explicit contact correction;
  receipts are invalidated by their existing content binding.
- Unmet-requirement coverage now also reads evidence quotations and normalizes
  simple plurals, so “REST APIs” in an experience entry covers “rest api”.

### Files unique to this pass

- `src/joblens_public/profile/contact.py`
- `src/joblens_public/decisions.py`
- `tests/test_core_reliability.py`
- `docs/core-reliability.md`

## 7. Focused verification

`tests/test_core_reliability.py` (19 tests) covers:

1. contact deduplication with exact offsets and merged evidence;
2. conservative name/email conflicts with no arbitrary selection;
3. missing contact values and date-vs-phone protection;
4. multi-valued links and serialization validation;
5. contact suggestions without automatic candidate filling;
6. supported facts (contributions, education, projects, skills, languages,
   certifications, dates, metrics) surviving source → draft;
7. Kubernetes remaining absent and reported as unmet;
8. C1/B2 contradiction neither included nor chosen;
9. AWS certification not becoming a skill;
10. report/draft consistency, essential-requirement classification,
    REST API coverage, determinism;
11. hostile job-posting instructions not becoming facts;
12. contact edits invalidating final and item receipts;
13. wording edits revoking approval;
14. no full source text, paths or technical identifiers in the report;
15. the real loopback HTTP route carrying suggestions and the report, and
    rejecting export after a contact edit.

The pre-existing `tests/test_fact_preservation.py` continues to exercise the
full source → real PDF export path.

## 8. Files

- `src/joblens_public/profile/contact.py` — new extraction contract.
- `src/joblens_public/decisions.py` — new decision report contract.
- `src/joblens_public/cv.py` — additive `contact_suggestions`, source-aware
  generation, contact reducer, truthful gap coverage.
- `src/joblens_public/provisional.py` — trace/analysis output, source-aware
  generation, final evidence quotes in the trace.
- `src/joblens_public/jobs.py` — token-boundary technology matching with
  optional plural.
- `src/joblens_public/release_guard.py` — contact bound into item and final
  receipts.
- `src/joblens_public/webapp.py` — additive report/suggestions in both draft
  routes.
- `tests/test_core_reliability.py` — 19 focused tests.
- `docs/cv-generation.md`, `docs/core-reliability.md` — contracts and
  integration notes.
