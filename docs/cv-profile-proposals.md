# Candidate profile proposal contract (profile schema 0.1)

Evidence-grounded candidate fact proposals derived from the CV parser
response (schema `1.1`). This is **not** CV generation. It produces reviewable
proposals from the text the parser actually extracted, and every proposal
points at the exact quotation that produced it.

The engine lives in `src/joblens_public/profile/`. It is a separate layer from
the parser: the parser still only returns text and locators, and nothing here
changes schema `1.1`.

- Pure and deterministic. The same response always yields the same proposals,
  in the same order, with the same identifiers.
- No model, no network call, no database, no automatic approval.
- No text is invented. A proposal without a quotation is never produced.

## Input

The engine consumes the response of the CV HTTP transport, unchanged:

```json
{
  "transport_version": "1.0",
  "schema_version": "1.1",
  "job_id": "job_...",
  "documents": [
    {
      "document_id": "doc_...",
      "index": 0,
      "filename": "synthetic-cv.pdf",
      "format": "pdf",
      "status": "extracted",
      "text": "...",
      "segments": [{ "locator": { "kind": "paragraph", "paragraph": 1 }, "text": "..." }],
      "warnings": [],
      "metadata": { "size_bytes": 0, "page_count": 1, "paragraph_count": null }
    }
  ]
}
```

Requirements on the input:

| Rule | Detail |
| --- | --- |
| `schema_version` | Must be `"1.1"`. Another value is rejected with `ProfileError`. |
| `document_id` | Required on every document. Provenance is never invented. A missing id is rejected. |
| `segments` | An array of `{ "locator": {...}, "text": "..." }`. |
| Document status | Only `extracted` and `partial` documents are read. Other statuses are skipped and reported in `warnings`. |
| Documents | At most five, as in the parser contract. More than five is rejected with `ProfileError`. |

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

| Field | Type | Meaning |
| --- | --- | --- |
| `profile_schema_version` | string | `"0.1"`. Bumped when the envelope changes shape. |
| `parser_schema_version` | string | `"1.1"`. The parser contract the proposals were derived from. |
| `job_id` | string or null | The transport job id, for correlation. |
| `documents` | array | Provenance of every source document, **by reference**. The document text is not copied here. |
| `proposals` | array | The proposed facts. May be empty. |
| `conflicts` | array | The conflict records. May be empty. |
| `warnings` | array | Non-fatal notes, for example a skipped document. |

### Proposal fields

| Field | Type | Meaning |
| --- | --- | --- |
| `proposal_id` | string | Opaque identifier, scoped to this analysis. `prop_` plus 16 hex characters. Stable for the same input; not meaningful across analyses. |
| `category` | string | One of `skill`, `experience`, `education`, `project`, `language`, `certification`. |
| `value` | object | Typed data for the category (see below). |
| `status` | string | `proposed` when produced. The review reducer adds `approved`, `rejected` and `superseded`. |
| `evidence` | array | One or more quotations. A proposal always has at least one. |
| `conflicts` | array | Ids of the conflict records that involve this proposal. |

### Value shapes

| Category | Value | Example |
| --- | --- | --- |
| `skill` | `{"name": "<canonical skill>"}` | `{"name": "python"}` |
| `experience` | `{"role": "<role title>"}` | `{"role": "senior data engineer"}` |
| `education` | `{"level": "<level>", "field": "<subject>"}` | `{"level": "bachelor", "field": "computer science"}` |
| `project` | `{"name": "<project title>"}` | `{"name": "invoice tracker"}` |
| `language` | `{"language": "<language>", "stated_level": <string or null>}` | `{"language": "english", "stated_level": "c1"}` |
| `certification` | `{"name": "<certification>"}` | `{"name": "aws certified solutions architect"}` |

All values are normalised: lower case, single spaces. The original wording is
always available in the evidence quotation.

- `education.level` is one of `bachelor`, `master`, `doctorate`, `associate`,
  `diploma`, `mba`.
- `language.stated_level` is the wording the document used, from a closed list
  (`native`, `fluent`, `advanced`, `intermediate`, `basic`, `elementary`,
  `limited`, `professional`, `conversational`, `a1`…`c2`). It is recorded, not
  interpreted: the engine never maps it onto a proficiency scale.

### Evidence

| Field | Type | Meaning |
| --- | --- | --- |
| `document_id` | string | The document the quotation comes from. |
| `segment_index` | integer | Index in `documents[].segments[]` of the source response. |
| `locator` | object | The locator of that segment, copied unchanged. |
| `quote` | string | The exact quotation. |
| `start`, `end` | integer | Python string indices into the segment text. |
| `support` | string | `explicit_claim` or `keyword_mention`. |

