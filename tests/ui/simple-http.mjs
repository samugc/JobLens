import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const cv = require("../../web/workspace/api-adapter.js");
const pa = require("../../web/workspace/profile-adapter.js");
const product = require("../../web/simple.js");

const [origin, pdfPath, docxPath] = process.argv.slice(2);
assert.ok(origin && pdfPath && docxPath, "usage: simple-http.mjs <origin> <pdf> <docx>");

const transport = (url, options = {}) => {
  assert.equal(new URL(url).origin, origin);
  return fetch(url, {
    ...options,
    headers: { ...(options.headers || {}), Origin: origin },
  });
};

const api = new cv.CvApiAdapter({
  baseUrl: origin + "/api/cv",
  fetchImpl: transport,
});

async function jsonPost(route, payload) {
  const response = await transport(origin + "/api/cv/" + route, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-JobLens-Request": "1",
    },
    body: JSON.stringify(payload),
  });
  const text = await response.text();
  let body = {};
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = {};
  }
  return { response, body };
}

async function binaryPost(route, payload) {
  return transport(origin + "/api/cv/" + route, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-JobLens-Request": "1",
    },
    body: JSON.stringify(payload),
  });
}

/* ------------------------------------------------------------------ HTTP */

const batch = await api.createExtraction([
  new File([readFileSync(pdfPath)], "alex-rivera-cv.pdf", {
    type: "application/pdf",
  }),
  new File([readFileSync(docxPath)], "alex-rivera-cv-2.docx", {
    type: product.DOCX_MIME,
  }),
]);
assert.equal(batch.documents.length, 2);
const source = pa.buildProfileRequest(batch);

let { response, body } = await jsonPost("draft", {
  source,
  text: product.SAMPLE_JOB,
});
assert.equal(response.status, 200, JSON.stringify(body));
let draft = body.draft;
assert.ok(draft.sections.length > 0, "the real pipeline returns content");
assert.equal(draft.review.baseline.review_mode, "provisional");
assert.ok(Object.keys(draft.review.baseline.evidence || {}).length > 0);
assert.ok(Array.isArray(draft.unmet_requirements));
assert.ok(draft.unmet_requirements.includes("terraform"));
assert.equal(typeof body.draft.omitted_count, "number");

draft.candidate.full_name = "Alex Rivera";
draft.candidate.email = "alex.rivera@example.com";
draft.candidate.location = "Madrid, Spain";
({ response, body } = await jsonPost("confirm", {
  draft,
  confirmed: true,
  attested: true,
}));
assert.equal(response.status, 200, JSON.stringify(body));
draft = body.draft;
assert.ok(draft.review.final_receipt, "the server issues a final receipt");
assert.ok(
  draft.sections.every((section) =>
    section.items.every((item) => item.review_status === "approved"),
  ),
);

for (const [kind, magic] of [
  ["pdf", "%PDF"],
  ["docx", "PK"],
]) {
  const download = await binaryPost("cv-drafts/export/" + kind, {
    draft,
    confirmed: true,
    contact: draft.candidate,
  });
  assert.equal(download.status, 200);
  const bytes = Buffer.from(await download.arrayBuffer());
  assert.equal(bytes.subarray(0, magic.length).toString(), magic);
  assert.ok(bytes.length > 500);
}

// Editing after confirmation must make the old final receipt stale.
const item = draft.sections[0].items[0];
({ response, body } = await jsonPost("cv-drafts/edit", {
  draft,
  item_id: item.item_id,
  text: item.text + " Edited after confirmation.",
}));
assert.equal(response.status, 200, JSON.stringify(body));
const edited = body.draft;
assert.equal(
  edited.sections
    .flatMap((section) => section.items)
    .find((entry) => entry.item_id === item.item_id).review_status,
  "needs_review",
);

