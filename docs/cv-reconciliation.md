# Professional claim reconciliation contract (reconciliation schema 0.1)

Reconciliation answers a different question from the profile engine. The
profile engine asks *what does this document state*; the reconciliation layer
asks *how do several documents relate to each other, and what can be
decided*.

It is an additive layer. It does not change profile schema `0.1`, parser
schema `1.1` or transport `1.0`, and it has its own versioned report.

The separation stays visible in the report:

| Layer | Object | Meaning |
| --- | --- | --- |
| Stated | `claims` | What a source says, with the exact evidence. |
| Inferred | `relationships` | What the engine concludes about two claims. |
| Recommended | `decisions` | What the engine proposes, always with a confirmation flag. |
| Unresolved | `decisions` with `outcome: "unresolved"` | What nobody can decide yet. |

Nothing is ever approved automatically, and a recommendation is never a fact.

## Input and output

The input is the same source documents the profile layer consumes: the
parser or transport response, with `schema_version` `"1.1"`, up to five
documents and their segments.

```python
from joblens_public.reconcile import reconcile_documents

report = reconcile_documents(transport_response)
payload = report.as_dict()
```

## Report schema

```json
{
  "reconciliation_schema_version": "0.1",
  "parser_schema_version": "1.1",
  "profile_schema_version": "0.1",
  "job_id": "job_synthetic",
  "documents": [
    {
      "document_id": "doc_alpha",
      "index": 0,
      "filename": "synthetic-cv.pdf",
      "status": "extracted",
      "format": "pdf",
      "segment_count": 1,
      "text_length": 63
    }
  ],
  "claims": [
    {
      "claim_id": "claim_8828984ac0df3bb2",
      "category": "employment",
      "subject": "data engineer",
      "subject_label": "Senior Data Engineer",
      "attributes": [
        { "name": "role", "value": "Senior Data Engineer", "normalized": "senior data engineer" },
        { "name": "organization", "value": "Acme Corporation", "normalized": "acme corporation" },
        { "name": "start", "value": "2019", "normalized": "2019" },
        { "name": "end", "value": "2022", "normalized": "2022" }
      ],
      "evidence": [
        {
          "document_id": "doc_alpha",
          "segment_index": 0,
          "locator": { "kind": "paragraph", "paragraph": 1 },
          "quote": "Senior Data Engineer | Acme Corporation | 2019-2022",
          "start": 11,
          "end": 62,
          "support": "explicit_claim"
        }
      ],
      "qualifier": "explicit_claim"
    }
  ],
  "relationships": [
    {
      "relationship_id": "rel_282e2c3f4e3f80d0",
      "relation": "duplicate",
      "left_claim_id": "claim_8828984ac0df3bb2",
      "right_claim_id": "claim_177c23955e8a8955",
      "attributes": ["role", "organization", "start", "end"],
      "reason": "both sources state the same position with the same period",
      "basis": "employment",
      "evidence": []
    }
  ],
  "decisions": [
    {
      "decision_id": "dec_f7fda91cc6e33c5e",
      "outcome": "auto_consolidate",
      "category": "employment",
      "subject": "data engineer",
      "subject_label": "Senior Data Engineer",
      "keep_claim_ids": [],
      "merge_claim_ids": ["claim_8828984ac0df3bb2", "claim_177c23955e8a8955"],
      "alternative_claim_ids": [],
      "relationship_ids": ["rel_282e2c3f4e3f80d0"],
      "explanation": "The sources state the same fact, so the claims are merged into one and every source is kept; nothing is approved.",
      "requires_user_confirmation": false,
      "approval_state": "not_approved"
    }
  ],
  "consolidated": [
    {
      "subject": "data engineer",
      "category": "employment",
      "subject_label": "Senior Data Engineer",
      "attributes": [],
      "claim_ids": ["claim_8828984ac0df3bb2", "claim_177c23955e8a8955"],
      "evidence": [],
      "qualifiers": ["explicit_claim"],
      "approval_state": "not_approved"
    }
  ],
  "warnings": []
}
```

## Claims

A claim is one statement made by a source. It never carries a status: the
claims of the report are always statements, and the review state lives in the
profile layer.

