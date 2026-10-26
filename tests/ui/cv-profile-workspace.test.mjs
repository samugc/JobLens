import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const require = createRequire(import.meta.url);
const HERE = dirname(fileURLToPath(import.meta.url));
const WORKSPACE = join(HERE, "..", "..", "web", "workspace");
const cvp = require(join(WORKSPACE, "profile-adapter.js"));
const cvr = require(join(WORKSPACE, "profile-review.js"));

function fixture(name) {
  return JSON.parse(readFileSync(join(WORKSPACE, "fixtures", `${name}.json`), "utf8"));
}

function jsonResponse(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(payload),
  };
}

function preview() {
  return cvp.normalizePreviewEnvelope(
    fixture("profile-synthetic"),
    fixture("profile-preview-source"),
  );
}

function recommendationPreview() {
  return cvp.normalizePreviewEnvelope(
    fixture("profile-synthetic-recommendation"),
    fixture("profile-preview-source"),
  );
}

function state(profile) {
  return cvr.createReviewState(profile);
}

function model(profile, reviewState) {
  return cvr.buildViewModel(profile, reviewState, cvp);
}

function proposalById(view, proposalId) {
  return view.proposals.find((proposal) => proposal.id === proposalId);
}

test("the adapter targets the canonical profile and parser versions", () => {
  assert.equal(cvp.PROFILE_SCHEMA_VERSION, "0.1");
  assert.equal(cvp.PARSER_SCHEMA_VERSION, "1.1");
  assert.deepEqual([...cvp.CATEGORIES], [
    "skill",
    "experience",
    "education",
    "project",
    "language",
    "certification",
  ]);
  assert.deepEqual([...cvp.SUPPORT_KINDS], ["explicit_claim", "keyword_mention"]);
  assert.deepEqual([...cvp.DEGREE_LEVELS], [
    "bachelor",
    "master",
    "doctorate",
    "associate",
    "diploma",
    "mba",
  ]);
});

test("the canonical envelope is accepted with its source documents", () => {
  const { profile } = preview();

  assert.equal(profile.schemaVersion, "0.1");
  assert.equal(profile.parserSchemaVersion, "1.1");
  assert.equal(profile.jobId, "job_synthetic_profile");
  assert.deepEqual(profile.warnings, []);
  assert.equal(profile.documents.length, 2);
  assert.equal(profile.documents[0].documentId, "doc_synthetic_cv_0");
  assert.equal(profile.documents[0].filename, "synthetic-cv.pdf");
  assert.equal(profile.documents[0].status, "extracted");
  assert.equal(profile.documents[0].segmentCount, 6);
  assert.equal(typeof profile.documents[0].textLength, "number");
});

test("every category carries the exact value shape of the contract", () => {
  const { profile } = preview();
  const values = new Map();

  for (const proposal of profile.proposals) {
    if (!values.has(proposal.category)) values.set(proposal.category, proposal.value);
  }

  assert.deepEqual([...values.keys()].sort(), [...cvp.CATEGORIES].sort());
  assert.deepEqual(Object.keys(values.get("skill")), ["name"]);
  assert.deepEqual(Object.keys(values.get("experience")), ["role"]);
  assert.deepEqual(Object.keys(values.get("education")).sort(), ["field", "level"]);
  assert.deepEqual(Object.keys(values.get("project")), ["name"]);
  assert.deepEqual(Object.keys(values.get("language")).sort(), ["language", "stated_level"]);
  assert.deepEqual(Object.keys(values.get("certification")), ["name"]);

  const education = profile.proposals.find(
    (proposal) => proposal.category === "education",
  );
  assert.equal(education.label, "computer science");
  assert.deepEqual(education.details, [
    { key: "level", label: "Level", value: "bachelor" },
  ]);

  const language = profile.proposals.find(
    (proposal) => proposal.category === "language",
  );
  assert.equal(language.label, "english");
  assert.deepEqual(language.details, [
    { key: "stated_level", label: "Stated level", value: "c1" },
  ]);

  const experience = profile.proposals.find(
    (proposal) => proposal.category === "experience",
  );
  assert.equal(experience.label, "data engineer");
});

test("evidence quotes are checked at code-point offsets, not UTF-16 offsets", () => {
  const source = fixture("profile-preview-source");
  const document = source.documents[0];
  const text = document.segments[0].text;

  // The synthetic CV puts a character outside the basic multilingual plane in
  // front of the quotation, so the two offset systems disagree.
  assert.ok([...text].some((character) => character.codePointAt(0) > 0xffff));

  const { profile } = preview();
  const python = profile.proposals.find(
    (proposal) =>
      proposal.category === "skill" && proposal.value.name === "python",
  );
  const reference = python.evidence.find(
    (entry) => entry.documentId === "doc_synthetic_cv_0",
  );

  assert.equal(reference.verified, true);
  assert.equal(reference.resolved, true);
  assert.equal(cvp.codePointSlice(text, reference.start, reference.end), reference.quote);
  // A plain JavaScript substring is wrong here: it counts UTF-16 code units.
  assert.notEqual(text.slice(reference.start, reference.end), reference.quote);
});

