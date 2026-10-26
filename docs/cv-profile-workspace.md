# Candidate profile review — profile schema 0.1 over parser schema 1.1

This document describes the **candidate profile review view** that lives next to
the CV evidence workspace, and the JSON that `web/workspace/profile-adapter.js`
expects.

The contract below is the canonical one of the profile engine
(`joblens_public.profile`, profile schema `0.1`, derived from parser schema
`1.1`). The HTTP route does not exist yet; the client is prepared for it and
the interface works against the canonical envelope today.

- Profile schema version: `0.1`
- Parser schema version: `1.1`
- Wire format: `web/workspace/profile-adapter.js`
- Review rules: `web/workspace/profile-review.js`
- Canonical sample: `web/workspace/fixtures/profile-synthetic.json`
- Its source documents: `web/workspace/fixtures/profile-preview-source.json`
- Broken examples, tests only: `web/workspace/fixtures/profile-invalid-samples.json`

## Boundaries

- The extraction workspace is unchanged. Uploading, extracting and inspecting
  parser output behave exactly as before.
- The profile view is a **second view**, not a replacement. The extraction
  report stays available and keeps its own state.
- The interface never invents a proposal. It shows what the engine returned,
  matches every quotation against the text of this session, and records human
  decisions.
- The interface does not pretend the engine is connected. The "Build profile"
  button calls the endpoint and reports the honest failure until a real engine
  answers.
- The only sample data is the clearly labelled synthetic fixture. It is not
  parser output and it is not a real candidate.

## Request

`POST {base}/profiles` (same base as the extraction route, default `/api/cv`).

- Content type: `application/json`
- Required header: `X-JobLens-Request: 1`

The endpoint accepts **exactly two top-level keys**. Any other top-level key is
refused with HTTP `400 invalid_request`, so the extraction response is
projected down to the job id and the source documents:

```json
{
  "job_id": "job_2f1c...",
  "documents": [
    {
      "document_id": "doc_9ab4...",
      "index": 0,
      "filename": "synthetic-cv.pdf",
      "status": "extracted",
      "format": "pdf",
      "segments": [{ "locator": { "kind": "page", "page": 1 }, "text": "..." }]
    }
  ]
}
```

Each document carries the identifier, position, name, status and format the
parser gave it, and its blocks in order with the locator and the exact text.
Nothing else is sent: no `transport_version`, no `schema_version`, no `batch`,
no `text`, no `warnings`, no `metadata`.

The projection is checked before the request is sent:

- a job without documents is refused (`no_source`),
- a document without the identifier the parser gave it is refused
  (`invalid_source`),
- a document whose index does not match its position in the batch is refused,
- a block without a locator or without its text is refused.

Nothing incomplete is sent to the endpoint, and the text that is sent is the
text the evidence of a proposal is checked against, so a proposal keeps its
identity and its exact source quotation.

## Envelope

```json
{
  "profile_schema_version": "0.1",
  "parser_schema_version": "1.1",
  "job_id": "job_9a8b7c6d5e4f3021",
  "documents": [
    {
      "document_id": "doc_1f2e3d4c5b6a7081",
      "index": 0,
      "filename": "synthetic-cv.pdf",
      "status": "extracted",
      "format": "pdf",
      "segment_count": 1,
      "text_length": 112
    }
  ],
  "proposals": [
    {
      "proposal_id": "prop_aad0beff2dabbfb2",
      "category": "education",
      "value": { "level": "bachelor", "field": "computer science" },
      "status": "proposed",
      "evidence": [
        {
          "document_id": "doc_1f2e3d4c5b6a7081",
          "segment_index": 0,
          "locator": { "kind": "paragraph", "paragraph": 1 },
          "quote": "BSc in Computer Science",
          "start": 38,
          "end": 61,
          "support": "explicit_claim"
        }
      ],
      "conflicts": []
    }
  ],
  "conflicts": [],
  "warnings": []
}
```

### Envelope fields

