import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const product = require("../../web/simple.js");
const html = readFileSync(new URL("../../web/simple.html", import.meta.url), "utf8");
const css = readFileSync(new URL("../../web/simple.css", import.meta.url), "utf8");

function draftFixture() {
  return {
    cv_draft_version: "0.1",
    target_job: { title: "Senior Data Engineer", company: "Northwind Analytics" },
    candidate: {
      full_name: "",
      email: null,
      phone: null,
      location: null,
      links: [],
    },
    sections: [
      {
        section_id: "summary",
        kind: "summary",
        title: "Professional Summary",
        items: [
          {
            item_id: "i1",
            text: "Data engineer using Python and SQL.",
            approved_fact_ids: ["f1"],
            review_status: "needs_review",
          },
        ],
      },
      {
        section_id: "skills",
        kind: "skills",
        title: "Skills",
        items: [
          {
            item_id: "i2",
            text: "Python",
            approved_fact_ids: ["f1", "f2"],
            review_status: "needs_review",
          },
          {
            item_id: "i3",
            text: "SQL",
            approved_fact_ids: ["f2"],
            review_status: "needs_review",
          },
        ],
      },
    ],
    warnings: [
      "Candidate full name is missing and must be supplied by the user.",
      "No candidate contact method is available.",
      "One detail was omitted.",
    ],
    unmet_requirements: ["terraform", "5+ years of professional experience."],
    omitted_count: 2,
    review: {
      baseline: {
        evidence: {
          f1: [{ quote: "Python and SQL" }, { quote: "Python and SQL" }],
          f2: [{ quote: "SQL" }],
        },
      },
      approvals: {},
      receipt: "baseline-receipt",
      session_id: "session",
    },
  };
}

test("empty and malformed inputs are rejected with actionable copy", () => {
  assert.equal(product.validateFiles([]).ok, false);
  assert.match(product.validateFiles([]).error, /at least one/i);
  assert.equal(product.validateFiles([{ name: "cv.txt", size: 10 }]).ok, false);
  assert.match(product.validateFiles([{ name: "cv.txt", size: 10 }]).error, /PDF or DOCX/);
  assert.equal(
    product.validateFiles(
      Array.from({ length: 6 }, (_, i) => ({ name: `cv-${i}.pdf`, size: 10 })),
    ).ok,
    false,
  );
  assert.equal(
    product.validateFiles([{ name: "huge.pdf", size: product.MAX_TOTAL_BYTES + 1 }]).ok,
    false,
  );

  assert.equal(product.validatePosting("").ok, false);
  assert.equal(product.validatePosting("   ").ok, false);
  assert.equal(product.validatePosting("x".repeat(product.MIN_JOB_LENGTH - 1)).ok, false);
  assert.equal(product.validatePosting("x".repeat(product.MIN_JOB_LENGTH)).ok, true);
  assert.equal(product.validatePosting("x".repeat(product.MAX_JOB_LENGTH)).ok, true);
  assert.equal(product.validatePosting("x".repeat(product.MAX_JOB_LENGTH + 1)).ok, false);
});

test("upload validation accepts both PDF and DOCX, by extension or declared MIME", () => {
  const pdf = { name: "cv.pdf", size: 1000, type: product.PDF_MIME };
  const docx = {
    name: "cv.docx",
    size: 1000,
    type: product.DOCX_MIME,
  };
  const byMime = { name: "cv", size: 1000, type: product.PDF_MIME };
  assert.equal(product.validateFiles([pdf]).ok, true);
  assert.equal(product.validateFiles([pdf, docx]).ok, true);
  assert.equal(product.validateFiles([byMime]).ok, true);
  assert.equal(product.fileKind(pdf), "pdf");
  assert.equal(product.fileKind(docx), "docx");
  assert.equal(product.fileKind({ name: "cv.rtf", type: "text/rtf" }), null);
});