test("a proposal can be supported by more than one document", () => {
  const { profile } = preview();
  const python = profile.proposals.find(
    (proposal) =>
      proposal.category === "skill" && proposal.value.name === "python",
  );

  assert.equal(python.evidence.length, 2);
  assert.deepEqual(
    python.evidence.map((entry) => entry.documentId).sort(),
    ["doc_synthetic_cv_0", "doc_synthetic_letter_1"],
  );
  for (const entry of python.evidence) {
    assert.equal(entry.verified, true);
  }
});

test("the support values of the contract are kept apart", () => {
  const { profile } = preview();
  const explicit = profile.proposals.find(
    (proposal) =>
      proposal.category === "skill" && proposal.value.name === "python",
  );
  assert.equal(explicit.evidence[0].support, "explicit_claim");
  assert.equal(explicit.evidence[0].supportLabel, "Explicit claim");

  const mention = profile.proposals.find(
    (proposal) =>
      proposal.category === "skill" && proposal.value.name === "aws",
  );
  assert.equal(mention.evidence[0].support, "keyword_mention");
  assert.equal(mention.evidence[0].supportLabel, "Keyword mention");
});

test("conflicts are global records that proposals reference by id", () => {
  const { profile } = recommendationPreview();

  assert.equal(profile.conflicts.length, 2);
  const conflict = profile.conflicts.find(
    (item) => item.kind === "conflicting_stated_level",
  );
  assert.equal(conflict.conflictId, "conf_432dd4b794242232");
  assert.equal(conflict.kind, "conflicting_stated_level");
  assert.equal(conflict.category, "language");
  assert.equal(conflict.proposalIds.length, 2);
  assert.match(conflict.message, /different levels/);

  for (const proposalId of conflict.proposalIds) {
    const proposal = profile.proposals.find((item) => item.id === proposalId);
    assert.deepEqual(proposal.conflictIds, [conflict.conflictId]);
    assert.equal(proposal.conflicts[0].known, true);
    assert.equal(proposal.conflicts[0].message, conflict.message);
  }
});

test("malformed envelopes are rejected", () => {
  const cases = [
    [null, /response: expected an object/],
    [{ proposals: [] }, /profile_schema_version: expected a string/],
    [
      { profile_schema_version: "0.2", parser_schema_version: "1.1", proposals: [] },
      /Unsupported profile_schema_version/,
    ],
    [
      { profile_schema_version: "0.1", parser_schema_version: "1.0", proposals: [] },
      /Unsupported parser_schema_version/,
    ],
    [
      { profile_schema_version: "0.1", parser_schema_version: "1.1" },
      /proposals: expected an array/,
    ],
    [
      {
        profile_schema_version: "0.1",
        parser_schema_version: "1.1",
        proposals: [
          {
            proposal_id: "p1",
            category: "skill",
            value: { name: "python" },
            status: "proposed",
          },
        ],
      },
      /evidence: expected an array/,
    ],
    [
      {
        profile_schema_version: "0.1",
        parser_schema_version: "1.1",
        proposals: [
          {
            proposal_id: "p1",
            category: "skill",
            value: { name: "python" },
            status: "unknown",
            evidence: [],
          },
        ],
      },
      /unknown proposal status “unknown”/,
    ],
    [
      {
        profile_schema_version: "0.1",
        parser_schema_version: "1.1",
        proposals: [
          {
            proposal_id: "p1",
            category: "education",
            value: { level: "bachelor" },
            status: "proposed",
            evidence: [],
          },
        ],
      },
      /value.field: expected a non-empty string/,
    ],
    [
      {
        profile_schema_version: "0.1",
        parser_schema_version: "1.1",
        proposals: [
          {
            proposal_id: "p1",
            category: "education",
            value: { level: "phd", field: "computer science" },
            status: "proposed",
            evidence: [],
          },
        ],
      },
      /value.level: expected one of/,
    ],
    [
      {
        profile_schema_version: "0.1",
        parser_schema_version: "1.1",
        proposals: [
          {
            proposal_id: "p1",
            category: "skill",
            value: { name: "python" },
            status: "proposed",
            evidence: [
              {
                document_id: "doc-1",
                segment_index: 0,
                locator: { kind: "page", page: 1 },
                quote: "python",
                start: 0,
                end: 6,
                support: "mentioned",
              },
            ],
          },
        ],
      },
      /expected “explicit_claim” or “keyword_mention”/,
    ],
  ];

  for (const [payload, pattern] of cases) {
    assert.throws(
      () => cvp.normalizeProfileEnvelope(payload),
      (error) => {
        assert.equal(error.name, "CvProfileContractError");
        assert.equal(error.code, "contract_error");
        assert.match(error.message, pattern);
        return true;
      },
    );
  }
});