| Field | Required | Notes |
| --- | --- | --- |
| `profile_schema_version` | yes | Must be exactly `"0.1"`. |
| `parser_schema_version` | yes | Must be exactly `"1.1"`. |
| `job_id` | yes | String or `null`. |
| `documents` | optional | Provenance by reference: `document_id`, `index`, `filename`, `status`, `format`, `segment_count`, `text_length`. The document text is not copied into the envelope. |
| `proposals` | yes | The proposed facts. May be empty. |
| `conflicts` | optional | The global conflict records. May be empty. |
| `warnings` | optional | Non-fatal notes, for example a skipped document. |

### Proposal fields

| Field | Required | Notes |
| --- | --- | --- |
| `proposal_id` | yes | Opaque identifier, unique in the response. |
| `category` | yes | One of `skill`, `experience`, `education`, `project`, `language`, `certification`. |
| `value` | yes | The category-specific object (see below). |
| `status` | yes | `proposed`, `approved`, `rejected` or `superseded`. The engine only ever produces `proposed`. |
| `evidence` | yes | One or more quotations. May be empty in a broken response; such a proposal can never be approved. |
| `conflicts` | optional | Ids of the conflict records that involve this proposal. |

### Value shapes

| Category | Value | Displayed as |
| --- | --- | --- |
| `skill` | `{"name": "<skill>"}` | the skill name |
| `experience` | `{"role": "<role title>"}` | the role |
| `education` | `{"level": "<level>", "field": "<subject>"}` | the subject, with the level as a detail |
| `project` | `{"name": "<project title>"}` | the project name |
| `language` | `{"language": "<language>", "stated_level": <string or null>}` | the language, with the stated level as a detail |
| `certification` | `{"name": "<certification>"}` | the certification name |

`education.level` is one of `bachelor`, `master`, `doctorate`, `associate`,
`diploma`, `mba`. `language.stated_level` is the wording the document used; it
is recorded, never interpreted, and shown as "not stated" when it is `null`.

The values are normalised by the engine (lower case, single spaces). The
original wording stays in the quotation.

### Evidence

| Field | Required | Notes |
| --- | --- | --- |
| `document_id` | yes | A document of the source extraction. |
| `segment_index` | yes | Zero-based index into that document's segments. |
| `locator` | yes | The locator of that segment, copied unchanged: `{"kind": "page", "page": n}` or `{"kind": "paragraph", "paragraph": n, "section": "..."}` with 1-based numbers. |
| `quote` | yes | The exact quotation. |
| `start`, `end` | yes | **Python string indices** into the segment text, that is, Unicode code points. |
| `support` | yes | `explicit_claim` or `keyword_mention`. |

`explicit_claim` means the document states the fact; `keyword_mention` means the
word appears in the text without stating it. A mention is not a fact, and the
review view says so on every quotation.

**Code-point offsets.** `start` and `end` are code points, not UTF-16 code
units. JavaScript string indices are UTF-16 code units, and the two differ as
soon as the text contains a character outside the basic multilingual plane. The
adapter therefore applies every offset to `Array.from(text)` and never to a raw
substring. The synthetic sample deliberately contains such a character in
front of a quotation, and the tests assert that a plain JavaScript substring
would return the wrong text there.

### Conflicts

Conflicts are global records. A proposal references them by id.

```json
{
  "conflict_id": "conf_1a2b3c4d5e6f7081",
  "kind": "conflicting_stated_level",
  "category": "language",
  "proposal_ids": ["prop_1111", "prop_2222"],
  "message": "The documents state different levels for the language english."
}
```

| Field | Required | Notes |
| --- | --- | --- |
| `conflict_id` | yes | Unique in the response. |
| `kind` | yes | For example `conflicting_stated_level` or `conflicting_description`. |
| `category` | yes | The category the conflict is about. |
| `proposal_ids` | yes | The proposals that take part in it. |
| `message` | yes | Why the engine reports the conflict. |
| `resolution_hint` | no | An optional suggestion of the backend (see below). |

A proposal that names a conflict the response does not contain is broken: the
reference is marked as unknown and the proposal cannot be approved.

### Optional `resolution_hint`

The backend may suggest how a conflict could be resolved:

