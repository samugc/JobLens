# CV generation contract (draft schema 0.1)

JobLens generates a structured, job-tailored CV draft from explicitly
approved candidate facts and a pasted job posting. The generator is
deterministic and does not require Ollama. Nothing is approved
automatically, and no fact enters the draft unless a person approved it.

## Inputs

1. **ApprovedProfile** — a portable, human-approved set of facts with exact
   source evidence. See `joblens_public.profile.approved`.
2. **JobPosting** — parsed from pasted plain text. See `joblens_public.jobs`.
3. **CandidateContact** — user-supplied contact details (optional, may be
   empty).

## ApprovedProfile schema (`approved_profile_version: "0.1"`)

```json
{
  "approved_profile_version": "0.1",
  "parser_schema_version": "1.1",
  "profile_schema_version": "0.1",
  "job_id": "job_...",
  "documents": [ { "document_id": "...", "index": 0, "filename": "...", "status": "extracted", "format": "pdf", "segment_count": 1, "text_length": 100 } ],
  "facts": [
    {
      "fact_id": "prop_...",
      "category": "skill",
      "value": { "name": "python" },
      "evidence": [ { "document_id": "...", "segment_index": 0, "locator": {}, "quote": "Python", "start": 0, "end": 6, "support": "explicit_claim" } ],
      "source_document_ids": ["doc_0"],
      "review_sequence": 4
    }
  ],
  "candidate": { "full_name": null, "email": null, "phone": null, "location": null, "links": [] },
  "review_sequence": 4,
  "review_history": [],
  "warnings": []
}
```

Categories: `skill`, `experience`, `education`, `project`, `language`,
`certification`. A fact without evidence cannot be approved or imported.

## JobPosting schema (`job_posting_version: "0.1"`)

```json
{
  "job_posting_version": "0.1",
  "title": "Senior AI Engineer",
  "company": "Acme AI",
  "location": null,
  "raw_text": "...",
  "required": ["Python", "SQL", "Docker", "Kubernetes", "5+ years experience"],
  "preferred": ["AWS"],
  "technologies": ["python", "sql", "docker", "kubernetes", "aws"],
  "responsibilities": ["Build and deploy machine learning pipelines"],
  "experience_expectations": ["5+ years experience"],
  "other_context": ["We are a fast-growing AI company."]
}
```

The posting is untrusted: it influences ranking and gap reporting only.

## CvDraft schema (`cv_draft_version: "0.1"`)

```json
{
  "cv_draft_version": "0.1",
  "target_job": { "title": "Senior AI Engineer", "company": "Acme AI" },
  "candidate": { "full_name": null, "email": null, "phone": null, "location": null, "links": [] },
  "sections": [
    {
      "section_id": "section_summary",
      "kind": "summary",
      "title": "Professional Summary",
      "items": [
        {
          "item_id": "item_0001",
          "text": "Experienced Data Engineer with expertise in Python, SQL, AWS.",
          "approved_fact_ids": ["prop_..."],
          "review_status": "needs_review"
        }
      ]
    }
  ],
  "warnings": ["Candidate full name is missing and must be supplied by the user."],
  "unmet_requirements": ["Kubernetes"]
}
```

Section kinds: `summary`, `experience`, `projects`, `education`, `skills`,
`languages`, `certifications`. Item review states: `needs_review`,
`approved`. Every factual item has at least one `approved_fact_ids` entry.
Optional item attributes: `heading`, `subheading`, `period`, `location`.

A generated draft is never approved: every item starts as `needs_review`.

## Domain entrypoints

```python
from joblens_public.profile.approved import (
    build_approved_profile, export_approved_profile, import_approved_profile,
    validate_approved_profile,
)
from joblens_public.jobs import parse_job_posting
from joblens_public.cv import generate_cv_draft, edit_cv_item, approve_cv_item,
    validate_export_eligibility, can_export
```

- `build_approved_profile(envelope, review_state, candidate_contact=..., source_response=...)`
- `export_approved_profile(profile) -> str` (private local JSON)
- `import_approved_profile(payload, source_response=...) -> ApprovedProfile`
- `validate_approved_profile(profile, source_response=None)` (raises on inconsistency)
- `parse_job_posting(text, title=..., company=..., location=...) -> JobPosting`
- `generate_cv_draft(profile, job, ollama=False) -> CvDraft`
- `edit_cv_item(draft, item_id, new_text) -> CvDraft` (revokes approval)
- `approve_cv_item(draft, item_id) -> CvDraft` (explicit only)
- `validate_export_eligibility(draft) -> list[str]`

## Proposed same-origin HTTP contract

The integrated webapp owns the routes. Suggested endpoints:

- `POST /api/cv/approved-profiles/export` — body: approved profile JSON; response: the validated profile (echo) plus a `filename` hint. Stores nothing server-side.
- `POST /api/cv/approved-profiles/import` — body: `{ "profile": <json>, "source": <parser response or job id> }`; validates evidence against retained source material; returns the profile or a 4xx with a structured error.
- `POST /api/cv/jobs` — body: `{ "text": "...", "title": "...", "company": "...", "location": "..." }`; returns a `JobPosting`.
- `POST /api/cv/drafts` — body: `{ "profile": <approved profile>, "job": <job posting> }`; returns a `CvDraft`. Deterministic, no Ollama.
- `POST /api/cv/drafts/{id}/items/{item_id}` — edit an item (revokes approval).
- `POST /api/cv/drafts/{id}/items/{item_id}/approve` — explicit approval.
- `GET /api/cv/drafts/{id}/export-eligibility` — returns `{ "can_export": bool, "reasons": [...] }`.

Errors are returned as `{ "error": { "code": "...", "message": "..." } }` with
HTTP 400 for validation failures and 409 for inconsistent evidence.

## Validation and error contracts

- Malformed JSON, wrong schema version, unknown category, duplicate fact id,
  missing evidence, invalid offsets, evidence that does not match the source,
  unknown document or segment → `ApprovedProfileError` → HTTP 400.
- An item without approved facts cannot be approved → 400.
- Editing an item resets its `review_status` to `needs_review`.
- Export is blocked until every item is `approved` and the candidate has a
  full name.

## Safety

- Job postings are untrusted: they influence ranking and gap reporting only.
- No network dependency; Ollama is optional and falls back to the
  deterministic generator on any failure.
- No private data is transmitted; export/import is explicit and local.