test("an empty profile is valid and reports zero counts", () => {
  const profile = cvp.normalizeProfileEnvelope({
    profile_schema_version: "0.1",
    parser_schema_version: "1.1",
    job_id: null,
    documents: [],
    proposals: [],
    conflicts: [],
    warnings: [],
  });

  assert.equal(profile.counts.total, 0);
  assert.equal(profile.counts.proposed, 0);
  assert.equal(profile.counts.approved, 0);
  assert.equal(profile.counts.rejected, 0);
  assert.equal(profile.counts.superseded, 0);
  assert.equal(profile.counts.unresolved, 0);

  const view = model(profile, state(profile));
  assert.deepEqual(view.groups, []);
  assert.equal(view.counts.total, 0);
});

test("the intentionally invalid samples can never be approved", () => {
  const source = fixture("profile-preview-source");
  const profile = cvp.normalizeProfileEnvelope(
    fixture("profile-invalid-samples"),
    { source: cvp.buildSource(source) },
  );
  const view = model(profile, state(profile));

  const expectations = {
    prop_invalid_quote: /does not match the extracted text/,
    prop_invalid_document: /not in this session/,
    prop_invalid_segment: /does not exist/,
    prop_invalid_locator: /does not match the extracted block/,
  };

  for (const [proposalId, pattern] of Object.entries(expectations)) {
    const proposal = proposalById(view, proposalId);
    assert.ok(proposal, proposalId);
    assert.equal(proposal.canApprove, false, proposalId);
    assert.match(proposal.evidence[0].reason, pattern);
    assert.match(proposal.approveReason, /evidence does not resolve/);
  }

  const noEvidence = proposalById(view, "prop_invalid_no_evidence");
  assert.equal(noEvidence.canApprove, false);
  assert.match(noEvidence.approveReason, /without evidence/);

  const unknownConflict = proposalById(view, "prop_invalid_unknown_conflict");
  assert.equal(unknownConflict.canApprove, false);
  assert.match(unknownConflict.approveReason, /conflict/);
  assert.equal(unknownConflict.conflicts[0].known, false);
});

test("a conflict without a suggestion is resolved by hand", () => {
  const raw = fixture("profile-synthetic-recommendation");
  for (const conflict of raw.conflicts) delete conflict.resolution_hint;
  const profile = cvp.normalizeProfileEnvelope(raw, {
    source: cvp.buildSource(fixture("profile-preview-source")),
  });
  const conflict = profile.conflicts.find(
    (item) => item.kind === "conflicting_stated_level",
  );

  assert.equal(conflict.resolutionHint, null);
  assert.equal(conflict.resolutionHintIssue, null);
  assert.equal(conflict.suggestion, null);
  assert.equal(conflict.blocking, true);
});

test("the B2 versus C1 conflict carries a usable backend suggestion", () => {
  const { profile } = preview();
  const conflict = profile.conflicts.find(
    (item) => item.kind === "conflicting_stated_level",
  );

  assert.equal(conflict.resolutionHint.strategy, "prefer_higher_cefr_claim");
  assert.deepEqual(conflict.resolutionHint.keepProposalIds, ["prop_5d140fe600f64396"]);
  assert.match(conflict.resolutionHint.explanation, /C1 is the highest/);
  assert.equal(conflict.resolutionHint.requiresUserConfirmation, true);
  assert.equal(conflict.suggestion.label, "english (Stated level: c1)");
  assert.deepEqual(conflict.suggestion.proposalIds, ["prop_5d140fe600f64396"]);

  // The suggestion only speaks about the proposals of its own conflict.
  for (const id of conflict.resolutionHint.keepProposalIds) {
    assert.ok(conflict.proposalIds.includes(id));
  }
});

test("a malformed suggestion is never offered", () => {
  const source = fixture("profile-preview-source");
  const profile = cvp.normalizeProfileEnvelope(
    fixture("profile-invalid-samples"),
    { source: cvp.buildSource(source) },
  );
  const conflict = profile.conflicts.find(
    (item) => item.conflictId === "conf_malformed_hint",
  );

  assert.equal(conflict.resolutionHint, null);
  assert.match(conflict.resolutionHintIssue, /not part of this conflict/);
  assert.equal(conflict.suggestion, null);
});

test("a suggestion that names an unknown proposal is dropped", () => {
  const raw = fixture("profile-synthetic");
  raw.conflicts[0].proposal_ids = [
    ...raw.conflicts[0].proposal_ids,
    "prop_not_in_this_response",
  ];
  raw.conflicts[0].resolution_hint.keep_proposal_ids = ["prop_not_in_this_response"];

  const profile = cvp.normalizeProfileEnvelope(raw, {
    source: cvp.buildSource(fixture("profile-preview-source")),
  });
  const conflict = profile.conflicts[0];

  assert.equal(conflict.resolutionHint, null);
  assert.match(conflict.resolutionHintIssue, /not in this response/);
  assert.equal(conflict.suggestion, null);
});