| Field | Type | Meaning |
| --- | --- | --- |
| `claim_id` | string | Opaque, `claim_` plus 16 hex characters. |
| `category` | string | One of `skill`, `employment`, `organization`, `education`, `institution`, `degree`, `project`, `technology`, `contribution`, `language`, `certification`, `achievement`. |
| `subject` | string | The normalised entity the claim is about. |
| `subject_label` | string | The original wording of that entity. |
| `attributes` | array | `{ "name", "value", "normalized" }`. Only what the source states. |
| `evidence` | array | One or more exact quotations. |
| `qualifier` | string | `explicit_claim` or `keyword_mention`. |

Attributes per category:

| Category | Attributes |
| --- | --- |
| `skill` | `name`, `proficiency` (only when the source states one) |
| `employment` | `role`, `organization`, `start`, `end`, `duration_months`, `duration_exact` |
| `organization` | `name`, `role`, `start`, `end` |
| `education` | `level`, `field`, `institution`, `start`, `end`, or `graduation_year` |
| `institution` | `name` |
| `degree` | `level`, `field`, `institution`, `start`, `end` |
| `project` | `name`, `description`, `technologies` |
| `technology` | `name`, `project` |
| `contribution` | `text`, `project`, `template`, `technologies` (only when the statement names one) |
| `achievement` | `text`, `project`, `template`, `quantities`, `technologies` (only when stated) |
| `language` | `name`, `proficiency`, `date` |
| `certification` | `name`, `issuer`, `date` |

`quantities` holds only genuine numeric quantities, and `technologies` only
names from the closed technology vocabulary. A statement therefore carries one
or the other, never both in one field:

| Statement | Category | `quantities` | `technologies` |
| --- | --- | --- | --- |
| `Built a Python API` | `contribution` | *absent* | `python` |
| `Built a JavaScript API` | `contribution` | *absent* | `javascript` |
| `Reduced latency by 35%` | `achievement` | `35%` | *absent* |
| `Managed 5 engineers` | `achievement` | `5` | *absent* |
| `Processed 1,000 documents` | `achievement` | `1,000` | *absent* |
| `Automated the release pipeline using Docker` | `contribution` | *absent* | `docker` |
| `Reduced latency by 35% using Postgres` | `achievement` | `35%` | `postgresql` |

A statement is an `achievement` only when it states a real figure. A statement
that names a technology instead is a `contribution`, and the technology never
appears in `quantities`. The parser normalises the surface form, so `Postgres`
is recorded as `postgresql` in both fields.

The `template` is the clause with every quantity and every technology replaced
by `#`. Two statements with the same template state the same responsibility
with different values, which the comparator reports as `contradictory`.

A missing attribute is absent. The engine never fills a gap, and it never
reads a fact out of the absence of a statement in another document.

### Support qualifiers

Every claim carries a `qualifier`: `explicit_claim` when the source states it
in a section, or with wording, that claims it, and `keyword_mention` when the
term is only mentioned. The rule is shared with the profile engine:

* a skill in a skills section, or named after an explicit marker such as
  `experience with`, is an `explicit_claim`;
* the same name in free prose is a `keyword_mention`;
* a technology named inside a certification title is part of the credential,
  not a separate skill claim: the certification claim and the cross-category
  comparator already relate it to a stated skill, so no skill is inferred from
  a credential title alone.

An explicit claim and a mention of the same name are **not** the same claim.
They are `complementary`, they are never merged, and a mention is never
promoted. A `consolidated` claim records the qualifiers of the claims it merges
in `qualifiers`, so a merged mention is still visible as a mention.

## Relationships

| Relation | Meaning |
| --- | --- |
| `equivalent` | The claims state the same thing in different wording, through a documented normalisation such as an alias. |
| `duplicate` | The claims state the same thing with the same normalised values. |
| `complementary` | The claims are about the same entity and add different information. |
| `more_specific` | One claim carries strictly more attributes than the other. |
| `less_specific` | The mirror of `more_specific`. |
| `potentially_conflicting` | The claims differ in a way that may be legitimate: different stated proficiencies, different dates for one position, overlapping periods. |
| `contradictory` | The claims cannot both be true: a duration against its own dates, the same responsibility with a different figure or technology, a graduation year outside the period. |
| `temporal_update` | The claims describe the same fact at different times: a promotion, a second degree, a later stint. |
| `unrelated` | The claims are about different entities. Such a pair is not written to the report. |
| `uncertain` | The entity identity is not reliable, for example two similar organisation names, or the same title with no employer to identify it. |