test("file additions append, deduplicate, and preserve the current selection on rejection", () => {
  const a = {
    name: "A.pdf",
    size: 1000,
    type: product.PDF_MIME,
    lastModified: 1,
  };
  const b = {
    name: "B.docx",
    size: 1000,
    type: product.DOCX_MIME,
    lastModified: 2,
  };
  const c = {
    name: "C.pdf",
    size: 1000,
    type: product.PDF_MIME,
    lastModified: 3,
  };

  const two = product.mergeFileSelection([], [a, b]);
  assert.equal(two.ok, true);
  assert.deepEqual(two.files.map((file) => file.name), ["A.pdf", "B.docx"]);

  const sequential = product.mergeFileSelection([a], [b]);
  assert.equal(sequential.ok, true);
  assert.equal(sequential.added, 1);
  assert.deepEqual(sequential.files.map((file) => file.name), ["A.pdf", "B.docx"]);

  const duplicate = product.mergeFileSelection([a, b], [{ ...a }]);
  assert.equal(duplicate.ok, true);
  assert.equal(duplicate.added, 0);
  assert.equal(duplicate.duplicates, 1);
  assert.equal(duplicate.files.length, 2);

  const mixed = product.mergeFileSelection([a, b], [{ ...a }, c]);
  assert.equal(mixed.ok, true);
  assert.equal(mixed.added, 1);
  assert.equal(mixed.duplicates, 1);
  assert.deepEqual(mixed.files.map((file) => file.name), ["A.pdf", "B.docx", "C.pdf"]);

  const five = [a, b, c, { ...a, name: "D.pdf" }, { ...b, name: "E.pdf" }];
  const tooMany = product.mergeFileSelection(five, [
    { ...c, name: "F.pdf" },
  ]);
  assert.equal(tooMany.ok, false);
  assert.match(tooMany.error, /five/i);

  const invalid = product.mergeFileSelection([a], [
    { name: "notes.txt", size: 10, type: "text/plain" },
  ]);
  assert.equal(invalid.ok, false);
  assert.match(invalid.error, /PDF or DOCX/);
  assert.equal([a].length, 1, "the existing selection is not mutated on rejection");

  const oversized = product.mergeFileSelection([a], [
    { name: "huge.pdf", size: product.MAX_FILE_BYTES + 1, type: product.PDF_MIME },
  ]);
  assert.equal(oversized.ok, false);
  assert.match(oversized.error, /larger than 10 MB/);

  const totalTooLarge = product.validateFiles(
    [a, b, c].map((file) => ({ ...file, size: 9 * 1024 * 1024 })),
  );
  assert.equal(totalTooLarge.ok, false);
  assert.match(totalTooLarge.error, /25 MB/);
});

test("generate is enabled only with a read source and a valid posting", () => {
  const jobText = "x".repeat(product.MIN_JOB_LENGTH);
  assert.equal(product.canGenerate({ source: null, jobText, busy: false }), false);
  assert.equal(product.canGenerate({ source: {}, jobText: "short", busy: false }), false);
  assert.equal(product.canGenerate({ source: {}, jobText, busy: true }), false);
  assert.equal(product.canGenerate({ source: {}, jobText, busy: false }), true);
});

test("confirmation requires a full name, non-empty lines and an explicit check", () => {
  const draft = draftFixture();
  const base = { draft, checked: true, busy: false };
  assert.equal(product.canConfirm(base), false, "name is required");
  assert.equal(product.hasFullName(draft), false);
  draft.candidate.full_name = "Alex Rivera";
  assert.equal(product.canConfirm(base), true);
  assert.equal(product.canConfirm({ ...base, checked: false }), false);
  assert.equal(product.canConfirm({ ...base, busy: true }), false);
  draft.sections[0].items[0].text = "  ";
  assert.equal(product.canConfirm(base), false, "empty wording is not confirmable");
});

test("download readiness requires a server receipt, every item approved and a name", () => {
  const draft = draftFixture();
  draft.candidate.full_name = "Alex Rivera";
  for (const section of draft.sections) {
    for (const item of section.items) item.review_status = "approved";
  }
  const ready = {
    draft,
    confirmed: true,
    receipt: "final-receipt",
    busy: false,
  };
  assert.equal(product.canDownload(ready), true);
  assert.equal(product.canDownload({ ...ready, confirmed: false }), false);
  assert.equal(product.canDownload({ ...ready, receipt: null }), false);
  assert.equal(product.canDownload({ ...ready, busy: true }), false);
  draft.sections[0].items[0].review_status = "needs_review";
  assert.equal(product.canDownload(ready), false, "an edited line needs review again");
});

test("editing invalidates the previous final confirmation", () => {
  const draft = draftFixture();
  draft.candidate.full_name = "Alex Rivera";
  for (const section of draft.sections) {
    for (const item of section.items) item.review_status = "approved";
  }
  const state = {
    draft,
    confirmed: true,
    receipt: "final-receipt",
    busy: false,
  };
  assert.equal(product.canDownload(state), true);
  // This is exactly what the controller does on a change.
  state.confirmed = false;
  state.receipt = null;
  delete draft.review.final_receipt;
  draft.sections[0].items[0].text += " Edited.";
  draft.sections[0].items[0].review_status = "needs_review";
  assert.equal(product.canDownload(state), false);
});