test("taking the suggestion records the decision and approves nothing", () => {
  const { profile } = recommendationPreview();
  const review = state(profile);
  const conflict = profile.conflicts.find(
    (item) => item.kind === "conflicting_stated_level",
  );
  const [c1, b2] = conflict.proposalIds;

  // Before the decision both proposals are blocked.
  let view = model(profile, review);
  assert.equal(proposalById(view, c1).canApprove, false);
  assert.equal(proposalById(view, b2).canApprove, false);

  const taken = cvr.applyReviewAction(
    review,
    { kind: "use_recommendation", conflictId: conflict.conflictId },
    { adapter: cvp },
  );
  assert.equal(taken.applied, true);

  view = model(profile, taken.state);
  const resolution = view.conflicts.find(
    (item) => item.conflictId === conflict.conflictId,
  );
  assert.equal(resolution.resolved, true);
  assert.equal(resolution.resolution.source, "recommendation");
  assert.equal(resolution.resolution.strategy, "prefer_higher_cefr_claim");
  assert.deepEqual(resolution.resolution.kept, [c1]);

  // The recommendation resolves the conflict, it does not approve the fact.
  assert.equal(proposalById(view, c1).status, "proposed");
  assert.equal(proposalById(view, b2).status, "proposed");
  assert.equal(view.counts.approved, 0);
  assert.equal(view.counts.unresolved, 1, "project contradiction remains unresolved");

  const projectConflict = view.conflicts.find(c => c.kind === "conflicting_description");
  assert.equal(projectConflict.resolved, false);
  for (const id of projectConflict.proposalIds) assert.equal(proposalById(view, id).canApprove, false);

  // The suggested proposal may now be approved, by hand.
  assert.equal(proposalById(view, c1).canApprove, true);
  assert.equal(proposalById(view, b2).canApprove, false);
  assert.match(proposalById(view, b2).approveReason, /not kept/);

  const approved = cvr.applyReviewAction(
    taken.state,
    { kind: "approve", proposalId: c1 },
    { adapter: cvp },
  );
  assert.equal(approved.applied, true);

  const after = model(profile, approved.state);
  assert.equal(after.counts.approved, 1);
  assert.equal(proposalById(after, c1).status, "approved");
  assert.deepEqual(
    after.history.map((event) => event.kind),
    ["use_recommendation", "approve"],
  );
  assert.equal(after.history[0].detail.strategy, "prefer_higher_cefr_claim");
});

test("the reviewer can disagree with the suggestion and resolve by hand", () => {
  const { profile } = recommendationPreview();
  const review = state(profile);
  const conflict = profile.conflicts.find(
    (item) => item.kind === "conflicting_stated_level",
  );
  const [c1, b2] = conflict.proposalIds;

  const manual = cvr.applyReviewAction(
    review,
    {
      kind: "resolve_conflict",
      conflictId: conflict.conflictId,
      kept: [b2],
      note: "The CV is the signed document; the letter was written earlier.",
    },
    { adapter: cvp },
  );
  assert.equal(manual.applied, true);

  const view = model(profile, manual.state);
  const resolution = view.conflicts.find(
    (item) => item.conflictId === conflict.conflictId,
  );
  assert.equal(resolution.resolution.source, "manual");
  assert.deepEqual(resolution.resolution.kept, [b2]);

  // The recommendation is not applied on top of the manual decision.
  assert.equal(proposalById(view, c1).canApprove, false);
  assert.match(proposalById(view, c1).approveReason, /not kept/);
  assert.equal(proposalById(view, b2).canApprove, true);
  assert.equal(view.history[0].kind, "resolve_conflict");
});

test("complementary projects remain one backend proposal with both citations", () => {
  const { profile } = cvp.normalizePreviewEnvelope(
    fixture("profile-complementary"), fixture("profile-complementary-source"),
  );
  assert.equal(profile.proposals.length, 1);
  assert.equal(profile.conflicts.length, 0);
  assert.equal(new Set(profile.proposals[0].evidence.map(e => e.documentId)).size, 2);
  assert.ok(profile.proposals[0].evidence.every(e => e.verified));
  assert.equal(profile.proposals[0].status, "proposed");
});

test("project artifact contradictions block until a justified manual selection", () => {
  const { profile } = recommendationPreview();
  const conflict = profile.conflicts.find(c => c.kind === "conflicting_description");
  const initial = state(profile);
  assert.equal(conflict.blocking, true);
  assert.equal(conflict.resolutionHint, null);
  assert.equal(conflict.suggestion, null);
  assert.equal(conflict.proposalIds.length, 2);
  const run = action => cvr.applyReviewAction(initial, action, { adapter: cvp });
  for (const id of conflict.proposalIds) {
    assert.equal(proposalById(model(profile, initial), id).canApprove, false);
    assert.equal(run({ kind: "approve", proposalId: id }).applied, false);
  }
  assert.equal(run({kind: "use_recommendation", conflictId: conflict.conflictId}).applied, false);
  const action = {kind: "resolve_conflict", conflictId: conflict.conflictId,
    kept: [conflict.proposalIds[0]], note: "Reviewer selects the CLI artifact based on this source."};
  assert.equal(run({...action, note: ""}).applied, false);
  assert.equal(run({...action, kept: []}).applied, false);
  assert.equal(run({...action, kept: conflict.proposalIds}).applied, false);
  const result = run(action);
  assert.equal(result.applied, true);
  const view = model(profile, result.state);
  const record = view.conflicts.find(c => c.conflictId === conflict.conflictId).resolution;
  assert.deepEqual(record.kept, action.kept);
  assert.equal(record.note, action.note);
  assert.equal(record.source, "manual");
  assert.equal(view.history[0].kind, "resolve_conflict");
  assert.equal(view.counts.approved, 0);
  assert.ok(view.proposals.every(p => p.status === "proposed"));
  assert.equal(proposalById(view, action.kept[0]).canApprove, true);
  assert.equal(proposalById(view, conflict.proposalIds[1]).canApprove, false);
});