Every relationship names the attributes it is about, a fixed reason, the
`basis` that produced it and the evidence of both sides.

### What may become a `duplicate`

A `duplicate` is the only relation that leads to an automatic merge, so it is
only produced when the sources state enough identity to make it safe:

| Category | A `duplicate` requires |
| --- | --- |
| `skill` | the same name, the same qualifier and the same stated proficiency |
| `language` | the same language and the same stated level |
| `employment` | an employer stated by **both** sources, matching (or close, which is `uncertain` instead), no differing dates, and compatible roles |
| `education`, `degree` | the same level and field **and** at least one shared identity attribute (`institution`, `start` or `end`) with equal values |
| `project` | the same name **and** an identical description |
| `certification` | the same name |
| `technology` | the same name in the same project |
| `contribution`, `achievement` | the same template and the same quantities and technologies |

Two consequences are deliberate:

* a position stated without an employer is not merged with anything, because a
  missing employer is not evidence of a different employer and the same job
  title is not an identity;
* two statements with the same degree name but no institution and no dates
  stay `uncertain`, because nothing identifies the degree.

## Resolution policy

| Outcome | When | Effect |
| --- | --- | --- |
| `auto_consolidate` | Every relation inside the group is `duplicate` or `equivalent`. | The claims are merged into one `consolidated` claim that keeps every source. `merge_claim_ids` names the merged claims, `alternative_claim_ids` is empty and `requires_user_confirmation` is `false`. |
| `recommend` | A defensible preference exists and nothing in the group is in doubt: a `temporal_update`, a `more_specific` claim, or comparable CEFR levels. | The decision names the claim it would keep in `keep_claim_ids` and the claims it does **not** discard in `alternative_claim_ids`. `merge_claim_ids` is empty: nothing is merged. `requires_user_confirmation` is `true`. |
| `unresolved` | The claims are contradictory, potentially conflicting, or the entity is uncertain — or a preference exists beside a contradiction or an uncertain identity. | No preference is proposed. Every claim is named in `alternative_claim_ids`. `requires_user_confirmation` is `true`. |

`merge_claim_ids` is only used by `auto_consolidate`. A recommendation keeps
every other claim as an alternative, and every decision and every consolidated
claim carries `approval_state: "not_approved"`: the engine never approves
anything, and `requires_user_confirmation: false` means no confirmation is
needed for that merge, not that a person approved it.

The policy never assumes that the highest number, the newest upload, the most
favourable statement or the most impressive title is true. A preference comes
from a date the sources state, or from the amount of information a claim
carries, never from the order of the documents. An end date written as
`present` ranks as the most recent period, so a position that is still held is
preferred over an ended one.

The comparable CEFR levels are `A1`, `A2`, `B1`, `B2`, `C1` and `C2`. Any
other wording, such as `native` or `fluent`, is not compared: the conflict
stays unresolved.

## Cross-category reasoning

| Comparison | Relation |
| --- | --- |
| A skill claim and a technology a project names | `complementary` |
| A certification title and a skill it names | `complementary` |
| A position and the organisation it names | `complementary` |
| A degree and the institution it names | `complementary` |
| A project and the technology or responsibility it holds | `complementary` |
| A stated duration and the dates another source states for the same position | `contradictory` |
| A graduation year and a stated education period | `contradictory` |

## Safety and evidence invariants

1. Every claim carries at least one evidence reference with the document id,
   the segment index, the original locator, the exact quotation and the
   offsets. `segments[segment_index].text[start:end] == quote` always holds.
2. The engine never invents a date, a duration, a level, a technology or a
   description. A value that is not written in the text is not an attribute.
   `quantities` holds only figures the source states, and never a technology.
3. The engine never reads a fact out of an absence.
4. `auto_consolidate` is only used for relations that a typed comparator
   proved with enough identity, and it never removes a source.