const stale = await binaryPost("cv-drafts/export/pdf", {
  draft: edited,
  confirmed: true,
  contact: edited.candidate,
});
assert.equal(stale.status, 400, "a stale receipt cannot export");
const staleBody = await stale.json();
assert.match(staleBody.error || "", /confirm the current version|changed/i);

// Re-confirmation makes the edited draft downloadable again.
({ response, body } = await jsonPost("confirm", {
  draft: edited,
  confirmed: true,
  attested: true,
}));
assert.equal(response.status, 200, JSON.stringify(body));
const reConfirmed = body.draft;
const fresh = await binaryPost("cv-drafts/export/docx", {
  draft: reConfirmed,
  confirmed: true,
  contact: reConfirmed.candidate,
});
assert.equal(fresh.status, 200);

// Missing contact information is rejected by the backend, not only the UI.
const noName = JSON.parse(JSON.stringify(draft));
noName.candidate.full_name = "";
({ response, body } = await jsonPost("confirm", {
  draft: noName,
  confirmed: true,
  attested: true,
}));
assert.equal(response.status, 400);
assert.equal(body.code, "missing_contact");

console.log("Real server: upload → provisional draft → confirm → PDF/DOCX → edit invalidation → re-confirm passed");

/* --------------------------------------------------------- controller DOM */

class TextNode {
  constructor(text) {
    this.textContent = text;
    this.children = [];
    this.parent = null;
  }
}

class Element {
  constructor(tag = "div") {
    this.tag = tag;
    this.id = "";
    this.className = "";
    this.textContent = "";
    this.children = [];
    this.parent = null;
    this.events = {};
    this.attributes = {};
    this.value = "";
    this.checked = false;
    this.disabled = false;
    this.hidden = false;
    this.files = [];
    this.type = "";
    this.title = "";
    this.href = "";
    this.download = "";
    this.focused = false;
  }

  addEventListener(name, fn) {
    (this.events[name] = this.events[name] || []).push(fn);
  }

  append(...nodes) {
    for (const node of nodes) {
      if (!node) continue;
      if (node.parent) node.parent.removeChild(node);
      node.parent = this;
      this.children.push(node);
    }
  }

  replaceChildren(...nodes) {
    for (const child of this.children) child.parent = null;
    this.children = [];
    this.append(...nodes);
  }

  removeChild(node) {
    const index = this.children.indexOf(node);
    if (index >= 0) this.children.splice(index, 1);
    if (node) node.parent = null;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  getAttribute(name) {
    return this.attributes[name];
  }

  remove() {
    if (this.parent) this.parent.removeChild(this);
  }

  click() {
    this.fire("click", { target: this, preventDefault() {} });
  }

  focus() {
    this.focused = true;
  }

  fire(name, event) {
    const handlers = this.events[name] || [];
    for (const handler of handlers) {
      handler(event || { target: this, preventDefault() {} });
    }
  }
}

function walk(node, visit) {
  if (!node) return;
  visit(node);
  for (const child of node.children || []) walk(child, visit);
}

function collect(node, predicate, out = []) {
  if (!node) return out;
  if (predicate(node)) out.push(node);
  for (const child of node.children || []) collect(child, predicate, out);
  return out;
}

function hasClass(node, name) {
  return String(node.className || "")
    .split(/\s+/)
    .filter(Boolean)
    .includes(name);
}

function waitFor(predicate, label, timeout = 20000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      try {
        if (predicate()) return resolve();
      } catch (error) {
        return reject(error);
      }
      if (Date.now() - started > timeout) {
        const status =
          nodes && nodes.status ? " (status: " + nodes.status.textContent + ")" : "";
        return reject(new Error("Timed out waiting for " + label + status));
      }
      setTimeout(tick, 25);
    };
    tick();
  });
}

