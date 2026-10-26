# Canonical reconciliation workspace (schema 0.1)

The Reconciliation tab requests the real deterministic Python report using
`POST /api/cv/reconciliations`. It never derives relationships from profile
proposals, compares levels itself, or infers chronology from a year in a quote.

Request: exactly `job_id` and `documents`, projected by `buildProfileRequest`
from the current extraction. Original parser statuses and source segments are
preserved. The server validates the same source contract used by profiles,
adds parser schema 1.1 for the pure engine, calls `reconcile_documents`, and
returns `report.as_dict()` unchanged. See `cv-reconciliation.md` for all fields.

The mounted endpoint reuses Host/Origin and `X-JobLens-Request: 1` checks,
8 MiB JSON body cap, five-document limit, socket read timeout, safe errors and
quiet logging. No jobs, files, reports or review decisions are stored.
Successful reports contain only the engine's versions, job_id, documents,
claims, relationships, decisions, consolidated and warnings.

`reconciliation-adapter.js` validates schema versions, source job/document
identity, unique IDs and cross-references. It groups source claims by the
engine's category/subject identity. Cross-category relationships remain
explicit links; grouping does not consolidate claims. Only the backend's
`consolidated` objects are shown as consolidations, retaining every citation.

The adapter also validates the additive fields of the current contract:

- `alternative_claim_ids` are preserved on `recommend` and `unresolved`
  decisions and keep their claims in the same group.
- `merge_claim_ids` are accepted only for `auto_consolidate`. A recommendation
  or an unresolved decision that tries to merge is rejected.
- `auto_consolidate` cannot retain alternatives. A merge is only a merge.
- `approval_state` is `not_approved`. Any other value fails closed, so no
  engine report can present an approved decision or consolidated claim.
- Consolidated `qualifiers` are preserved and validated against
  `explicit_claim` / `keyword_mention`.
- A claim-level `qualifier` is preserved. `keyword_mention` is never promoted
  to an explicit claim.

Attributes display the original value and normalized value supplied by the
engine, including dates, durations and quantities where present. Relationship
types, comparator basis, reasons, outcomes and confirmation flags are displayed
verbatim. Semantic, uncertain and unknown relationships are marked for review.
Citation checks use Unicode code points and require matching document, segment,
locator and quote. Invalid evidence keeps the group blocking.

### How the report is presented

The primary path is deliberately not a list of all pairwise relationships. The
view is ordered by what a reader can act on:

1. **Summary.** Documents, source claims, safe consolidations, conflicting
   pairs, decisions that need confirmation and conflicting pairs without an
   engine decision. The labels state what each number means; an all-zero view is
   never shown before a report exists.
2. **Needs your attention.** One card per decision that needs the reviewer
   (`recommend` or `unresolved`) and one card per conflicting pair without an
   engine decision. Each card shows the claims side by side, both source
   documents, the differing attribute, a plain-language difference line, the
   verbatim engine explanation under `Engine text`, and the engine outcome.
   A `recommend` card shows the recommended claim under *Recommended for review
   · not approved* and keeps the claims it did not choose under *Retained
   alternative(s)*, so nothing disappears. An `unresolved` card shows every
   candidate under *Retained claim A/B* and states that the engine expresses no
   preference. The only navigation is to Candidate Profile; there is no
   Approve, Apply or bulk action here. A single note above the cards states
   that this screen confirms and approves nothing.
3. **Consolidated information.** One card per engine `consolidated` object, with
   the shared value, both source documents, the support qualifiers of the
   joined claims and an expandable list of the exact quotes. A degree and an
   education record that come from the same source line and carry the same
   attributes are shown on one card, labelled as two canonical records that are
   not merged with each other. Auto-consolidation is described as the engine
   joining equal statements, never as proof or approval.
4. **Remaining claims.** Every source claim that no decision card and no
   consolidated card represents is listed here, with its category, its source
   document, its support qualifier and an expandable exact quote. The count is a
   claim count, so a grouped degree/education row still counts both canonical
   claims. Nothing is hidden in the technical panel: projects, project
   contributions, technologies, skills, employment and education records all
   appear in this group.