test("unknown canonical conflict kinds also block", () => {
  const raw = fixture("profile-synthetic-recommendation");
  raw.conflicts[1].kind = "future_canonical_conflict";
  const { profile } = cvp.normalizePreviewEnvelope(raw, fixture("profile-preview-source"));
  const view = model(profile, state(profile));
  assert.equal(view.counts.unresolved, 2);
  for (const id of profile.conflicts[1].proposalIds) assert.equal(proposalById(view, id).canApprove, false);
});

test("the conflicting quotes keep their source citations", () => {
  const { profile } = recommendationPreview();
  const conflict = profile.conflicts.find(
    (item) => item.kind === "conflicting_stated_level",
  );

  const citations = conflict.proposalIds.map((proposalId) => {
    const proposal = profile.proposals.find((item) => item.id === proposalId);
    const evidence = proposal.evidence[0];
    return {
      proposalId,
      documentId: evidence.documentId,
      filename: evidence.document.filename,
      locator: evidence.locator,
      quote: evidence.quote,
      verified: evidence.verified,
    };
  });

  assert.equal(citations.length, 2);
  assert.notEqual(citations[0].documentId, citations[1].documentId);
  assert.ok(citations[0].filename);
  assert.ok(citations[1].filename);
  assert.equal(citations[0].locator.kind, "page");
  assert.equal(citations[1].locator.kind, "paragraph");
  for (const citation of citations) {
    assert.equal(citation.verified, true);
    assert.ok(citation.quote.length > 0);
  }
});

test("editing after an approval still revokes it", () => {
  const { profile } = recommendationPreview();
  let review = state(profile);
  const conflict = profile.conflicts.find(
    (item) => item.kind === "conflicting_stated_level",
  );
  const [c1] = conflict.proposalIds;

  review = cvr.applyReviewAction(
    review,
    { kind: "use_recommendation", conflictId: conflict.conflictId },
    { adapter: cvp },
  ).state;
  review = cvr.applyReviewAction(
    review,
    { kind: "approve", proposalId: c1 },
    { adapter: cvp },
  ).state;

  let view = model(profile, review);
  assert.equal(view.counts.approved, 1);

  const edited = cvr.applyReviewAction(
    review,
    { kind: "edit", proposalId: c1, value: { language: "english", stated_level: "c2" } },
    { adapter: cvp },
  );
  assert.equal(edited.applied, true);
  assert.equal(edited.supported, false, "C2 is not quoted anywhere");

  view = model(profile, edited.state);
  assert.equal(view.counts.approved, 0);
  assert.equal(view.counts.superseded, 1);
  assert.deepEqual(
    view.history.map((event) => event.kind),
    ["use_recommendation", "approve", "edit"],
  );
  assert.equal(proposalById(view, edited.revisionId).canApprove, false);
});

test("approving records the decision and nothing is approved without an action", () => {
  const { profile } = preview();
  const review = state(profile);
  const view = model(profile, review);

  assert.equal(view.counts.approved, 0);
  assert.equal(view.history.length, 0);
  assert.ok(profile.proposals.every((proposal) => proposal.status === "proposed"));

  const target = profile.proposals.find(
    (proposal) => proposal.category === "skill" && proposal.value.name === "python",
  );
  const result = cvr.applyReviewAction(
    review,
    { kind: "approve", proposalId: target.id },
    { adapter: cvp },
  );
  assert.equal(result.applied, true);

  const updated = model(profile, result.state);
  assert.equal(updated.counts.approved, 1);
  assert.equal(updated.counts.proposed, profile.proposals.length - 1);
  assert.equal(updated.history.length, 1);
  assert.equal(updated.history[0].kind, "approve");
  assert.equal(updated.history[0].proposal_id, target.id);
});