const documentBody = new Element("body");
const ids = [
  "create",
  "review",
  "create-title",
  "review-title",
  "review-subtitle",
  "review-progress",
  "status",
  "drop",
  "files",
  "files-list",
  "file-count",
  "files-empty",
  "file-error",
  "job",
  "job-title",
  "job-company",
  "job-location",
  "job-count",
  "job-error",
  "generate",
  "generate-note",
  "sample",
  "preview",
  "notes",
  "editor",
  "accuracy",
  "confirm",
  "confirm-status",
  "download-note",
  "review-status",
  "pdf",
  "docx",
  "start-over",
];
const nodes = {};
for (const id of ids) {
  const node = new Element(id === "job" ? "textarea" : "div");
  node.id = id;
  nodes[id] = node;
  documentBody.append(node);
}
nodes.review.hidden = true;
nodes.accuracy.type = "checkbox";

const TestURL = class extends URL {};
TestURL.createObjectURL = () => "blob:joblens-test";
TestURL.revokeObjectURL = () => {};

const extractionCalls = [];
let extractionGate = null;

const CvApiAdapter = class extends cv.CvApiAdapter {
  constructor(options = {}) {
    super({ ...options, baseUrl: origin + "/api/cv", fetchImpl: transport });
  }

  createExtraction(files, options) {
    const list = Array.from(files || []);
    extractionCalls.push(list.map((file) => file.name));
    if (extractionGate) {
      const gate = extractionGate;
      extractionGate = null;
      return gate.then(() => super.createExtraction(files, options));
    }
    return super.createExtraction(files, options);
  }
};

const context = {
  document: {
    // Keep the module from auto-booting: this test starts the controller
    // explicitly so it can inspect the live state during async flows.
    readyState: "loading",
    body: documentBody,
    title: "",
    getElementById(id) {
      let found = null;
      walk(documentBody, (node) => {
        if (!found && node.id === id) found = node;
      });
      return found;
    },
    createElement(tag) {
      return new Element(tag);
    },
    createTextNode(text) {
      return new TextNode(text);
    },
    addEventListener() {},
  },
  window: { scrollTo() {} },
  JobLensCV: { ...cv, CvApiAdapter },
  JobLensProfileAdapter: pa,
  fetch(input, options) {
    const absolute = new URL(input, origin).href;
    return transport(absolute, options);
  },
  URL: TestURL,
  File,
  FormData,
  Blob,
  Headers,
  Request,
  Response,
  console,
  setTimeout(fn) {
    fn();
    return 0;
  },
  clearTimeout() {},
};
vm.createContext(context);
vm.runInContext(
  readFileSync(new URL("../../web/simple.js", import.meta.url), "utf8"),
  context,
);

const controller = context.JobLensProduct.init();
assert.ok(controller, "the controller starts");
assert.equal(nodes.review.hidden, true);
assert.equal(nodes.pdf.disabled, true);

// "Try a sample" must run the real sample files through the real pipeline.
nodes.sample.click();
await waitFor(() => nodes.review.hidden === false, "sample draft");
assert.match(nodes.status.textContent, /Draft ready/);
const paper = collect(nodes.preview, (node) => hasClass(node, "cv-paper"))[0];
assert.ok(paper, "the preview renders a paper");
assert.ok(
  collect(nodes.preview, (node) => hasClass(node, "cv-section")).length > 0,
  "the preview renders real sections",
);
assert.equal(nodes.accuracy.checked, false);

