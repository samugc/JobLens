"use strict";
/* Canonical CV draft baseline 0.1. Frontend boundary only: generation and
   export are owned by the backend and stay unavailable until integrated. */
(function (global, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    global.JobLensTailor = factory();
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const DRAFT_VERSION = "0.1";
  const SECTION_KINDS = Object.freeze([
    "summary", "experience", "projects", "education", "skills", "publications", "custom", "languages", "certifications",
  ]);
  const REVIEW_STATUSES = Object.freeze(["draft", "approved", "needs_review"]);

  class TailorAdapterError extends Error {
    constructor(message) { super(message); this.name = "TailorAdapterError"; }
  }

  function fail(message) { throw new TailorAdapterError(message); }

  function isString(value) { return typeof value === "string"; }
  function isStringArray(value) {
    return Array.isArray(value) && value.every(isString);
  }
  function isObject(value) { return value !== null && typeof value === "object" && !Array.isArray(value); }

  function validateDraft(draft) {
    if (!isObject(draft)) fail("a CV draft must be an object");
    if (draft.cv_draft_version !== DRAFT_VERSION) {
      fail(`unsupported CV draft version: ${draft.cv_draft_version}`);
    }
    if (!isObject(draft.target_job)) fail("target_job must be an object");
    if (!isString(draft.target_job.title)) fail("target_job.title must be a string");
    if (!isString(draft.target_job.company)) fail("target_job.company must be a string");
    if (!isObject(draft.candidate)) fail("candidate must be an object");
    if (!isString(draft.candidate.full_name)) fail("candidate.full_name must be a string");
    if (!isString(draft.candidate.email)) fail("candidate.email must be a string");
    if (!isString(draft.candidate.phone)) fail("candidate.phone must be a string");
    if (!isString(draft.candidate.location)) fail("candidate.location must be a string");
    if (!isStringArray(draft.candidate.links)) fail("candidate.links must be a string array");
    if (!Array.isArray(draft.sections)) fail("sections must be an array");
    draft.sections.forEach((section, index) => {
      if (!isObject(section)) fail(`section ${index} must be an object`);
      if (!isString(section.section_id) || !section.section_id) fail(`section ${index} needs a section_id`);
      if (!SECTION_KINDS.includes(section.kind)) fail(`section ${index} has an unknown kind`);
      if (!isString(section.title)) fail(`section ${index} title must be a string`);
      if (!Array.isArray(section.items)) fail(`section ${index} items must be an array`);
      section.items.forEach((item, itemIndex) => {
        if (!isObject(item)) fail(`item ${itemIndex} of section ${index} must be an object`);
        if (!isString(item.item_id) || !item.item_id) fail(`item ${itemIndex} needs an item_id`);
        if (!isString(item.text)) fail(`item ${itemIndex} text must be a string`);
        if (!isStringArray(item.approved_fact_ids)) fail(`item ${itemIndex} approved_fact_ids must be a string array`);
        if (!REVIEW_STATUSES.includes(item.review_status)) fail(`item ${itemIndex} has an unknown review_status`);
      });
    });
    if (!isStringArray(draft.warnings)) fail("warnings must be a string array");
    if (!isStringArray(draft.unmet_requirements)) fail("unmet_requirements must be a string array");
    return draft;
  }

  function emptyDraft(job) {
    job = job || {};
    return validateDraft({
      cv_draft_version: DRAFT_VERSION,
      target_job: {
        title: isString(job.title) ? job.title : "",
        company: isString(job.company) ? job.company : "",
      },
      candidate: { full_name: "", email: "", phone: "", location: "", links: [] },
      sections: [],
      warnings: [],
      unmet_requirements: [],
    });
  }

  const adapter = {
    DRAFT_VERSION,
    SECTION_KINDS,
    REVIEW_STATUSES,
    validateDraft,
    emptyDraft,
    generateDraft: async function () {
      // The backend generation contract is owned by another layer. Until it is
      // integrated, generation is honestly unavailable and no draft is produced.
      throw new TailorAdapterError(
        "CV generation is not available: the backend generation contract is not integrated. " +
        "You can still build a draft manually from your approved facts.",
      );
    },
    exportPdf: async function () {
      throw new TailorAdapterError(
        "PDF export is not available: no real exporter is integrated and the draft has not been validated.",
      );
    },
    exportDocx: async function () {
      throw new TailorAdapterError(
        "DOCX export is not available: no real exporter is integrated and the draft has not been validated.",
      );
    },
    isGenerationAvailable: function () { return false; },
    isExportAvailable: function () { return false; },
  };

  return adapter;
});