test("a conflict blocks approval until it is resolved with a record", () => {
  const { profile } = recommendationPreview();
  const review = state(profile);
  const conflict = profile.conflicts[0];
  const [firstId, secondId] = conflict.proposalIds;

  let view = model(profile, review);
  const blocked = proposalById(view, firstId);
  assert.equal(blocked.canApprove, false);
  assert.match(blocked.approveReason, /conflict/);

  // A resolution without a note or without a choice is refused.
  const withoutNote = cvr.applyReviewAction(
    review,
    { kind: "resolve_conflict", conflictId: conflict.conflictId, kept: [firstId] },
    { adapter: cvp },
  );
  assert.equal(withoutNote.applied, false);
  assert.match(withoutNote.reason, /record why/);

  const withoutChoice = cvr.applyReviewAction(
    review,
    { kind: "resolve_conflict", conflictId: conflict.conflictId, kept: [], note: "kept" },
    { adapter: cvp },
  );
  assert.equal(withoutChoice.applied, false);
  assert.match(withoutChoice.reason, /stands behind/);

  const resolution = cvr.applyReviewAction(
    review,
    {
      kind: "resolve_conflict",
      conflictId: conflict.conflictId,
      kept: [firstId],
      note: "The cover letter states the level, the CV does not.",
    },
    { adapter: cvp },
  );
  assert.equal(resolution.applied, true);
  assert.equal(resolution.state.history.length, 1);
  assert.equal(resolution.state.history[0].kind, "resolve_conflict");
  assert.match(resolution.state.history[0].detail.note, /cover letter/);

  view = model(profile, resolution.state);
  assert.equal(view.counts.unresolved, 1, "project contradiction remains unresolved");
  assert.equal(proposalById(view, firstId).canApprove, true);
  // The proposal the reviewer did not keep stays blocked.
  assert.equal(proposalById(view, secondId).canApprove, false);
  assert.match(proposalById(view, secondId).approveReason, /not kept/);

  const approved = cvr.applyReviewAction(
    resolution.state,
    { kind: "approve", proposalId: firstId },
    { adapter: cvp },
  );
  assert.equal(approved.applied, true);
});

test("editing creates a proposed revision and revokes the approval", () => {
  const { profile } = preview();
  let review = state(profile);

  const target = profile.proposals.find(
    (proposal) => proposal.category === "skill" && proposal.value.name === "python",
  );

  review = cvr.applyReviewAction(
    review,
    { kind: "approve", proposalId: target.id },
    { adapter: cvp },
  ).state;
  let view = model(profile, review);
  assert.equal(proposalById(view, target.id).status, "approved");

  const edited = cvr.applyReviewAction(
    review,
    { kind: "edit", proposalId: target.id, value: { name: "java" } },
    { adapter: cvp },
  );
  assert.equal(edited.applied, true);
  assert.equal(edited.supported, false, "java is not quoted by the evidence");
  assert.notEqual(edited.revisionId, target.id);

  view = model(profile, edited.state);
  const original = proposalById(view, target.id);
  const revision = proposalById(view, edited.revisionId);

  assert.equal(original.status, "superseded");
  assert.equal(original.isApproved, false);
  assert.equal(revision.status, "proposed");
  assert.equal(revision.revisionOf, target.id);
  assert.equal(revision.evidence.length, 0, "no quotation supports the new value");
  assert.equal(revision.canApprove, false);
  assert.match(revision.approveReason, /without evidence/);

  // The history keeps the approval and the edit, and the approval is revoked.
  assert.deepEqual(
    view.history.map((event) => event.kind),
    ["approve", "edit"],
  );
  assert.equal(view.counts.approved, 0);
  assert.equal(view.counts.superseded, 1);
  assert.equal(view.counts.proposed, profile.proposals.length);
});

test("an edit that is still quoted keeps its evidence and can be approved", () => {
  const { profile } = preview();
  const review = state(profile);
  const target = profile.proposals.find(
    (proposal) => proposal.category === "skill" && proposal.value.name === "python",
  );

  const edited = cvr.applyReviewAction(
    review,
    { kind: "edit", proposalId: target.id, value: { name: "Python" } },
    { adapter: cvp },
  );
  assert.equal(edited.applied, true);
  assert.equal(edited.supported, true);

  const view = model(profile, edited.state);
  const revision = proposalById(view, edited.revisionId);
  assert.equal(revision.evidence.length, 2);
  assert.equal(revision.canApprove, true);
});

test("an education revision needs the degree and the subject in the quotation", () => {
  const { profile } = preview();
  const review = state(profile);
  const target = profile.proposals.find(
    (proposal) =>
      proposal.category === "education" && proposal.value.level === "bachelor",
  );

  const good = cvr.applyReviewAction(
    review,
    {
      kind: "edit",
      proposalId: target.id,
      value: { level: "bachelor", field: "computer science" },
    },
    { adapter: cvp },
  );
  assert.equal(good.supported, true);

  const bad = cvr.applyReviewAction(
    review,
    {
      kind: "edit",
      proposalId: target.id,
      value: { level: "master", field: "computer science" },
    },
    { adapter: cvp },
  );
  assert.equal(bad.supported, false);

  const other = cvr.applyReviewAction(
    review,
    {
      kind: "edit",
      proposalId: target.id,
      value: { level: "bachelor", field: "robotics" },
    },
    { adapter: cvp },
  );
  assert.equal(other.supported, false);
});

test("a revision keeps the conflicts of the engine empty, like the reducer does", () => {
  const { profile } = preview();
  const review = state(profile);
  const conflict = profile.conflicts[0];
  const target = conflict.proposalIds[0];

  const edited = cvr.applyReviewAction(
    review,
    { kind: "edit", proposalId: target, value: { language: "english", stated_level: "c1" } },
    { adapter: cvp },
  );
  assert.equal(edited.applied, true);

  const view = model(profile, edited.state);
  const revision = proposalById(view, edited.revisionId);
  assert.deepEqual(revision.conflicts, []);
  assert.deepEqual(revision.conflictIds, []);
});