const nameInput = () => context.document.getElementById("candidate-full_name");
const emailInput = () => context.document.getElementById("candidate-email");
const locationInput = () => context.document.getElementById("candidate-location");
const githubInput = () => context.document.getElementById("candidate-github");
const linkedinInput = () => context.document.getElementById("candidate-linkedin");
const websiteInput = () => context.document.getElementById("candidate-website");
assert.ok(nameInput(), "contact fields are rendered");
assert.ok(githubInput() && linkedinInput() && websiteInput(), "link fields are rendered");
assert.equal(nameInput().value, "Alex Rivera", "the supported name is prefilled");
assert.equal(
  emailInput().value,
  "alex.rivera@example.test",
  "the supported e-mail is prefilled",
);
assert.equal(
  locationInput().value,
  "Madrid, Spain",
  "the supported location is prefilled",
);
assert.equal(controller.state.prefilledContacts.size, 3);
assert.equal(
  collect(nodes.preview, (node) => hasClass(node, "cv-name"))[0].textContent,
  "Alex Rivera",
  "the prefilled contact appears in the document preview",
);
nameInput().value = "Alex Rivera";
nameInput().fire("input");
assert.equal(
  collect(nodes.preview, (node) => hasClass(node, "cv-name"))[0].textContent,
  "Alex Rivera",
);

const decisionItems = collect(nodes.notes, (node) => hasClass(node, "decision"));
assert.ok(decisionItems.length > 0, "the real decision report is rendered");
assert.ok(
  collect(nodes.notes, (node) => hasClass(node, "decision-summary")).length > 0,
  "the decision summary is rendered",
);
const notesText = collect(nodes.notes, (node) => typeof node.textContent === "string")
  .map((node) => node.textContent)
  .join(" ");
assert.match(notesText, /actual generation decisions/);
const decisionText = collect(nodes.notes, (node) => hasClass(node, "decision-copy"))
  .map((node) => node.textContent)
  .join(" ");
assert.doesNotMatch(decisionText, /%|percent/i);

const entry = () => collect(nodes.editor, (node) => hasClass(node, "entry"))[0];
const entryText = () => collect(entry(), (node) => node.tag === "textarea")[0];
assert.ok(entryText(), "each line has a textarea");
entryText().value += " ";
entryText().fire("input");
assert.equal(nodes.pdf.disabled, true, "an edit relocks downloads");
assert.equal(nodes.accuracy.checked, false, "an edit clears the confirmation");

nodes.accuracy.checked = true;
nodes.confirm.click();
await waitFor(() => nodes.pdf.disabled === false, "confirmation");
assert.match(nodes.status.textContent, /confirmed/i);
assert.equal(nodes.accuracy.checked, true);

nodes.pdf.click();
await waitFor(() => /PDF download is ready/.test(nodes.status.textContent), "PDF download");
nodes.docx.click();
await waitFor(() => /DOCX download is ready/.test(nodes.status.textContent), "DOCX download");

// Changing contact details must invalidate the final confirmation again.
nameInput().value = "Alex Rivera Updated";
nameInput().fire("input");
assert.equal(nodes.pdf.disabled, true);
assert.equal(nodes.accuracy.checked, false);

// Re-confirm after the contact edit.
nodes.accuracy.checked = true;
nodes.confirm.click();
await waitFor(() => nodes.pdf.disabled === false, "re-confirmation");

// Structural edits also relock downloads.
const before = collect(nodes.editor, (node) => hasClass(node, "entry")).length;
const remove = collect(
  nodes.editor,
  (node) =>
    node.tag === "button" &&
    /^Remove this /.test(node.getAttribute("aria-label") || "") &&
    !node.disabled,
)[0];
assert.ok(remove, "a remove control is available");
remove.click();
assert.ok(
  collect(nodes.editor, (node) => hasClass(node, "entry")).length < before,
  "the line is removed",
);
assert.equal(nodes.pdf.disabled, true, "removal relocks downloads");
assert.equal(nodes.accuracy.checked, false);

const move = collect(
  nodes.editor,
  (node) =>
    node.tag === "button" &&
    /^Move this /.test(node.getAttribute("aria-label") || "") &&
    !node.disabled,
)[0];
assert.ok(move, "a reorder control is available");
move.click();
assert.equal(nodes.pdf.disabled, true);