The offsets are the contract: `segment_text[start:end] == quote` always holds,
and the consumer can verify a proposal without trusting the engine.

`support` says how the quotation supports the proposal:

- `explicit_claim`: the document states the fact, for example in a `Skills`
  section, or in a sentence with an explicit marker such as "experience
  with".
- `keyword_mention`: the word appears in the text, but the document does not
  state it as a claim about the candidate. A mention is not a fact.

### Conflicts

```json
{
  "conflict_id": "conf_1a2b3c4d5e6f7081",
  "kind": "conflicting_stated_level",
  "category": "language",
  "proposal_ids": ["prop_1111", "prop_2222"],
  "message": "The documents state different levels for the language english.",
  "resolution_hint": {
    "strategy": "prefer_higher_cefr_claim",
    "keep_proposal_ids": ["prop_1111"],
    "explanation": "C1 is the highest explicitly stated level, but no reliable chronology is available.",
    "requires_user_confirmation": true
  }
}
```

| Kind | When it is reported |
| --- | --- |
| `conflicting_stated_level` | The same language is claimed with two different stated levels. |
| `conflicting_description` | The same project name describes two different kinds of artifact, such as a command line tool and a mobile application. The proposals were not merged. |

The engine reports a conflict only when the documents state something
incompatible. It never merges uncertain entities: two proposals that may or
may not be the same thing stay separate and are linked by a conflict record.

A project whose descriptions differ only in wording, or in technology, is
**not** a conflict. Those descriptions are complementary, so they are merged
into one proposal and every description is kept as a separate evidence
reference, with the original text and its exact span.

#### `resolution_hint`

The `resolution_hint` is optional and additive: a conflict without a
defensible preference has no such field, and a consumer that ignores unknown
fields keeps working.

| Field | Type | Meaning |
| --- | --- | --- |
| `strategy` | string | `prefer_higher_cefr_claim` or `prefer_dated_claim`. |
| `keep_proposal_ids` | array | The proposal or proposals worth keeping first. |
| `explanation` | string | Why, in fixed wording built from the stated levels and dates. |
| `requires_user_confirmation` | boolean | Always `true`. A hint is never an approval and never a proof. |

The rules:

1. Only the recognised CEFR levels `A1`, `A2`, `B1`, `B2`, `C1` and `C2` are
   compared. A claim in any other wording, such as `native`, `fluent` or
   `professional`, is not comparable, so the conflict gets **no** hint and a
   reviewer has to decide.
2. Without a date there is no reliable chronology, so the highest declared
   level is recommended: `prefer_higher_cefr_claim`.
3. A claim that states a date next to it is anchored in time. The most recent
   dated claim is then recommended: `prefer_dated_claim`. This can prefer a
   lower level, because the highest level is not proof of anything.
4. The date is read only from the text of the claim itself, and it stays in
   the evidence quotation. The upload order and the file name are never used
   as a chronology, and no date is ever invented.
5. When no defensible preference exists, there is no hint at all and the
   conflict requires a human decision.

A hint never changes a proposal status. The proposals stay `proposed` until
a reviewer acts.

## Extraction rules

The engine reads the document as a sequence of segments, and each segment as a
sequence of lines. A line that matches a known heading opens a section, and
the section stays open until the next heading.

| Category | Rule | Support |
| --- | --- | --- |
| `skill` | A word from the curated skill vocabulary. | `explicit_claim` in a `Skills` section or next to a marker such as "experience with"; otherwise `keyword_mention`. |
| `education` | An explicit degree statement: a degree word plus a subject, such as "BSc in Computer Science", "MSc Data Science" or "Computer Science, BSc". | Always `explicit_claim`. |
| `experience` | The leading title of a line in an `Experience` section, when it contains a known role noun. | Always `explicit_claim`. |
| `project` | The leading title of a line in a `Projects` section. | Always `explicit_claim`. |
| `language` | A word from the curated language vocabulary. | `explicit_claim` in a `Languages` section; otherwise `keyword_mention`. |
| `certification` | The leading title of a line in a `Certifications` section, when it contains a certification marker or a known certification name. | Always `explicit_claim`. |

### What the engine never does

- It never infers years of experience, dates, durations or employers. The
  quotation of a role title stops at the title.