test("rejecting keeps the proposal in the state and can be undone by approving", () => {
  const { profile } = preview();
  let review = state(profile);
  const target = profile.proposals.find(
    (proposal) => proposal.category === "skill" && proposal.value.name === "sql",
  );

  review = cvr.applyReviewAction(
    review,
    { kind: "reject", proposalId: target.id },
    { adapter: cvp },
  ).state;
  let view = model(profile, review);
  assert.equal(proposalById(view, target.id).status, "rejected");
  assert.equal(view.counts.rejected, 1);
  assert.equal(view.counts.total, profile.proposals.length);

  review = cvr.applyReviewAction(
    review,
    { kind: "approve", proposalId: target.id },
    { adapter: cvp },
  ).state;
  view = model(profile, review);
  assert.equal(proposalById(view, target.id).status, "approved");
  assert.equal(view.counts.approved, 1);
  assert.deepEqual(
    view.history.map((event) => event.kind),
    ["reject", "approve"],
  );
});

test("a superseded revision cannot be approved or edited again", () => {
  const { profile } = preview();
  let review = state(profile);
  const target = profile.proposals.find(
    (proposal) => proposal.category === "skill" && proposal.value.name === "python",
  );

  review = cvr.applyReviewAction(
    review,
    { kind: "edit", proposalId: target.id, value: { name: "Java" } },
    { adapter: cvp },
  ).state;

  const approve = cvr.applyReviewAction(
    review,
    { kind: "approve", proposalId: target.id },
    { adapter: cvp },
  );
  assert.equal(approve.applied, false);
  assert.match(approve.reason, /superseded/);

  const edit = cvr.applyReviewAction(
    review,
    { kind: "edit", proposalId: target.id, value: { name: "Rust" } },
    { adapter: cvp },
  );
  assert.equal(edit.applied, false);
  assert.match(edit.reason, /superseded/);
});

test("the profile request carries the transport response of the extraction", async () => {
  const calls = [];
  const adapter = new cvp.CvProfileAdapter({
    baseUrl: "/api/cv/",
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      return jsonResponse(fixture("profile-synthetic"));
    },
  });

  const job = {
    id: "job-1",
    status: "complete",
    parserStatus: "completed",
    schemaVersion: "1.1",
    transportVersion: "1.0",
    documentCount: 1,
    totalBytes: 12,
    statusCounts: {},
    limits: {},
    batchError: null,
    documents: [
      {
        id: "doc-1",
        index: 0,
        filename: "cv.pdf",
        format: "pdf",
        parserStatus: "extracted",
        status: "extracted",
        fullText: "Hello",
        segments: [
          { text: "Hello", locator: { kind: "page", page: 1, paragraph: null, section: null } },
        ],
        warnings: [],
        metadata: { size_bytes: 5, page_count: 1, paragraph_count: null },
      },
    ],
  };

  const profile = await adapter.createProfile(job);

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/cv/profiles");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.headers["Content-Type"], "application/json");
  assert.equal(calls[0].options.headers["X-JobLens-Request"], "1");

  const body = JSON.parse(calls[0].options.body);
  assert.deepEqual(Object.keys(body).sort(), ["documents", "job_id"]);
  assert.equal(body.job_id, "job-1");
  assert.equal(body.documents.length, 1);
  assert.equal(body.documents[0].document_id, "doc-1");
  assert.equal(body.documents[0].segments[0].text, "Hello");
  assert.equal(body.documents[0].status, "extracted");
  assert.equal(profile.counts.total, fixture("profile-synthetic").proposals.length);
});

test("the request body has exactly the two top-level keys the endpoint accepts", () => {
  const job = {
    id: "job-1",
    documents: [
      {
        id: "doc-1",
        index: 0,
        filename: "cv.pdf",
        format: "pdf",
        parserStatus: "extracted",
        segments: [
          { text: "Hello", locator: { kind: "page", page: 1, paragraph: null, section: null } },
        ],
      },
    ],
  };

  const body = cvp.buildProfileRequest(job);

  // The endpoint refuses anything else with HTTP 400 invalid_request.
  assert.deepEqual(Object.keys(body), ["job_id", "documents"]);
  for (const key of ["transport_version", "schema_version", "batch", "status_counts", "limits"]) {
    assert.equal(key in body, false, key);
  }
  assert.deepEqual(Object.keys(body.documents[0]).sort(), [
    "document_id",
    "filename",
    "format",
    "index",
    "segments",
    "status",
  ]);
  assert.deepEqual(Object.keys(body.documents[0].segments[0]).sort(), ["locator", "text"]);
});