// A confirmation reply that arrives after an edit must not restore the old
// draft or unlock downloads.
const realFetch = context.fetch;
let releaseConfirm = null;
context.fetch = (input, options) => {
  const url = String(input);
  if (url.endsWith("/api/cv/confirm")) {
    return new Promise((resolve, reject) => {
      releaseConfirm = () => realFetch(input, options).then(resolve, reject);
    });
  }
  return realFetch(input, options);
};
nodes.accuracy.checked = true;
nodes.confirm.click();
await waitFor(() => typeof releaseConfirm === "function", "delayed confirmation");
nameInput().value = "Alex Rivera Edited";
nameInput().fire("input");
assert.equal(nodes.pdf.disabled, true, "the edit locks downloads again");
assert.equal(controller.state.confirmed, false);
releaseConfirm();
await new Promise((resolve) => setTimeout(resolve, 300));
assert.equal(
  controller.state.draft.candidate.full_name,
  "Alex Rivera Edited",
  "a stale confirmation response must not overwrite the edited contact",
);
assert.equal(controller.state.confirmed, false, "a stale response cannot confirm");
assert.equal(nodes.pdf.disabled, true);
assert.doesNotMatch(nodes.status.textContent, /This version is confirmed/);

// The current version can still be confirmed normally after the stale reply.
context.fetch = realFetch;
nodes.accuracy.checked = true;
nodes.confirm.click();
await waitFor(() => nodes.pdf.disabled === false, "confirmation after stale reply");

// Start Over while a confirmation is in flight must leave no review state.
let releaseStartOverConfirm = null;
context.fetch = (input, options) => {
  const url = String(input);
  if (url.endsWith("/api/cv/confirm")) {
    return new Promise((resolve, reject) => {
      releaseStartOverConfirm = () => realFetch(input, options).then(resolve, reject);
    });
  }
  return realFetch(input, options);
};
nameInput().value = "Alex Rivera Final";
nameInput().fire("input");
nodes.accuracy.checked = true;
nodes.confirm.click();
await waitFor(
  () => typeof releaseStartOverConfirm === "function",
  "delayed confirmation before Start Over",
);
nodes["start-over"].click();
assert.equal(controller.state.draft, null, "Start Over clears the draft immediately");
releaseStartOverConfirm();
await new Promise((resolve) => setTimeout(resolve, 300));
assert.equal(controller.state.draft, null, "a stale reply cannot restore a draft");
assert.equal(nodes.create.hidden, false, "the create screen stays visible");
assert.equal(nodes.review.hidden, true, "the review screen stays hidden");
assert.equal(nodes.pdf.disabled, true);
assert.doesNotMatch(nodes.status.textContent, /This version is confirmed/);

/* ------------------------------------------------- sequential upload flow */

// The real picker and drop handlers must append, not replace, and every
// combined selection must be the batch the real extraction endpoint receives.
extractionCalls.length = 0;
const pickerA = new File([readFileSync(pdfPath)], "picker-a.pdf", {
  type: product.PDF_MIME,
});
const pickerB = new File([readFileSync(docxPath)], "picker-b.docx", {
  type: product.DOCX_MIME,
});
const pickerC = new File([readFileSync(pdfPath)], "picker-c.pdf", {
  type: product.PDF_MIME,
});
const pickerD = new File([readFileSync(pdfPath)], "picker-d.pdf", {
  type: product.PDF_MIME,
});
const pickerE = new File([readFileSync(pdfPath)], "picker-e.pdf", {
  type: product.PDF_MIME,
});
const pickerF = new File([readFileSync(pdfPath)], "picker-f.pdf", {
  type: product.PDF_MIME,
});

function choose(files) {
  nodes.files.files = files;
  nodes.files.value = "picked";
  nodes.files.fire("change");
}

async function waitForUpload(count, label) {
  await waitFor(
    () =>
      controller.state.files.length === count &&
      !controller.state.uploading &&
      controller.state.source &&
      controller.state.source.documents.length === count,
    label || "upload of " + count + " documents",
  );
}