- It never infers proficiency, seniority or a level from a keyword mention.
- It never derives a degree, an employer or an achievement from a mention.
- It never proposes contact details, dates or achievements at all.
- It never invents provenance. Without a `document_id` there is no proposal.
- It never approves anything. Approval is a separate, explicit action.

### Duplicate grouping

Proposals with the same category and the same normalised value are grouped
into one proposal, and every individual quotation is kept as a separate
evidence reference. Aliases are merged only when they are clearly the same
term, for example `postgres` and `postgresql`, or `js` and `javascript`.

Projects are grouped by name. Two descriptions of the same project are merged
unless they name different kinds of artifact, which is the only difference the
engine treats as a contradiction. A merged project keeps one evidence
reference per source, and each reference quotes the whole entry, so the
original description stays visible with its exact span.

### Known limitations

- Recall is limited by the closed vocabularies. A skill that is not listed is
  never proposed, and a technology the reviewer expects to see may be
  missing. Adding a term is a deliberate, reviewed change to
  `src/joblens_public/profile/lexicon.py`.
- Section headings must be a line of their own that matches a known heading.
  A heading inside a sentence is not recognised.
- The degree subject stops before an institution name, so
  "BSc in Computer Science, University of Manchester" yields the subject
  "computer science" and no institution.
- Two different degrees on one line are both proposed, but only the first
  matching form per subject is used.
- A role title is recognised only when it contains a known role noun, and
  repeated role titles group into one proposal, so employment history is not
  reconstructed.
- Project descriptions are not proposed as values. They stay in the evidence
  quotation, and two descriptions of the same project are merged unless they
  name different kinds of artifact, which is reported as a conflict.
- The artifact vocabulary is small: a project described only as a "tool", a
  "system" or a "solution" is never treated as a contradiction.
- The compatibility clustering is greedy and deterministic: an entry joins the
  first compatible group, so the result never depends on a random order.
- The date used by a resolution hint must be written next to the claim in the
  source text. A date elsewhere in the document, the upload order and the
  file name are never used as a chronology.
- The engine reads the extracted text only. It cannot see a table, a column
  layout or an image, and it never re-reads the original file.

## Review

The review reducer is a separate, pure module. It is not a database and it
writes nothing.

```python
from joblens_public.profile import (
    ReviewAction,
    apply_review_action,
    build_profile_proposals,
    initial_review_state,
)

envelope = build_profile_proposals(transport_response)
state = initial_review_state(envelope)

state = apply_review_action(
    state,
    ReviewAction(kind="approve", proposal_id="prop_aad0beff2dabbfb2"),
)
```

| Action | Effect |
| --- | --- |
| `approve` | The proposal becomes `approved`. Refused when the proposal has no evidence, so an unsupported fact can never become evidence-backed. |
| `reject` | The proposal becomes `rejected`. It stays in the state. |
| `edit` | A new proposal is created with the edited value, in the `proposed` state. The edited proposal becomes `superseded`, so an approval is revoked. The revision only keeps the evidence that still supports the new value. |

Every action appends a `ReviewEvent` to the history, and the history is kept
for the lifetime of the in-memory session. `apply_review_action` never
modifies the state it is given.

A revision whose value is not contained in the quoted evidence has an empty
`evidence` list and cannot be approved. That is how "an unsupported edit must
never appear as an evidence-backed claim" is enforced.

For an education revision the subject must still be quoted, and the degree
must still be quoted in one of its spellings: "BSc in Computer Science"
supports the value `{"level": "bachelor", "field": "computer science"}`.

## HTTP endpoint

The candidate profile engine is mounted in the main local application as
`POST /api/cv/profiles`. It is a bridge, not a second engine: the route
validates the request, rebuilds the parser response shape and calls
`build_profile_proposals()`.

```bash
python3 run_demo.py --port 8765
```

```http
POST /api/cv/profiles HTTP/1.1
Host: 127.0.0.1:8765
Origin: http://127.0.0.1:8765
X-JobLens-Request: 1
Accept: application/json
Content-Type: application/json
Content-Length: 512

{"job_id": "job_9a8b7c6d5e4f3021", "documents": [ ... ]}
```

### Request schema

The body is a JSON object with exactly two keys.

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `job_id` | string | yes | Non-empty. Echoed in the response. |
| `documents` | array | yes | One to five source documents, in order. |

Any other top-level key is rejected with `400`. That is deliberate: the
request has no field that could express a review decision, so a client can
never present an approval as authoritative.