test("items and sections can be reordered and removed without losing content", () => {
  const draft = draftFixture();
  const skills = draft.sections[1];
  assert.equal(product.moveItem(draft.sections, 1, 0, 1), true);
  assert.deepEqual(
    skills.items.map((item) => item.text),
    ["SQL", "Python"],
  );
  assert.equal(product.moveItem(draft.sections, 1, 0, -1), false);
  assert.equal(product.moveItem(draft.sections, 1, 1, 1), false);
  assert.equal(product.moveSection(draft.sections, 0, 1), true);
  assert.deepEqual(
    draft.sections.map((section) => section.title),
    ["Skills", "Professional Summary"],
  );
  assert.equal(product.moveSection(draft.sections, 0, -1), false);

  const removed = product.removeItem(draft.sections, 0, 0);
  assert.equal(removed.text, "SQL");
  assert.equal(draft.sections[0].items.length, 1);
  product.removeItem(draft.sections, 0, 0);
  assert.equal(draft.sections.some((section) => section.kind === "skills"), false);
});

test("source wording is real backend evidence, deduplicated, and never invented", () => {
  const draft = draftFixture();
  const summary = draft.sections[0].items[0];
  assert.deepEqual(product.sourceQuotes(draft, summary), ["Python and SQL"]);
  assert.deepEqual(product.sourceQuotes(draft, { approved_fact_ids: ["missing"] }), []);
  assert.equal(product.itemMode(draft, summary), null);
  draft.review.approvals.i1 = { mode: "candidate_attested" };
  assert.equal(product.itemMode(draft, summary), "candidate_attested");
});

test("why-this-content notes only surface real backend data", () => {
  const draft = draftFixture();
  const notes = product.reviewNotes(draft);
  assert.equal(notes.omitted, 2);
  assert.deepEqual(notes.unmet, [
    "terraform",
    "5+ years of professional experience.",
  ]);
  assert.deepEqual(notes.warnings, ["One detail was omitted."]);
  assert.equal(notes.sourceLines, 3);
  assert.deepEqual(product.reviewNotes(null), {
    omitted: 0,
    unmet: [],
    warnings: [],
    sourceLines: 0,
  });
});

test("supported contacts are prefilled as editable provisional values", () => {
  const draft = draftFixture();
  draft.candidate = {
    full_name: null,
    email: null,
    phone: null,
    location: null,
    links: [],
  };
  draft.contact_suggestions = {
    contact_suggestions_version: "0.1",
    suggestions: [
      { field: "full_name", status: "supported", selected: "Alex Rivera", values: [] },
      { field: "email", status: "supported", selected: "alex@example.com", values: [] },
      { field: "phone", status: "supported", selected: "(555) 010-0000", values: [] },
      { field: "location", status: "supported", selected: "Madrid, Spain", values: [] },
      { field: "github", status: "supported", selected: "github.com/alex", values: [] },
      { field: "linkedin", status: "supported", selected: "linkedin" + ".com/in/alex", values: [] },
      { field: "website", status: "supported", selected: "alex.example.test", values: [] },
    ],
  };
  const applied = product.applyContactPrefill(draft);
  assert.deepEqual([...applied].sort(), [
    "email",
    "full_name",
    "github",
    "linkedin",
    "location",
    "phone",
    "website",
  ]);
  assert.equal(draft.candidate.full_name, "Alex Rivera");
  assert.equal(draft.candidate.email, "alex@example.com");
  assert.equal(draft.candidate.phone, "(555) 010-0000");
  assert.equal(draft.candidate.location, "Madrid, Spain");
  assert.deepEqual(draft.candidate.links, [
    "github.com/alex",
    "linkedin" + ".com/in/alex",
    "alex.example.test",
  ]);
  // A second call never overwrites the candidate's own edits.
  assert.equal(product.applyContactPrefill(draft).size, 0);
});

test("conflicting contacts are never selected and existing values are preserved", () => {
  const draft = draftFixture();
  draft.candidate = {
    full_name: "Casey Nguyen",
    email: "existing@example.com",
    phone: null,
    location: null,
    links: ["github.com/existing"],
  };
  draft.contact_suggestions = {
    contact_suggestions_version: "0.1",
    suggestions: [
      {
        field: "email",
        status: "conflict",
        selected: null,
        values: [
          { value: "one@example.com", evidence: [] },
          { value: "two@example.com", evidence: [] },
        ],
      },
      { field: "phone", status: "supported", selected: "(555) 010-0000", values: [] },
      { field: "github", status: "supported", selected: "github.com/other", values: [] },
    ],
  };
  const applied = product.applyContactPrefill(draft);
  assert.deepEqual([...applied], ["phone"]);
  assert.equal(draft.candidate.email, "existing@example.com");
  assert.deepEqual(draft.candidate.links, ["github.com/existing"]);
  const detail = product.contactSuggestionDetail(draft, "email");
  assert.equal(detail.status, "conflict");
  assert.equal(detail.selected, "");
  assert.deepEqual(
    detail.values.map((item) => item.value),
    ["one@example.com", "two@example.com"],
  );
});