```json
{
  "resolution_hint": {
    "strategy": "prefer_higher_cefr_claim",
    "keep_proposal_ids": ["prop_example"],
    "explanation": "C1 is the highest explicitly stated level, but no reliable chronology is available.",
    "requires_user_confirmation": true
  }
}
```

| Field | Required | Notes |
| --- | --- | --- |
| `strategy` | yes | The name of the strategy the backend applied. |
| `keep_proposal_ids` | yes | The proposals the backend suggests keeping. Every id has to be one of the proposals of **this** conflict. |
| `explanation` | yes | The reasoning of the backend, in its own words. |
| `requires_user_confirmation` | no | Whether the backend wants a confirmation. Defaults to `true`. |

A hint is **never applied by itself**. It is shown, and a reviewer has to act
on it:

- A hint that is not an object, has no strategy, names no proposal, names a
  proposal of another conflict, names a proposal that is not in the response or
  carries a non-boolean confirmation flag is dropped. The conflict then has to
  be resolved by hand.
- The interface never interprets a strategy. It shows the suggestion, the
  explanation of the backend and the quotations of the conflicting proposals.
- Taking a suggestion resolves the conflict and records the decision. It never
  approves a fact: the proposals stay proposed until the reviewer approves
  them one by one.

### Blocking canonical conflicts

Every unresolved canonical conflict blocks approval, including unknown kinds.
`conflicting_description` means incompatible project artifact kinds (for example,
a mobile app versus a CLI tool), not different wording. Select exactly one
proposal and record a justification to resolve it manually. No backend
recommendation is displayed without a valid `resolution_hint`.

The backend merges equivalent or complementary project descriptions into one
proposal with multiple evidence references and no conflict. The frontend does
not split or merge those proposals. Resolving any conflict never approves a fact.

## Citation matching and claim support

Support and citation matching are separate facts, and the interface names both:

- `support = explicit_claim` means the document states the claim directly.
- `support = keyword_mention` means the word appears in the text without an
  explicit claim. It is never promoted to an explicit claim.
- Citation matching only asks whether the quotation is the exact text at the
  stated offsets. It does not prove that a claim is true and it is never called
  verification.

Every quotation is compared with the source documents of the current session:

1. The `document_id` must exist in the source, otherwise the citation is
   **not resolved**.
2. The `segment_index` must exist in that document, otherwise the citation is
   **not resolved**.
3. `quote` must equal `segment.text[start:end]` at code-point offsets,
   otherwise it is a **citation mismatch**.
4. The locator must match the block's locator, otherwise it is a **citation
   mismatch**.

A citation mismatch is shown with its reason and blocks approval of that
proposal. The adapter never repairs a quote and never widens a reference.

## Review rules

The rules live in `web/workspace/profile-review.js`, mirror the review reducer
of the engine and are unit tested.

- **Nothing is approved without a click.** The engine's status is the starting
  point; every decision is a user action.
- **Approval requires a matched citation.** A proposal without evidence, or
  with a citation mismatch, is refused exactly like the reducer refuses it.
- **Editing creates a revision.** An edit produces a **new** proposal in the
  `proposed` state. The edited proposal becomes `superseded`, so its approval
  is revoked, and the revision only keeps the evidence that still supports the
  new value. A revision whose value is not contained in the quotations has no
  evidence and can never be approved.
- **The history is kept.** Every action appends an event with its sequence
  number: `approve`, `reject`, `edit` or `resolve_conflict`. The review view
  shows that history, including the revocation of an approval by an edit.
- **Conflicts are never dismissed by a click.** A conflict keeps its proposals
  blocked until a resolution is recorded that says which proposals the
  reviewer stands behind and why. A proposal the reviewer did not keep stays
  blocked. The record is part of the history.
- **A suggestion is a suggestion.** The backend may propose a resolution. The
  interface shows it with the explanation of the backend and the quotations of
  the conflicting proposals, and offers "Use recommendation" next to the manual
  resolution. Taking it records the decision and resolves the conflict; it
  never approves a fact, and the interface never says that a level, a date or
  a claim was confirmed.