// Hold the first extraction call so B is added while A is still in flight.
let releaseFirst;
extractionGate = new Promise((resolve) => {
  releaseFirst = resolve;
});
choose([pickerA]);
await waitFor(() => extractionCalls.length === 1, "first picker extraction request");
choose([pickerB]);
await waitForUpload(2, "A and B appended in one extraction request");
assert.deepEqual(
  Array.from(controller.state.files, (file) => file.name),
  ["picker-a.pdf", "picker-b.docx"],
);
assert.deepEqual(
  extractionCalls.at(-1),
  ["picker-a.pdf", "picker-b.docx"],
  "the actual extraction request contains the combined selection",
);
releaseFirst();
await new Promise((resolve) => setTimeout(resolve, 300));
assert.deepEqual(
  Array.from(controller.state.files, (file) => file.name),
  ["picker-a.pdf", "picker-b.docx"],
  "a late response for A cannot restore an obsolete selection",
);
assert.equal(
  controller.state.source.documents.length,
  2,
  "the current source remains the A+B extraction",
);

// Selecting B again is a no-op, not a duplicate document or a new request.
const callsAfterDuplicate = extractionCalls.length;
choose([pickerB]);
await new Promise((resolve) => setTimeout(resolve, 150));
assert.equal(controller.state.files.length, 2);
assert.equal(extractionCalls.length, callsAfterDuplicate);
assert.match(nodes.status.textContent, /already selected/i);

// Drag-and-drop uses the same append path.
nodes.drop.fire("drop", {
  preventDefault() {},
  dataTransfer: { files: [pickerC] },
});
await waitForUpload(3, "drag-and-drop addition");
assert.deepEqual(extractionCalls.at(-1), [
  "picker-a.pdf",
  "picker-b.docx",
  "picker-c.pdf",
]);

// Removing one file preserves the others and re-extracts the remainder.
const removeButtons = collect(
  nodes["files-list"],
  (node) => hasClass(node, "file-remove"),
);
assert.equal(removeButtons.length, 3);
removeButtons[0].click();
await waitForUpload(2, "remove A and keep B/C");
assert.deepEqual(
  Array.from(controller.state.files, (file) => file.name),
  ["picker-b.docx", "picker-c.pdf"],
);

// The same file can be selected again after removal.
choose([pickerA]);
await waitForUpload(3, "re-add A");
assert.deepEqual(
  Array.from(controller.state.files, (file) => file.name),
  ["picker-b.docx", "picker-c.pdf", "picker-a.pdf"],
);

// An invalid addition is rejected without clearing the current selection.
const callsBeforeInvalid = extractionCalls.length;
choose([
  new File([Buffer.from("not a cv")], "not-a-cv.txt", { type: "text/plain" }),
]);
await new Promise((resolve) => setTimeout(resolve, 100));
assert.equal(controller.state.files.length, 3);
assert.equal(extractionCalls.length, callsBeforeInvalid);
assert.match(nodes["file-error"].textContent, /PDF or DOCX/);
assert.ok(controller.state.source, "the valid extraction remains usable");

// Five documents are allowed; a sixth is rejected and the five remain.
choose([pickerD, pickerE]);
await waitForUpload(5, "combined D/E addition");
const callsAtFive = extractionCalls.length;
choose([pickerF]);
await new Promise((resolve) => setTimeout(resolve, 100));
assert.equal(controller.state.files.length, 5);
assert.equal(extractionCalls.length, callsAtFive);
assert.match(nodes["file-error"].textContent, /at most five/i);

console.log(
  "Main controller: sample → prefill → preview → edit → confirm → PDF/DOCX → invalidation → removal/reorder → stale-reply guards passed (DOM test double)",
);
console.log(
  "Sequential upload: picker append, drag-and-drop append, duplicate no-op, remove/re-add, invalid addition preservation, five-document limit and stale extraction guard passed (real HTTP extraction)",
);