test("decision explanations come only from the backend report", () => {
  const draft = draftFixture();
  assert.equal(product.decisionReport(draft), null);
  draft.decision_report = {
    decision_report_version: "0.1",
    counts: { included: 1, omitted: 1, insufficient: 0 },
    decisions: [
      {
        outcome: "included",
        label: "Python",
        explanation: "Python was included because it supports the essential job requirement “Python”.",
        supports: ["Python"],
        alternatives: [],
        documents: ["fictional.pdf"],
      },
      {
        outcome: "omitted",
        label: "English",
        explanation: "English was left out because the source documents disagree about it.",
        supports: [],
        alternatives: ["English (C1)", "English (B2)"],
        documents: ["fictional.pdf"],
      },
      { outcome: "included", label: "", explanation: "", supports: [] },
    ],
    unmet_requirements: [
      { requirement: "Kubernetes", explanation: "No approved fact supports this job requirement." },
    ],
  };
  const report = product.decisionReport(draft);
  assert.equal(report.decisions.length, 2);
  assert.deepEqual(report.counts, { included: 1, omitted: 1, insufficient: 0 });
  assert.deepEqual(report.decisions[0].supports, ["Python"]);
  assert.deepEqual(report.decisions[1].alternatives, ["English (C1)", "English (B2)"]);
  assert.deepEqual(report.unmet.map((item) => item.requirement), ["Kubernetes"]);
});

test("contact and filename helpers stay deterministic", () => {
  assert.deepEqual(
    product.contactParts({
      location: "Madrid",
      email: "a@example.com",
      phone: "555 0100",
      links: ["github.com/alex", " "],
    }),
    ["Madrid", "a@example.com", "555 0100", "github.com/alex"],
  );
  assert.equal(product.formatBytes(900), "900 B");
  assert.equal(product.formatBytes(2048), "2 KB");
  assert.equal(product.formatBytes(2 * 1024 * 1024), "2.0 MB");
  assert.equal(
    product.fileNameFor("pdf", { candidate: { full_name: "Alex Rivera" } }),
    "joblens-alex-rivera.pdf",
  );
  assert.equal(
    product.fileNameFor("docx", { candidate: { full_name: "" } }),
    "joblens-cv.docx",
  );
  assert.equal(
    product.targetLabel({ target_job: { title: "Data Engineer", company: "Northwind" } }),
    "Data Engineer · Northwind",
  );
});

test("the two-screen page keeps the required controls and accessibility hooks", () => {
  for (const id of [
    "create",
    "review",
    "create-title",
    "review-title",
    "drop",
    "files",
    "files-list",
    "file-error",
    "job",
    "job-title",
    "job-company",
    "job-location",
    "job-error",
    "generate",
    "sample",
    "status",
    "preview",
    "review-progress",
    "notes",
    "editor",
    "accuracy",
    "confirm",
    "confirm-status",
    "review-status",
    "pdf",
    "docx",
    "download-note",
    "start-over",
  ]) {
    assert.match(
      html,
      new RegExp(`id="${id}"`),
      `missing #${id}`,
    );
  }
  assert.match(html, /Generate my CV/);
  assert.match(html, /Try a sample/);
  assert.match(html, /Your experience\./);
  assert.match(html, /\/simple\.js/);
  assert.match(html, /class="skip-link"/);
  assert.match(html, /aria-live="polite"/);
  assert.match(html, /role="alert"/);
  assert.match(html, /for="job"/);
  assert.match(html, /for="files"/);
  assert.match(html, /aria-describedby="files-hint file-error"/);
  assert.equal(/<script(?![^>]*\bsrc=)/i.test(html), false, "no inline scripts");
  assert.equal(/\son[a-z]+\s*=/i.test(html), false, "no inline handlers");
});

test("the stylesheet defines the 65/35 review grid, mobile stacking and focus states", () => {
  assert.match(
    css,
    /grid-template-columns:\s*minmax\(0,\s*1\.95fr\)\s+minmax\(320px,\s*1fr\)/,
  );
  assert.match(css, /@media \(max-width: 980px\)/);
  assert.match(css, /\.review-layout\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s);
  assert.match(css, /overflow-wrap:\s*anywhere/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /\.dropzone:focus-within/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /\.downloads\s*\{[^}]*display:\s*grid/s);
  assert.match(css, /@media \(max-width: 430px\)/);
});

test("skip link focuses main without overriding native scrolling or Tab order", () => {
  assert.match(html, /<main id="main" tabindex="-1">/);
  let focused = false;
  product.focusMain({ getElementById(id) {
    assert.equal(id, "main");
    return { focus(options) { assert.deepEqual(options, { preventScroll: true }); focused = true; } };
  } });
  assert.equal(focused, true);
});
