"use strict";

/*
 * JobLens CV Evidence Workspace — candidate profile adapter
 *
 * This file is the only place that knows the profile wire format. It reads the
 * canonical envelope of the profile engine (profile schema 0.1, derived from
 * parser schema 1.1) and turns it into a normalized shape the review view can
 * render without knowing the wire format.
 *
 * Two things are checked here and nowhere else:
 *
 * 1. The shape of the envelope: versions, categories, value objects, evidence
 *    support values, conflict records and their references.
 * 2. The evidence itself: every quotation must be the text of the referenced
 *    block of the source extraction. The offsets of the contract are Python
 *    string indices, that is, Unicode code points, while JavaScript strings are
 *    indexed in UTF-16 code units. Every offset in this file is therefore
 *    applied to an array of code points, never to a raw substring.
 *
 * The adapter never proposes, approves or edits a fact. Those are human
 * decisions and they live in profile-review.js.
 */
(function (global, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    global.JobLensProfileAdapter = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const PROFILE_SCHEMA_VERSION = "0.1";
  const PARSER_SCHEMA_VERSION = "1.1";

  const CATEGORIES = Object.freeze([
    "skill",
    "experience",
    "education",
    "project",
    "language",
    "certification",
  ]);

  // The exact support values of the contract.
  const SUPPORT_KINDS = Object.freeze(["explicit_claim", "keyword_mention"]);

  // The education levels the engine may propose.
  const DEGREE_LEVELS = Object.freeze([
    "bachelor",
    "master",
    "doctorate",
    "associate",
    "diploma",
    "mba",
  ]);

  // Canonical conflicts are contradictions. Compatible descriptions are already
  // merged by the backend; no independently validated non-blocking type exists.
  const NON_BLOCKING_CONFLICT_KINDS = Object.freeze([]);

  const PROPOSAL_STATUSES = Object.freeze([
    "proposed",
    "approved",
    "rejected",
    "superseded",
  ]);

  const SUPPORT_META = Object.freeze({
    explicit_claim: {
      label: "Explicit claim",
      tone: "ok",
      description: "The document states this fact.",
    },
    keyword_mention: {
      label: "Keyword mention",
      tone: "warn",
      description:
        "The word appears in the text, but the document does not state it as a fact.",
    },
  });

  /*
   * The value shapes are exact. The primary field is the one a card is titled
   * with; the other fields are shown as details, with the wording the contract
   * uses.
   */
  const CATEGORY_META = Object.freeze({
    skill: {
      label: "Skills",
      singular: "Skill",
      primary: "name",
      required: ["name"],
      details: [],
    },
    experience: {
      label: "Experience",
      singular: "Experience",
      primary: "role",
      required: ["role"],
      details: [],
    },
    education: {
      label: "Education",
      singular: "Education",
      primary: "field",
      required: ["level", "field"],
      details: ["level"],
    },
    project: {
      label: "Projects",
      singular: "Project",
      primary: "name",
      required: ["name"],
      details: [],
    },
    language: {
      label: "Languages",
      singular: "Language",
      primary: "language",
      required: ["language"],
      details: ["stated_level"],
    },
    certification: {
      label: "Certifications",
      singular: "Certification",
      primary: "name",
      required: ["name"],
      details: [],
    },
  });

  const FIELD_LABELS = Object.freeze({
    name: "Name",
    role: "Role",
    level: "Level",
    field: "Field of study",
    language: "Language",
    stated_level: "Stated level",
  });

  class CvProfileError extends Error {
    constructor(message, { code = "profile_error", details = null } = {}) {
      super(message);
      this.name = "CvProfileError";
      this.code = code;
      this.details = details;
    }
  }

  class CvProfileContractError extends CvProfileError {
    constructor(message, details = null) {
      super(message, { code: "contract_error", details });
      this.name = "CvProfileContractError";
    }
  }

  class CvProfileHttpError extends CvProfileError {
    constructor(status, message, details = null) {
      super(message, { code: "http_error", details });
      this.name = "CvProfileHttpError";
      this.status = status;
    }
  }

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function fail(path, message) {
    throw new CvProfileContractError(`${path}: ${message}`, { path });
  }

  function readString(value, path, { allowEmpty = false } = {}) {
    if (typeof value !== "string") fail(path, "expected a string");
    if (!allowEmpty && !value.trim()) fail(path, "expected a non-empty string");
    return allowEmpty ? value : value.trim();
  }

  function readOptionalString(value, path) {
    if (value === undefined || value === null) return null;
    return readString(value, path, { allowEmpty: true });
  }

  function readIndex(value, path) {
    if (!Number.isInteger(value) || value < 0) {
      fail(path, "expected a non-negative integer");
    }
    return value;
  }

  function readArray(value, path, { optional = false } = {}) {
    if (value === undefined || value === null) {
      if (optional) return [];
      fail(path, "expected an array");
    }
    if (!Array.isArray(value)) fail(path, "expected an array");
    return value;
  }

  function humanizeKey(key) {
    const text = String(key || "").replace(/[_-]+/g, " ").trim();
    if (!text) return "Detail";
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  function fieldLabel(key) {
    return FIELD_LABELS[key] || humanizeKey(key);
  }

  /*
   * The offsets of the contract are Python string indices, that is, Unicode
   * code points. JavaScript string indices are UTF-16 code units, which differ
   * as soon as the text contains a character outside the basic multilingual
   * plane. Every offset is therefore applied to an array of code points.
   */
  function codePoints(text) {
    return Array.from(String(text ?? ""));
  }

  function codePointLength(text) {
    return codePoints(text).length;
  }

  function codePointSlice(text, start, end) {
    return codePoints(text).slice(start, end).join("");
  }

  /* Locators keep the parser's shape: 1-based pages, 1-based paragraphs and
   * the DOCX section when the parser reported one. */
  function normalizeLocator(raw, path) {
    if (!isPlainObject(raw)) fail(path, "expected an object");

    const kind =
      raw.kind ||
      (raw.page !== undefined
        ? "page"
        : raw.paragraph !== undefined
          ? "paragraph"
          : null);

    if (kind === "page") {
      if (!Number.isInteger(raw.page) || raw.page < 1) {
        fail(`${path}.page`, "expected a 1-based page number");
      }
      return { kind: "page", page: raw.page, paragraph: null, section: null };
    }

    if (kind === "paragraph") {
      if (!Number.isInteger(raw.paragraph) || raw.paragraph < 1) {
        fail(`${path}.paragraph`, "expected a 1-based paragraph number");
      }
      return {
        kind: "paragraph",
        paragraph: raw.paragraph,
        page: null,
        section: readOptionalString(raw.section, `${path}.section`),
      };
    }

    fail(`${path}.kind`, "expected “page” or “paragraph”");
  }

  function sameLocator(a, b) {
    if (!a || !b) return false;
    if (a.kind !== b.kind) return false;
    if (a.kind === "page") return a.page === b.page;
    if (a.kind === "paragraph") {
      return (
        a.paragraph === b.paragraph &&
        (a.section ?? null) === (b.section ?? null)
      );
    }
    return false;
  }

  /*
   * The category-specific values are kept exactly as the engine sent them. The
   * adapter checks the required fields and nothing else: it never invents a
   * field and never rewrites a value.
   */
  function describeValue(category, raw) {
    const meta = CATEGORY_META[category];
    if (!meta) fail("value", `unknown category “${category}”`);

    const source = isPlainObject(raw) ? raw : {};

    for (const key of meta.required) {
      const value = source[key];
      if (typeof value !== "string" || !value.trim()) {
        fail(`value.${key}`, "expected a non-empty string");
      }
    }
    if (category === "education" && !DEGREE_LEVELS.includes(source.level)) {
      fail(
        "value.level",
        `expected one of ${DEGREE_LEVELS.join(", ")}`,
      );
    }
    if (
      category === "language" &&
      source.stated_level !== undefined &&
      source.stated_level !== null &&
      typeof source.stated_level !== "string"
    ) {
      fail("value.stated_level", "expected a string or null");
    }

    const details = [];
    for (const key of meta.details) {
      const value = source[key];
      details.push({
        key,
        label: fieldLabel(key),
        value: value === undefined || value === null ? "not stated" : String(value),
      });
    }

    const primary = source[meta.primary];
    return {
      value: { ...source },
      label: String(primary).trim(),
      details,
    };
  }

  function normalizeEvidence(raw, position, path) {
    if (!isPlainObject(raw)) fail(path, "expected an object");

    const documentId = readString(raw.document_id, `${path}.document_id`);
    const segmentIndex = readIndex(raw.segment_index, `${path}.segment_index`);
    const quote = readString(raw.quote, `${path}.quote`, { allowEmpty: true });
    const start = readIndex(raw.start, `${path}.start`);
    const end = readIndex(raw.end, `${path}.end`);
    if (end < start) fail(`${path}.end`, "must not be smaller than start");

    const locator = normalizeLocator(raw.locator, `${path}.locator`);

    const support = readString(raw.support, `${path}.support`);
    if (!SUPPORT_KINDS.includes(support)) {
      fail(
        `${path}.support`,
        `expected “${SUPPORT_KINDS.join("” or “")}”`,
      );
    }

    return {
      id: `${documentId}#${segmentIndex}#${position}`,
      documentId,
      segmentIndex,
      locator,
      quote,
      start,
      end,
      support,
      supportLabel: SUPPORT_META[support].label,
      supportTone: SUPPORT_META[support].tone,
      supportDescription: SUPPORT_META[support].description,
      resolved: null,
      verified: null,
      reason: null,
      document: null,
      segmentText: null,
    };
  }

  /*
   * An optional resolution hint. The backend may suggest how a conflict could
   * be resolved. A suggestion is never applied by itself: it is only shown,
   * and a reviewer has to act on it. A hint that does not hold together is
   * dropped, and the conflict then has to be resolved by hand.
   */
  function normalizeResolutionHint(raw, conflict, path) {
    if (raw === undefined || raw === null) {
      return { hint: null, issue: null };
    }

    if (!isPlainObject(raw)) {
      return { hint: null, issue: "the suggestion is not an object" };
    }

    const strategy = readOptionalString(raw.strategy, `${path}.strategy`);
    if (!strategy || !strategy.trim()) {
      return { hint: null, issue: "the suggestion names no strategy" };
    }

    const keep = readArray(raw.keep_proposal_ids, `${path}.keep_proposal_ids`);
    if (!keep.length) {
      return { hint: null, issue: "the suggestion names no proposal" };
    }

    const keepProposalIds = keep.map((id, index) =>
      readString(id, `${path}.keep_proposal_ids[${index}]`),
    );

    // A suggestion may only speak about the proposals of its own conflict.
    const foreign = keepProposalIds.filter((id) => !conflict.proposalIds.includes(id));
    if (foreign.length) {
      return {
        hint: null,
        issue: "the suggestion names a proposal that is not part of this conflict",
      };
    }

    const explanation = readOptionalString(raw.explanation, `${path}.explanation`) ?? "";

    let requiresUserConfirmation = true;
    if (raw.requires_user_confirmation !== undefined) {
      if (typeof raw.requires_user_confirmation !== "boolean") {
        return {
          hint: null,
          issue: "the confirmation flag of the suggestion is not a boolean",
        };
      }
      requiresUserConfirmation = raw.requires_user_confirmation;
    }

    return {
      hint: {
        strategy: strategy.trim(),
        keepProposalIds,
        explanation,
        requiresUserConfirmation,
      },
      issue: null,
    };
  }

  function normalizeConflict(raw, position, path) {
    if (!isPlainObject(raw)) fail(path, "expected an object");

    const conflictId = readString(raw.conflict_id, `${path}.conflict_id`);
    const kind = readString(raw.kind, `${path}.kind`);
    const category = readString(raw.category, `${path}.category`);
    if (!CATEGORIES.includes(category)) {
      fail(`${path}.category`, `unknown category “${category}”`);
    }
    const message = readString(raw.message, `${path}.message`, {
      allowEmpty: true,
    });
    const proposalIds = readArray(raw.proposal_ids, `${path}.proposal_ids`).map(
      (id, index) => readString(id, `${path}.proposal_ids[${index}]`),
    );

    const conflict = {
      conflictId,
      kind,
      category,
      categoryLabel: CATEGORY_META[category].label,
      message,
      proposalIds,
      position,
    };

    const { hint, issue } = normalizeResolutionHint(
      raw.resolution_hint,
      conflict,
      `${path}.resolution_hint`,
    );
    conflict.resolutionHint = hint;
    conflict.resolutionHintIssue = issue;
    conflict.suggestion = null;
    // Unknown kinds also fail closed until explicitly resolved.
    conflict.blocking = !NON_BLOCKING_CONFLICT_KINDS.includes(kind);

    return conflict;
  }

  function describeSuggestion(proposals) {
    const parts = proposals.map((proposal) => {
      const detail = (proposal.details || [])
        .map((entry) => `${entry.label}: ${entry.value}`)
        .join(", ");
      return detail ? `${proposal.label} (${detail})` : proposal.label;
    });
    return {
      label: parts.join(", "),
      proposalIds: proposals.map((proposal) => proposal.id),
    };
  }

  function normalizeDocumentReference(raw, position, path) {
    if (!isPlainObject(raw)) fail(path, "expected an object");

    const documentId = readString(raw.document_id, `${path}.document_id`);
    return {
      documentId,
      index: readIndex(raw.index, `${path}.index`),
      filename: readOptionalString(raw.filename, `${path}.filename`),
      status: readOptionalString(raw.status, `${path}.status`),
      format: readOptionalString(raw.format, `${path}.format`),
      segmentCount: readIndex(raw.segment_count, `${path}.segment_count`),
      textLength: readIndex(raw.text_length, `${path}.text_length`),
    };
  }

  function normalizeProposal(raw, position, path, conflictsById) {
    if (!isPlainObject(raw)) fail(path, "expected an object");

    const id = readString(raw.proposal_id, `${path}.proposal_id`);
    const category = readString(raw.category, `${path}.category`);
    if (!CATEGORIES.includes(category)) {
      fail(`${path}.category`, `unknown category “${category}”`);
    }

    const status = readString(raw.status, `${path}.status`);
    if (!PROPOSAL_STATUSES.includes(status)) {
      fail(`${path}.status`, `unknown proposal status “${status}”`);
    }

    const described = describeValue(category, raw.value);

    const evidence = readArray(raw.evidence, `${path}.evidence`).map(
      (item, index) => normalizeEvidence(item, index, `${path}.evidence[${index}]`),
    );

    const conflictIds = readArray(raw.conflicts, `${path}.conflicts`, {
      optional: true,
    }).map((conflictId, index) =>
      readString(conflictId, `${path}.conflicts[${index}]`),
    );

    const conflicts = conflictIds.map((conflictId) => {
      const conflict = conflictsById.get(conflictId) || null;
      return {
        conflictId,
        known: Boolean(conflict),
        kind: conflict?.kind ?? null,
        message: conflict?.message ?? null,
        proposalIds: conflict?.proposalIds ?? [],
        blocking: conflict ? conflict.blocking : true,
        resolved: false,
        resolution: null,
      };
    });

    return {
      id,
      position,
      category,
      categoryLabel: CATEGORY_META[category].label,
      categorySingular: CATEGORY_META[category].singular,
      primaryField: CATEGORY_META[category].primary,
      fields: CATEGORY_META[category].required.concat(
        CATEGORY_META[category].details,
      ),
      label: described.label,
      value: described.value,
      details: described.details,
      status,
      evidence,
      conflictIds,
      conflicts,
      revision: null,
      revisionOf: null,
    };
  }

  /*
   * Evidence is only usable when it points at a document and a text block that
   * this session actually holds, and when the quote is that block's text at
   * the code-point offsets of the contract.
   */
  function resolveEvidence(evidence, source) {
    return evidence.map((entry) => {
      const resolved = { ...entry };

      if (!source || !Array.isArray(source.documents)) {
        resolved.resolved = null;
        resolved.verified = null;
        resolved.reason = "No source document is loaded for this profile.";
        return resolved;
      }

      const document = source.documents.find(
        (item) => item.id === entry.documentId,
      );
      if (!document) {
        resolved.resolved = false;
        resolved.verified = false;
        resolved.reason = "The source document is not in this session.";
        return resolved;
      }

      const segment = Array.isArray(document.segments)
        ? document.segments[entry.segmentIndex]
        : null;
      if (!segment) {
        resolved.resolved = false;
        resolved.verified = false;
        resolved.reason = "The referenced text block does not exist in that document.";
        return resolved;
      }

      resolved.resolved = true;
      resolved.document = {
        id: document.id,
        filename: document.filename ?? null,
        format: document.format ?? null,
      };
      resolved.segmentText = segment.text ?? "";

      const quoted = codePointSlice(
        resolved.segmentText,
        entry.start,
        entry.end,
      );
      if (quoted !== entry.quote) {
        resolved.verified = false;
        resolved.reason = "The quote does not match the extracted text of that block.";
        return resolved;
      }

      if (!sameLocator(entry.locator, segment.locator)) {
        resolved.verified = false;
        resolved.reason = "The reference does not match the extracted block.";
        return resolved;
      }

      resolved.verified = true;
      resolved.reason = null;
      return resolved;
    });
  }

  function countProposals(proposals, conflicts) {
    const counts = {
      total: proposals.length,
      proposed: 0,
      approved: 0,
      rejected: 0,
      superseded: 0,
      unresolved: 0,
      conflicts: conflicts.length,
      categories: {},
    };
    for (const category of CATEGORIES) counts.categories[category] = 0;

    for (const proposal of proposals) {
      if (proposal.status === "approved") counts.approved += 1;
      else if (proposal.status === "rejected") counts.rejected += 1;
      else if (proposal.status === "superseded") counts.superseded += 1;
      else counts.proposed += 1;

      if (proposal.category in counts.categories) {
        counts.categories[proposal.category] += 1;
      }
    }
    return counts;
  }

  function normalizeProfileEnvelope(raw, { source = null } = {}) {
    if (!isPlainObject(raw)) fail("response", "expected an object");

    const schemaVersion = readString(
      raw.profile_schema_version,
      "profile_schema_version",
    );
    if (schemaVersion !== PROFILE_SCHEMA_VERSION) {
      throw new CvProfileContractError(
        `Unsupported profile_schema_version “${schemaVersion}”. This adapter supports “${PROFILE_SCHEMA_VERSION}”.`,
        { schemaVersion, supported: PROFILE_SCHEMA_VERSION },
      );
    }

    const parserSchemaVersion = readString(
      raw.parser_schema_version,
      "parser_schema_version",
    );
    if (parserSchemaVersion !== PARSER_SCHEMA_VERSION) {
      throw new CvProfileContractError(
        `Unsupported parser_schema_version “${parserSchemaVersion}”. This adapter supports “${PARSER_SCHEMA_VERSION}”.`,
        { parserSchemaVersion, supported: PARSER_SCHEMA_VERSION },
      );
    }

    const jobId =
      raw.job_id === undefined || raw.job_id === null
        ? null
        : readString(raw.job_id, "job_id");

    // The document references are provenance. The evidence is resolved against
    // the source extraction, so a missing list is not fatal by itself.
    const documents = readArray(raw.documents, "documents", { optional: true }).map(
      (document, index) =>
        normalizeDocumentReference(document, index, `documents[${index}]`),
    );

    const conflicts = readArray(raw.conflicts, "conflicts", { optional: true }).map(
      (conflict, index) =>
        normalizeConflict(conflict, index, `conflicts[${index}]`),
    );
    const conflictsById = new Map(conflicts.map((conflict) => [conflict.conflictId, conflict]));

    const proposals = readArray(raw.proposals, "proposals").map((proposal, index) =>
      normalizeProposal(proposal, index, `proposals[${index}]`, conflictsById),
    );

    const ids = new Set();
    for (const proposal of proposals) {
      if (ids.has(proposal.id)) {
        fail("proposals", `duplicate proposal_id “${proposal.id}”`);
      }
      ids.add(proposal.id);
    }

    for (const proposal of proposals) {
      proposal.evidence = resolveEvidence(proposal.evidence, source);
    }

    // A suggestion may only point at proposals of this response.
    const proposalsById = new Map(proposals.map((proposal) => [proposal.id, proposal]));
    for (const conflict of conflicts) {
      if (!conflict.resolutionHint) continue;
      const kept = conflict.resolutionHint.keepProposalIds.map((id) =>
        proposalsById.get(id),
      );
      if (kept.some((proposal) => !proposal)) {
        conflict.resolutionHint = null;
        conflict.resolutionHintIssue =
          "the suggestion names a proposal that is not in this response";
        continue;
      }
      conflict.suggestion = describeSuggestion(kept);
    }

    const warnings = readArray(raw.warnings, "warnings", { optional: true }).map(
      (warning, index) => readString(warning, `warnings[${index}]`),
    );

    return {
      schemaVersion,
      parserSchemaVersion,
      jobId,
      documents,
      proposals,
      conflicts,
      warnings,
      counts: countProposals(proposals, conflicts),
      source: source
        ? { jobId: source.jobId ?? null, documentCount: source.documents.length }
        : null,
    };
  }

  /*
   * The synthetic preview reads two files: the synthetic parser response that
   * the engine would consume, and the envelope the engine produced from it.
   * The response is the source the evidence is checked against.
   */
  function normalizePreviewEnvelope(envelopeRaw, sourceRaw) {
    const source = buildSource(sourceRaw);
    const profile = normalizeProfileEnvelope(envelopeRaw, { source });
    return {
      profile,
      source,
      label:
        "Synthetic sample — produced by the profile engine from synthetic documents, not a real candidate.",
      synthetic: true,
    };
  }

  /* Build a source from a parser or transport response. */
  function buildSource(raw) {
    if (!isPlainObject(raw)) fail("source", "expected an object");
    const documents = readArray(raw.documents, "source.documents").map(
      (document, index) => {
        const path = `source.documents[${index}]`;
        if (!isPlainObject(document)) fail(path, "expected an object");
        const id = readString(
          document.document_id ?? document.id,
          `${path}.document_id`,
        );
        const segments = readArray(document.segments, `${path}.segments`).map(
          (segment, segmentIndex) => {
            const segmentPath = `${path}.segments[${segmentIndex}]`;
            if (!isPlainObject(segment)) fail(segmentPath, "expected an object");
            return {
              text: readString(segment.text, `${segmentPath}.text`, {
                allowEmpty: true,
              }),
              locator: normalizeLocator(segment.locator, `${segmentPath}.locator`),
            };
          },
        );
        return {
          id,
          index: Number.isInteger(document.index) ? document.index : index,
          filename: readOptionalString(document.filename, `${path}.filename`),
          format: readOptionalString(document.format, `${path}.format`),
          status: readOptionalString(document.status, `${path}.status`),
          segments,
        };
      },
    );

    return {
      jobId: readOptionalString(raw.job_id ?? raw.jobId, "source.job_id"),
      documents,
    };
  }

  /* Build a source from a normalized extraction job. */
  function sourceFromJob(job) {
    if (!job || !Array.isArray(job.documents)) return null;
    return {
      jobId: job.id ?? null,
      documents: job.documents.map((document) => ({
        id: document.id,
        index: document.index,
        filename: document.filename ?? null,
        format: document.format ?? null,
        status: document.parserStatus ?? document.status ?? null,
        segments: (document.segments || []).map((segment) => ({
          text: segment.text ?? "",
          locator: segment.locator,
        })),
      })),
    };
  }

  /*
   * The profile engine consumes the response of the CV HTTP transport
   * unchanged. The request body is therefore that response, rebuilt from the
   * extraction of this session.
   */
  /*
   * The profile endpoint accepts exactly two top-level keys. Anything else is
   * refused with HTTP 400 invalid_request, so the extraction response is
   * projected down to the job id and the source documents, and nothing else.
   */
  function projectLocator(locator) {
    if (!isPlainObject(locator)) return locator;
    if (locator.kind === "page") {
      return { kind: "page", page: locator.page };
    }
    if (locator.kind === "paragraph") {
      const projected = { kind: "paragraph", paragraph: locator.paragraph };
      if (locator.section !== undefined && locator.section !== null) {
        projected.section = locator.section;
      }
      return projected;
    }
    return locator;
  }

  function buildProfileRequest(job) {
    if (!job || !Array.isArray(job.documents) || !job.documents.length) {
      throw new CvProfileError(
        "A profile needs the extracted documents it is built from.",
        { code: "no_source" },
      );
    }

    const documents = job.documents.map((document, position) => {
      const documentId =
        typeof document?.id === "string" ? document.id.trim() : "";
      if (!documentId) {
        throw new CvProfileError(
          "Every document needs the identifier the parser gave it.",
          { code: "invalid_source", details: { position } },
        );
      }

      const index = Number.isInteger(document.index) ? document.index : position;
      if (index !== position) {
        throw new CvProfileError(
          "The document index has to match its position in the batch.",
          { code: "invalid_source", details: { position, index } },
        );
      }

      const segments = (document.segments || []).map((segment, segmentPosition) => {
        if (
          !segment ||
          typeof segment.text !== "string" ||
          !isPlainObject(segment.locator)
        ) {
          throw new CvProfileError(
            "Every block needs a locator and its text.",
            { code: "invalid_source", details: { position, segmentPosition } },
          );
        }
        return {
          locator: projectLocator(segment.locator),
          text: segment.text,
        };
      });

      return {
        document_id: documentId,
        index,
        filename: typeof document.filename === "string" ? document.filename : "",
        status: document.parserStatus ?? document.status ?? null,
        format: document.format ?? null,
        segments,
      };
    });

    return {
      job_id: job.id ?? null,
      documents,
    };
  }

  class CvProfileAdapter {
    constructor(options = {}) {
      this.baseUrl = String(options.baseUrl || "/api/cv").replace(/\/+$/, "");
      this.fetchImpl = options.fetchImpl || globalThis.fetch?.bind(globalThis);
      this.requestToken = options.requestToken || "1";
      this.path = options.path || "/profiles";

      if (typeof this.fetchImpl !== "function") {
        throw new CvProfileError("This browser cannot call the profile service.", {
          code: "fetch_unavailable",
        });
      }
    }

    endpoint(path) {
      return `${this.baseUrl}${path}`;
    }

    async request(path, { method = "GET", body, headers = {}, signal } = {}) {
      let response;
      try {
        response = await this.fetchImpl(this.endpoint(path), {
          method,
          body,
          headers,
          signal,
          credentials: "same-origin",
        });
      } catch (error) {
        if (error?.name === "AbortError") throw error;
        throw new CvProfileError(
          `Could not reach the profile service. ${error?.message || "The request failed."}`,
          { code: "network_error", details: error },
        );
      }

      const text = await response.text();
      let payload = null;
      if (text) {
        try {
          payload = JSON.parse(text);
        } catch {
          throw new CvProfileContractError(
            `The profile service returned HTTP ${response.status} with a non-JSON body.`,
            { status: response.status },
          );
        }
      }

      if (!response.ok) {
        const rawError = payload?.error;
        const code = isPlainObject(rawError) ? rawError.code : (payload?.code ?? null);
        const message =
          (isPlainObject(rawError) ? rawError.message : rawError) ||
          payload?.message ||
          `The profile service returned HTTP ${response.status}.`;
        throw new CvProfileHttpError(response.status, String(message), {
          code,
          payload,
        });
      }

      if (!isPlainObject(payload)) {
        throw new CvProfileContractError(
          "The profile service returned an empty or non-object JSON body.",
          { status: response.status },
        );
      }
      return payload;
    }

    /*
     * The engine has no route yet. This client is ready for the documented
     * one: a same-origin POST with the transport response of this session.
     */
    createProfile(job, { signal } = {}) {
      let body;
      try {
        body = JSON.stringify(buildProfileRequest(job));
      } catch (error) {
        return Promise.reject(error);
      }

      return this.request(this.path, {
        method: "POST",
        body,
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-JobLens-Request": this.requestToken,
        },
        signal,
      }).then((payload) =>
        normalizeProfileEnvelope(payload, { source: sourceFromJob(job) }),
      );
    }

    /* Static fixture read for the labelled synthetic preview. */
    async loadPreview(sourceUrl, envelopeUrl, { signal } = {}) {
      const [sourceRaw, envelopeRaw] = await Promise.all([
        this.fetchJson(sourceUrl, signal),
        this.fetchJson(envelopeUrl, signal),
      ]);
      return normalizePreviewEnvelope(envelopeRaw, sourceRaw);
    }

    async fetchJson(url, signal) {
      const response = await this.fetchImpl(url, {
        credentials: "same-origin",
        signal,
      });
      const text = await response.text();
      try {
        return JSON.parse(text);
      } catch {
        throw new CvProfileContractError(
          "The synthetic preview fixture is not valid JSON.",
        );
      }
    }
  }

  return Object.freeze({
    PROFILE_SCHEMA_VERSION,
    PARSER_SCHEMA_VERSION,
    CATEGORIES,
    SUPPORT_KINDS,
    DEGREE_LEVELS,
    NON_BLOCKING_CONFLICT_KINDS,
    PROPOSAL_STATUSES,
    SUPPORT_META,
    CATEGORY_META,
    FIELD_LABELS,
    CvProfileError,
    CvProfileContractError,
    CvProfileHttpError,
    CvProfileAdapter,
    normalizeProfileEnvelope,
    normalizePreviewEnvelope,
    normalizeLocator,
    describeValue,
    resolveEvidence,
    countProposals,
    buildSource,
    sourceFromJob,
    buildProfileRequest,
    codePoints,
    codePointLength,
    codePointSlice,
    fieldLabel,
  });
});