5. A `keyword_mention` is never promoted to an `explicit_claim`, and a claim
   is never inferred from a credential title alone.
6. `recommend` and `unresolved` always ask for a user confirmation, they keep
   every claim they do not choose as an alternative, and every decision and
   consolidated claim states `approval_state: "not_approved"`. Nothing is ever
   approved.
7. The engine is pure and deterministic: the same documents always produce
   the same claims, relationships and decisions.
8. The report adds no new dependency and changes no existing contract. The
   mapping utility is a separate, additive module.

## Coverage matrix

### Implemented conflict families

| Family | Relation | Outcome |
| --- | --- | --- |
| The same skill, organisation or certification in several sources | `duplicate` | `auto_consolidate` |
| The same skill with two stated proficiencies | `potentially_conflicting` | `unresolved` |
| The same skill stated explicitly in one source and only mentioned in another | `complementary` | no decision |
| The same language with two comparable CEFR levels | `potentially_conflicting` | `recommend` |
| The same language with a CEFR level and a non-CEFR wording | `potentially_conflicting` | `unresolved` |
| The same position with the same employer and the same period | `duplicate` | `auto_consolidate` |
| The same position with overlapping periods | `potentially_conflicting` | `unresolved` |
| The same position in two sequential stints | `temporal_update` | `recommend` |
| The same role at two organisations | `unrelated` | no decision |
| The same role without an employer on either side | `uncertain` | `unresolved` |
| Two similar organisation names | `uncertain` | `unresolved` |
| A stated duration against the stated dates | `contradictory` | `unresolved` |
| A duration that contradicts its own period | — | reported in `warnings` |
| The same degree with the same institution and dates | `duplicate` | `auto_consolidate` |
| The same degree with different dates or institutions | `potentially_conflicting` | `unresolved` |
| The same degree name with no institution and no dates | `uncertain` | `unresolved` |
| A bachelor and a master of one subject | `temporal_update` | `recommend` |
| A graduation year outside the education period | `contradictory` | `unresolved` |
| The same project with the same description and technologies | `duplicate` | `auto_consolidate` |
| The same project name with different descriptions | `complementary` | no decision |
| Complementary technology lists | `complementary` | no decision |
| The same responsibility with a different figure or technology | `contradictory` | `unresolved` |
| A statement that names a technology instead of a figure | — | a `contribution`, never an `achievement` |
| Different responsibilities of one project | `complementary` | no decision |
| A certification against a skill mention | `complementary` | no decision |
| A technology named inside a certification title | — | no skill claim is inferred |
| A position that is still held beside an ended one | `temporal_update` | `recommend` the current one |
| A preference beside a contradiction or an uncertain identity | as above | `unresolved` |
| Contradictions inside one document | as above | as above |
| Three or more conflicting sources | as above | the decision covers the whole group |
| Unicode evidence | — | exact spans preserved |
| A fact missing in one document | — | never a contradiction |

### Not supported, by design

| Case | Why |
| --- | --- |
| A contradiction expressed only in free prose, with no closed vocabulary | The deterministic engine cannot identify it reliably. A semantic reasoner may propose it, and a human decides. |
| Entity resolution between similar but different names | Only a similar-name check exists; a name that differs by more than a suffix is treated as a different entity. |
| Approximate employment dates | A difference in dates is `potentially_conflicting`, never a verdict. |
| An employer or a figure the source does not state | Never inferred from another document, from the upload order or from a technology name; the identity or the measurement simply stays absent. |
| Two projects that only share a name | Without an identical description the statements are `complementary`, never merged. |
| Two degrees that only share a name | Without an institution or dates the statements stay `uncertain`. |
| A chronology the sources do not state | The engine never infers one from the upload order, the file name or the position of a document. |
| Proficiency, seniority or a level that is not written | Never inferred from a mention. |
| Anything that needs world knowledge, a salary, a ranking or a judgement about a person | Out of scope by design. |

Not every human-language contradiction is detectable, and this document does
not claim that it is.

## Mapping a claim to a profile proposal (mapping schema 0.1)

The reconciliation report and the profile envelope describe the same documents
at a different granularity. The mapping utility connects them without guessing:

```python
from joblens_public.profile import build_profile_proposals
from joblens_public.reconcile import map_claims_to_proposals, reconcile_documents

report = reconcile_documents(transport_response)
envelope = build_profile_proposals(transport_response)
mapping = map_claims_to_proposals(report, envelope)
payload = mapping.as_dict()
```

Its own module, `joblens_public.reconcile.mapping`, is additive: it changes
neither artifact, shares no state with them, and never writes a proposal, a
review state or a decision. It is read-only and deterministic.

```json
{
  "mapping_schema_version": "0.1",
  "reconciliation_schema_version": "0.1",
  "profile_schema_version": "0.1",
  "counts": { "matched": 11, "ambiguous": 0, "unmapped": 2 },
  "matches": [
    {
      "claim_id": "claim_b3748c6af3b3f2a1",
      "claim_category": "skill",
      "outcome": "matched",
      "proposal_id": "prop_7cf0da85396b9451",
      "proposal_category": "skill",
      "span_relation": "exact",
      "compatible_attributes": ["name"],
      "conflicting_attributes": [],
      "candidate_proposal_ids": ["prop_7cf0da85396b9451"],
      "claim_support": "explicit_claim",
      "proposal_support": "explicit_claim",
      "reason": "one proposal of a compatible category shares the exact evidence and the stated attributes agree"
    }
  ]
}
```

Every claim of the report gets exactly one outcome:

| Outcome | Meaning |
| --- | --- |
| `matched` | Exactly one proposal of a compatible category shares the evidence, and the attributes both sides state agree. `proposal_id` is set. |
| `ambiguous` | Several proposals share the evidence, or the evidence is shared while the normalised attributes disagree. `proposal_id` is `null` and `candidate_proposal_ids` lists what a person has to look at. |
| `unmapped` | No proposal of a compatible category shares the evidence. |

Category compatibility is closed and explicit:

| Claim category | May map to |
| --- | --- |
| `skill` | `skill` |
| `language` | `language` |
| `employment` | `experience` |
| `education`, `degree` | `education` |
| `project` | `project` |
| `certification` | `certification` |
| `technology`, `contribution`, `achievement` | `project` (they are nested in the project entry) |
| `organization`, `institution` | nothing: no profile category corresponds to them |

An evidence match is only accepted when the quotation agrees exactly.
Identical spans must carry identical text, and a nested span must be the exact
slice of the containing quotation at its own offsets. The utility verifies
that from the quotations alone, so it never needs the source text and it never
invents a correspondence. The contract tests cover the three refusals:

* a proposal whose quotation has been altered at the claim's own offsets is
  `unmapped`, never trusted;
* a claim whose attributes disagree with the only proposal over the same text
  is `ambiguous`, not `matched`;
* two proposals over the same text are `ambiguous`, never a coin toss.

`span_relation` reports how the two spans relate: `exact`,
`claim_within_proposal` (a nested responsibility, technology or project title)
or `proposal_within_claim` (a degree or a role inside a longer education or
experience line). The two layers extract different granularity on purpose, and
the mapping states which one it found instead of hiding it.

The reverse lookup is derived from the same result, so it can never disagree
with it:

```python
mapping.for_proposal("prop_7cf0da85396b9451")  # claim ids matched to it
mapping.for_claim(claim_id)                    # the match of one claim
mapping.by_outcome("ambiguous")                # the claims a person must look at
```

The utility never synchronises the two artifacts: a `matched` outcome reports
that the same source text produced a claim and a proposal. It does not copy a
value, change a proposal status or approve anything.

One asymmetry follows from the layering and is not an error: the profile
engine may keep a `keyword_mention` proposal for a term that the reconciliation
layer deliberately does not restate as a claim, for example a technology named
inside a certification title. Such a proposal has no claim matched to it, and
the mapping never invents one.

## Proposed API contract for the frontend

The frontend consumes the report as it is, and keeps the source response to
resolve the evidence.

1. **Group by `decisions`.** Each decision has an `outcome`:
   `auto_consolidate` (show the consolidated claim), `recommend` (show the
   kept claim first and ask for a confirmation) or `unresolved` (show both
   sides and ask a human).