test("the request keeps the document identity, the segment order and the exact text", () => {
  const source = fixture("profile-preview-source");
  const job = {
    id: source.job_id,
    documents: source.documents.map((document) => ({
      id: document.document_id,
      index: document.index,
      filename: document.filename,
      format: document.format,
      parserStatus: document.status,
      segments: document.segments.map((segment) => ({
        text: segment.text,
        locator: segment.locator,
      })),
    })),
  };

  const body = cvp.buildProfileRequest(job);

  assert.equal(body.job_id, source.job_id);
  assert.equal(body.documents.length, source.documents.length);

  body.documents.forEach((document, position) => {
    const original = source.documents[position];
    assert.equal(document.document_id, original.document_id);
    assert.equal(document.index, position);
    assert.equal(document.filename, original.filename);
    assert.equal(document.status, original.status);
    assert.equal(document.format, original.format);
    assert.equal(document.segments.length, original.segments.length);

    document.segments.forEach((segment, segmentIndex) => {
      const originalSegment = original.segments[segmentIndex];
      assert.equal(segment.text, originalSegment.text);
      assert.deepEqual(segment.locator, originalSegment.locator);
    });
  });

  // The text is passed through untouched, including characters outside the
  // basic multilingual plane.
  const withEmoji = body.documents[0].segments[0].text;
  assert.equal(withEmoji, source.documents[0].segments[0].text);
  assert.ok([...withEmoji].some((character) => character.codePointAt(0) > 0xffff));
});

test("an incomplete or invalid extraction never reaches the endpoint", async () => {
  let fetchCalls = 0;
  const adapter = new cvp.CvProfileAdapter({
    fetchImpl: async () => {
      fetchCalls += 1;
      return jsonResponse(fixture("profile-synthetic"));
    },
  });

  // No documents at all.
  await assert.rejects(adapter.createProfile({ id: "job-1", documents: [] }), (error) => {
    assert.equal(error.code, "no_source");
    return true;
  });
  await assert.rejects(adapter.createProfile(null), (error) => {
    assert.equal(error.code, "no_source");
    return true;
  });

  // A document without the identifier the parser gave it.
  await assert.rejects(
    adapter.createProfile({
      id: "job-1",
      documents: [{ index: 0, filename: "cv.pdf", format: "pdf", segments: [] }],
    }),
    (error) => {
      assert.equal(error.code, "invalid_source");
      return true;
    },
  );

  // A document whose index does not match its position.
  await assert.rejects(
    adapter.createProfile({
      id: "job-1",
      documents: [
        {
          id: "doc-1",
          index: 3,
          filename: "cv.pdf",
          format: "pdf",
          segments: [],
        },
      ],
    }),
    (error) => {
      assert.equal(error.code, "invalid_source");
      return true;
    },
  );

  // A block without a locator or without its text.
  await assert.rejects(
    adapter.createProfile({
      id: "job-1",
      documents: [
        {
          id: "doc-1",
          index: 0,
          filename: "cv.pdf",
          format: "pdf",
          segments: [{ text: "Hello" }],
        },
      ],
    }),
    (error) => {
      assert.equal(error.code, "invalid_source");
      return true;
    },
  );

  assert.equal(fetchCalls, 0);
});

test("a profile request without an extraction never reaches the network", async () => {
  let fetchCalls = 0;
  const adapter = new cvp.CvProfileAdapter({
    fetchImpl: async () => {
      fetchCalls += 1;
      return jsonResponse(fixture("profile-synthetic"));
    },
  });

  await assert.rejects(adapter.createProfile(null), (error) => {
    assert.equal(error.code, "no_source");
    return true;
  });
  assert.equal(fetchCalls, 0);
});

test("a missing profile endpoint surfaces as an honest HTTP error", async () => {
  const adapter = new cvp.CvProfileAdapter({
    fetchImpl: async () =>
      jsonResponse({ error: { code: "not_found", message: "No such endpoint." } }, 404),
  });

  await assert.rejects(
    adapter.createProfile({
      id: "job-1",
      documents: [
        {
          id: "doc-1",
          index: 0,
          filename: "cv.pdf",
          format: "pdf",
          parserStatus: "extracted",
          segments: [{ text: "Hello", locator: { kind: "page", page: 1 } }],
        },
      ],
    }),
    (error) => {
      assert.equal(error.name, "CvProfileHttpError");
      assert.equal(error.status, 404);
      assert.equal(error.details.code, "not_found");
      return true;
    },
  );
});

test("the workspace markup keeps the profile view accessible", () => {
  const html = readFileSync(join(WORKSPACE, "index.html"), "utf8");

  assert.match(html, /role="tablist"/);
  assert.match(html, /role="tab"[\s\S]{0,200}aria-selected="true"/);
  assert.match(html, /role="tabpanel" aria-labelledby="view-extraction"/);
  assert.match(html, /role="tabpanel" aria-labelledby="view-profile"/);
  assert.match(html, /aria-controls="profile-view"/);

  assert.match(html, /id="profile-status"[^>]*role="status"/);
  assert.match(html, /id="profile-status"[^>]*aria-live="polite"/);

  assert.match(html, /src="\.\/api-adapter\.js"/);
  assert.match(html, /src="\.\/profile-adapter\.js"/);
  assert.match(html, /src="\.\/profile-review\.js"/);

  assert.match(html, /Load synthetic sample/);
  assert.match(html, /id="profile-conflicts"/);
  assert.match(html, /id="profile-history"/);
});