- **Compatible descriptions are already merged.** One backend proposal retains
  multiple evidence references. Incompatible project artifact kinds remain
  separate proposals with a blocking conflict.
- **The review state is in memory.** It is not written to `localStorage`, not
  sent to a service and not persisted. Refreshing the page loses every
  decision. That is deliberate for this iteration.

The engine's reducer has no conflict-resolution action, so a resolution taken
in the interface is a **local, unsent decision** until the backend offers an
action for it. The interface says so rather than pretending it was stored.

## The synthetic sample

`web/workspace/fixtures/profile-synthetic.json` is the canonical envelope the
profile engine produced from
`web/workspace/fixtures/profile-preview-source.json`, two synthetic documents
with a `Skills`, `Experience`, `Projects`, `Education`, `Languages` and
`Certifications` section. It holds eighteen proposals over all six
categories, proposals supported by two documents, keyword mentions, one
conflict about two stated levels of the same language, and one conflict about a
project that appears with two different descriptions.

`web/workspace/fixtures/profile-synthetic-recommendation.json` is the same
envelope with the optional suggestion of the backend on the language conflict:
the engine suggests the proposal that states C1, explains why, and asks for a
confirmation.

The preview source contains a character outside the basic multilingual plane in
front of a quotation, so the code-point offsets are exercised by the sample
itself. It keeps the full parser response of the two synthetic documents, which
is what the engine consumed; the request the workspace sends is the projection
of it described in [Request](#request).

`web/workspace/fixtures/profile-invalid-samples.json` holds the broken
examples: a quotation that does not match the text, a document that is not
loaded, a block that does not exist, a reference that points at the wrong
place, a proposal without evidence, a proposal that names a conflict the
response does not contain and a suggestion that names a proposal of another
conflict. The file says in its first line that it is intentionally invalid, and
it is used by the tests only.

Loading the sample shows a warning banner that says it is sample data, and the
view never mixes it with a real extraction: the sample carries its own source
documents, so its evidence is checked against the sample and not against the
CVs in the tab.

## Integration requirements

1. **A local, same-origin profile engine.** Mount `POST {base}/profiles` in the
   application that already serves the workspace, or run it on the same origin.
   The workspace sends no CORS headers and expects none.
2. **The documented request shape.** The endpoint receives exactly
   `{job_id, documents}` with the fields listed above, and answers with the
   envelope of this document.
3. **Stable identifiers.** The engine must echo the `document_id` values it
   received, so its evidence resolves against the extraction in the same tab.
4. **Honest errors.** A rejected request answers with a JSON body
   `{"error": {"code": "...", "message": "..."}}`. The workspace shows the
   message and never invents proposals.
5. **A conflict-resolution action.** The engine's reducer has none yet. Until
   it has one, the resolutions taken in the interface stay local and unsent.
   The same holds for the optional `resolution_hint`: the interface can show it
   and record a decision about it, but it cannot send the decision back.
6. **The suggestion is optional.** A backend that does not send
   `resolution_hint` changes nothing: the conflict is then resolved by hand,
   exactly as before.
7. **No persistence yet.** If decisions must survive a refresh later, that
   needs an explicit store and an explicit decision; it is out of scope for
   this iteration.

## Changing the contract

1. Diff the field names, categories, value shapes and support values against
   this document.
2. Update `web/workspace/profile-adapter.js`:
   - `PROFILE_SCHEMA_VERSION`, `PARSER_SCHEMA_VERSION`, `CATEGORIES`,
     `SUPPORT_KINDS`, `DEGREE_LEVELS`,
   - `CATEGORY_META` and the value shapes of each category,
   - the `normalize*` functions and the citation matching.
3. Update `web/workspace/fixtures/profile-synthetic.json` and
   `profile-preview-source.json`.
4. Update `tests/ui/cv-profile-workspace.test.mjs` and
   `tests/test_cv_workspace_assets.py`.
5. Update this document.

`web/workspace/profile-review.js` and `web/workspace/app.js` work with the
normalized shape and should not need to change.