Each entry of `documents` must carry these fields:

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `document_id` | string | yes | Non-empty and unique in the request. Provenance is never invented. |
| `index` | integer | yes | Must equal the position of the document in the array. |
| `filename` | string | yes | The name shown in the response provenance. |
| `status` | string | yes | The parser status, for example `extracted` or `partial`. Only `extracted` and `partial` documents are read. |
| `format` | string | yes | The parser format, for example `pdf`. |
| `segments` | array | yes | The original segments, in order. |

Each entry of `segments` must carry:

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `locator` | object | yes | The original locator, copied into the evidence. |
| `text` | string | yes | The original segment text. The evidence offsets refer to it. |

Unknown fields inside a document or a segment are ignored, so the documents of
a transport response can be sent as they are.

### Request example

```json
{
  "job_id": "job_9a8b7c6d5e4f3021",
  "documents": [
    {
      "document_id": "doc_1f2e3d4c5b6a7081",
      "index": 0,
      "filename": "synthetic-cv.pdf",
      "status": "extracted",
      "format": "pdf",
      "segments": [
        {
          "locator": { "kind": "paragraph", "paragraph": 1 },
          "text": "Skills\nPython, SQL, Docker\n"
        }
      ]
    }
  ]
}
```

### Response

The response is the canonical envelope of this document, unchanged: the
`profile_schema_version`, `parser_schema_version`, `job_id`, `documents`,
`proposals`, `conflicts` and `warnings` fields. The `proposals` are exactly
the proposals the engine produces, and every one of them is `proposed`.

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
      "text_length": 30
    }
  ],
  "proposals": [
    {
      "proposal_id": "prop_6caacb76a81e1e5b",
      "category": "skill",
      "value": { "name": "python" },
      "status": "proposed",
      "evidence": [
        {
          "document_id": "doc_1f2e3d4c5b6a7081",
          "segment_index": 0,
          "locator": { "kind": "paragraph", "paragraph": 1 },
          "quote": "Python",
          "start": 7,
          "end": 13,
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

### Errors

| Condition | Status | `error.code` |
| --- | --- | --- |
| Body is not a JSON object, or a field is missing or of the wrong type | 400 | `invalid_request` |
| Unknown top-level field | 400 | `invalid_request` |
| Body is not valid JSON | 400 | `invalid_json` |
| Content type is not `application/json` | 415 | `invalid_content_type` |
| `Content-Length` is missing | 411 | `length_required` |
| Body is larger than 8 MiB | 413 | `request_too_large` |
| Body is truncated | 400 | `incomplete_body` |
| Read timeout | 408 | `request_timeout` |
| Origin, request token or host is not local | 403 | the application error body |
| Unexpected failure | 500 | `internal_error` |

The error body of this route is:

```json
{
  "profile_schema_version": "0.1",
  "parser_schema_version": "1.1",
  "job_id": null,
  "error": { "code": "invalid_request", "message": "documents must be an array" }
}
```

The 8 MiB limit is separate from the 64 KiB limit of `/api/analyze` and from
the multipart limit of `/api/cv/extractions`: the profile route carries the
extracted text of up to five documents, which the parser bounds at 200,000
characters per document.

The route is loopback only, needs the same origin and the
`X-JobLens-Request: 1` header like the other routes of the application,
answers with `Cache-Control: no-store`, sends no CORS header, keeps
everything in memory and writes nothing.

A proposal can be linked to the claim the reconciliation layer extracted from
the same text with `joblens_public.reconcile.mapping`. That utility is
read-only and additive: it never changes a proposal, its status or its
evidence. Its contract is in
[`docs/cv-reconciliation.md`](cv-reconciliation.md).

## Verification

```bash
python3 -m pytest -q tests/test_profile_engine.py tests/test_profile_review.py
python3 -m pytest -q tests/test_profile_conflicts.py
python3 -m pytest -q tests/test_cv_profile_api.py
```

The tests cover the quote-span integrity of every evidence reference, empty
input, ambiguous documents, explicit claims versus keyword mentions, grouping
of duplicates across documents, conflicting language levels, the approval and
rejection transitions, the revocation of an approval by an edit, and the
refusal to approve an unsupported edit. The conflict tests cover the CEFR
comparison, the equal, unknown and native levels, the dated and undated
claims, the upload-order independence, the duplicate and complementary project
descriptions, and the genuine project ambiguity. The HTTP tests cover the
request and response contract, the multi-document evidence, the duplicates,
the conflicts, the malformed requests and the security checks. Every document
is synthetic.