5. **Technical details.** All claims, relationship IDs, comparators, offsets,
   outcomes, qualifiers, approval states and raw warnings, inside a closed
   `<details>`. This is the complete dump; the primary path above never
   requires it. The section repeats that no approval, resolution or
   claim-to-proposal mapping is transferred between the reconciliation report
   and the Candidate Profile.

The warning summary above the report says that the engine left technical
warnings and points to the collapsed technical section; raw warning text and
claim IDs do not appear in the primary path. The `Next step` bar becomes
`See what needs attention` while the Consistency view has attention cards.

`auto_consolidate` is never approval. `recommend` and `unresolved` remain
unconfirmed; this view has no approval or bulk-approval actions, and a
`recommend` decision never removes the claims it did not choose.

### Claim-to-proposal mapping

`joblens_public.reconcile.mapping` links a reconciliation claim to a profile
proposal by exact evidence. It is read-only and additive: it never changes a
proposal, its status or its evidence, and it is covered by its own tests in
`tests/test_reconcile_mapping.py`. The mapping is not displayed in this
workspace, because the mounted endpoint returns no mapping object and the
interface has no validated one-to-one link between a claim and a proposal ID.
The report therefore stays read-only: no mapping is guessed, no reconciliation
decision changes Candidate Profile review, and no approval is synchronised in
either direction. The existing profile view retains its own explicit approval,
conflict resolution, editing and in-memory history. A profile decision does
not resolve a reconciliation conflict, and neither view persists anything.

Refreshing or changing the source extraction clears the reconciliation report.
Stale asynchronous responses cannot replace a report for a newer extraction.
The new view uses only the same-origin endpoint. Preview controls are hidden
and disabled; production routes do not expose JSON fixtures or source files.

### Wording rules

- The masthead states the session mode: `No data loaded`, `Your local
  documents` or `Synthetic sample`. Uploaded CVs are never labelled synthetic.
  The footer states `local, in-memory session` or `synthetic sample`.
- Claim support and citation matching are named apart. A claim is an
  *Explicit claim* or a *Keyword mention*; a quotation is a *Citation matched*,
  a *Citation mismatch* or *Citation not checked*. Nothing is called verified
  or unverified, and citation matching is never described as proof.
- Counts are English and pluralised: claims, claim groups, decisions,
  alternatives, documents and quotes.
- No card or summary states that a claim was approved. The engine approval
  state is `not_approved` and the interface says so.

No external AI or Ollama is used. The deterministic reasoner is the only default.
Free-prose contradictions outside supported comparators remain a limitation.

Browser acceptance for this view is exercised with the real synthetic PDF/DOCX
pair through the mounted routes: headless Chromium at 1440x1000 and at a 390x844
mobile viewport, including keyboard tab navigation, expandable evidence, the
collapsed technical panel, summary/count checks, no horizontal overflow, no
console errors, no external requests and direct fixture URLs returning 404.
A second one-document run uses
`.integration-verification/phase2e/integration-qa/remaining.docx` and asserts
that every source claim of a report without decisions or consolidations is
visible in the remaining-claims group, including the project, its contribution
and its technology, and that a degree and an education record from the same
source line are shown on one row without being merged.
That is Chromium evidence, not Safari evidence; Safari rendering is still
unverified. The Node HTTP harness covers the served HTML and the real report
rendering separately from layout.

### Safari readiness

The six findings that were corrected here are DOM-structure and copy problems,
not engine problems: the primary path now renders every source claim, keeps
retained alternatives, names claim support and citation matching apart, uses
English and English pluralisation, groups a degree and an education record from
the same source line instead of repeating them, and labels the session mode
instead of calling every upload synthetic. None of that depends on the browser.

The stylesheet carries the WebKit prefixes Safari needs
(`-webkit-backdrop-filter`, `-webkit-text-size-adjust`,
`-webkit-appearance`), and the adapter falls back to a JSON copy when
`structuredClone` is missing. These are compatibility provisions, not verified
Safari support; no minimum Safari version has been established by testing. The stylesheet uses no `:has()`, no container queries and
no native `dialog`.

What is still missing is a real Safari pass: no WebKit build is installed in
this environment, so the acceptance run is Chromium only. A Safari check should
repeat the desktop and the mobile flow, the open/closed state of every
`<details>`, the sticky header, the viewport width at 390 px and the
`overflow-wrap` of long claim values.