2. **Never treat a recommendation as a fact.** `requires_user_confirmation`
   is `true` for every `recommend` and `unresolved` decision, and the
   proposals stay unconfirmed until a person acts.
3. **Read `merge_claim_ids` as "merged", and only on
   `auto_consolidate`.** A `recommend` names the claims it does not choose in
   `alternative_claim_ids`; they are kept and must stay visible.
4. **Show `approval_state`.** It is `not_approved` everywhere: no decision and
   no consolidated claim was approved by the engine.
5. **Resolve the evidence** with `document_id` and `segment_index` against
   the source response, and check `segments[segment_index].text[start:end]`
   against `quote` before showing it.
6. **Use `relationships` for the explanation.** `reason` is a fixed sentence,
   `attributes` names the fields in dispute, and `basis` names the comparator
   that produced it.
7. **Read `support` as a qualifier.** `keyword_mention` means the source
   mentions the term, not that it claims it; the `qualifier` of a claim and
   the `qualifiers` of a consolidated claim say the same.
8. **Use the mapping to link the two panes.** `matched` claims line up with a
   proposal; `ambiguous` and `unmapped` ones must be shown without a proposal
   instead of being forced into one.
9. **Treat `warnings` as visible notes**, for example a claim that
   contradicts itself.
10. **Identifiers are scoped to the report.** `claim_`, `rel_`, `dec_` and
    `prop_` are opaque and meaningless outside one report.

## Extensibility and the plan for a local model

The deterministic engine is complete on its own and never needs a model. The
seam is small and explicit:

```python
class SemanticReasoner(Protocol):
    def compare(self, left: Claim, right: Claim) -> SemanticJudgement | None: ...
```

Rules the seam already enforces:

1. The reasoner is only consulted for the pairs the deterministic
   comparators marked `uncertain`.
2. A judgement is rejected unless it cites quotations that exist in the
   evidence of the two claims.
3. A model may not return `duplicate` or `equivalent`: it can never merge
   claims.
4. An accepted judgement is a recommendation that needs a user confirmation.

The plan for a later local Ollama integration:

1. Run the model as a local process, with no network access, started and
   stopped by the application, with a hard timeout and a size limit on the
   prompt.
2. Give the model nothing but the two claims, their attributes and their
   evidence, and ask for a judgement in a fixed JSON shape.
3. Validate every judgement with `validate_judgement` and drop the ones
   that are not supported by the evidence.
4. Keep the deterministic result when the model is unavailable, times out or
   returns something invalid. The engine must behave the same without it.
5. Mark the relationships that come from a model with `semantic: true` and
   `basis: "semantic"`, and never let one reach `auto_consolidate`.
6. Log the judgements and their validation, never the document text.

## Verification

```bash
python3 -m pytest -q tests/test_reconcile_benchmark.py
python3 -m pytest -q tests/test_reconcile_semantic.py
python3 -m pytest -q tests/test_reconcile_quantities.py
python3 -m pytest -q tests/test_reconcile_safety.py
python3 -m pytest -q tests/test_reconcile_mapping.py
python3 -m pytest -q
ruff check .
```

The benchmark covers every CEFR pair, the job titles of one role, concurrent
and sequential positions, compatible and conflicting education dates,
conflicting durations, equivalent and contradictory responsibilities,
complementary technology lists, certifications against skill mentions,
contradictions inside one document, three conflicting sources, uncertain
entity identity, missing dates, contradictory chronology and Unicode
evidence, plus the negative cases that must not be reported as conflicts.

`test_reconcile_quantities.py` is the P0 regression: a technology is never a
quantity, a real figure is an achievement, and a statement with neither stays
a contribution. `test_reconcile_safety.py` is the P1/P3 regression: no merge
without identity evidence, no promotion of a mention, no inference from a
credential title, no merge of two projects that only share a name, a current
period ranks first, and only an automatic consolidation merges claims while
every decision and consolidated claim stays `not_approved`.
`test_reconcile_mapping.py` is the P2 contract: `matched`, `ambiguous` and
`unmapped` outcomes, the containment forms, the refusals and the payload
shape.

Every document in every test is synthetic.
