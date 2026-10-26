"use strict";

/*
 * JobLens CV Evidence Workspace — API adapter
 *
 * Canonical parser schema: 1.1 (docs/cv-parser-api.md in the parser branch).
 * Provisional HTTP transport: 1.0 (docs/cv-workspace-contract.md).
 *
 * This file is the only place that knows the parser wire format. It does not
 * parse PDF or DOCX files, infer text, or repair parser output. It validates and
 * normalizes the canonical envelope so the UI can render honest states, and it
 * keeps the parser's original statuses, formats, identifiers, metadata, warnings
 * and locators alongside the visual statuses the UI uses.
 */
(function (global, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    global.JobLensCV = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const SCHEMA_VERSION = "1.1";
  const TRANSPORT_VERSION = "1.0";
  // Kept for the UI contract badge; it follows the parser schema version.
  const CONTRACT_VERSION = SCHEMA_VERSION;
  const MAX_DOCUMENTS = 5;
  const DEFAULT_API_BASE = "/api/cv";

  /*
   * The parser's default aggregate batch limit (ParseLimits.max_batch_bytes).
   * The transport accepts one more MiB for multipart framing, so a batch of
   * exactly this size still reaches the parser, which accepts it. Anything
   * above it is refused here, before a request is built, with the same code
   * the parser would use. Per-document limits stay the parser's decision.
   */
  const MAX_BATCH_BYTES = 25 * 1024 * 1024;

  const PDF_MIME = "application/pdf";
  const DOCX_MIME =
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

  const SUPPORTED_EXTENSIONS = Object.freeze([".pdf", ".docx"]);
  const SUPPORTED_MIME_TYPES = Object.freeze({
    [PDF_MIME]: "pdf",
    [DOCX_MIME]: "docx",
  });

  // Parser batch statuses (schema 1.1). All three are terminal outcomes.
  const BATCH_STATUSES = Object.freeze(["completed", "partial", "rejected"]);

  // Parser document statuses (schema 1.1).
  const PARSER_DOCUMENT_STATUSES = Object.freeze([
    "extracted",
    "partial",
    "empty",
    "scanned_pdf",
    "encrypted",
    "malformed",
    "unsupported_format",
    "too_large",
  ]);

  const DOCUMENT_FORMATS = Object.freeze(["pdf", "docx", "unknown"]);

  const STATUS_COUNT_KEYS = Object.freeze([...PARSER_DOCUMENT_STATUSES]);

  const LIMIT_KEYS = Object.freeze([
    "max_documents",
    "max_file_bytes",
    "max_batch_bytes",
    "max_text_chars",
    "max_pdf_pages",
    "max_docx_paragraphs",
    "max_docx_xml_bytes",
  ]);

  const BATCH_ERROR_CODES = Object.freeze([
    "empty_batch",
    "too_many_documents",
    "batch_too_large",
  ]);

  // Visual statuses the workspace renders. The parser status is always kept
  // alongside them; this map never claims text that the parser did not return.
  const PARSER_DOCUMENT_STATUS_TO_VISUAL = Object.freeze({
    extracted: "extracted",
    partial: "needs_review",
    empty: "failed",
    scanned_pdf: "failed",
    encrypted: "failed",
    malformed: "failed",
    unsupported_format: "failed",
    too_large: "failed",
  });

  const BATCH_STATUS_TO_VISUAL = Object.freeze({
    completed: "complete",
    partial: "partial",
  });

  // Kept for adapters/pages that still render the visual status vocabulary.
  const JOB_STATUSES = Object.freeze([
    "queued",
    "processing",
    "complete",
    "partial",
    "failed",
  ]);
  const TERMINAL_JOB_STATUSES = Object.freeze(["complete", "partial", "failed"]);
  const DOCUMENT_STATUSES = Object.freeze([
    "queued",
    "processing",
    "extracted",
    "needs_review",
    "failed",
  ]);

  const DOCUMENT_STATUS_META = Object.freeze({
    queued: {
      label: "Queued",
      tone: "neutral",
      description: "Waiting for the parser.",
    },
    processing: {
      label: "Extracting",
      tone: "active",
      description: "The parser is working on this document.",
    },
    extracted: {
      label: "Extracted",
      tone: "ok",
      description: "The parser returned complete text for this document.",
    },
    needs_review: {
      label: "Needs review",
      tone: "warn",
      description:
        "The parser returned incomplete text with warnings. Inspect the source before trusting it.",
    },
    failed: {
      label: "Failed",
      tone: "error",
      description: "The parser returned no usable text for this document.",
    },
  });

  const JOB_STATUS_META = Object.freeze({
    queued: {
      label: "Queued",
      tone: "neutral",
      description: "The parser accepted the job and has not started it yet.",
    },
    processing: {
      label: "Processing",
      tone: "active",
      description: "The parser is still working.",
    },
    complete: {
      label: "Complete",
      tone: "ok",
      description: "Every document was extracted completely.",
    },
    partial: {
      label: "Partial",
      tone: "warn",
      description:
        "Processing finished, but at least one document is incomplete. Inspect it before use.",
    },
    failed: {
      label: "Failed",
      tone: "error",
      description: "The extraction job failed.",
    },
  });

  class CvError extends Error {
    constructor(message, { code = "cv_error", details = null } = {}) {
      super(message);
      this.name = "CvError";
      this.code = code;
      this.details = details;
    }
  }

  class CvContractError extends CvError {
    constructor(message, details = null) {
      super(message, { code: "contract_error", details });
      this.name = "CvContractError";
    }
  }

  class CvHttpError extends CvError {
    constructor(status, message, details = null) {
      super(message, { code: "http_error", details });
      this.name = "CvHttpError";
      this.status = status;
    }
  }

  class CvTimeoutError extends CvError {
    constructor(message, details = null) {
      super(message, { code: "timeout", details });
      this.name = "CvTimeoutError";
    }
  }

  /*
   * A rejected batch is a defined parser outcome, not a transport failure.
   * Its `code` stays the parser code (empty_batch, too_many_documents,
   * batch_too_large), so callers can act on it without inventing a mapping.
   */
  class CvBatchRejectedError extends CvError {
    constructor(message, { code = "rejected_batch", details = null } = {}) {
      super(message, { code, details });
      this.name = "CvBatchRejectedError";
    }
  }

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function fail(path, message) {
    throw new CvContractError(`${path}: ${message}`, { path });
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

  function readCount(value, path) {
    if (!Number.isInteger(value) || value < 0) {
      fail(path, "expected a non-negative integer");
    }
    return value;
  }

  function readOptionalCount(value, path) {
    if (value === undefined || value === null) return null;
    return readCount(value, path);
  }

  function requireObject(value, path) {
    if (!isPlainObject(value)) fail(path, "expected an object");
    return value;
  }

  function detectKindFromFilename(filename) {
    const name = String(filename || "").toLowerCase();
    if (name.endsWith(".pdf")) return "pdf";
    if (name.endsWith(".docx")) return "docx";
    return null;
  }

  function detectKindFromMime(mediaType) {
    if (!mediaType) return null;
    return SUPPORTED_MIME_TYPES[String(mediaType).split(";")[0].trim()] || null;
  }

  function detectDocumentKind(file) {
    return detectKindFromFilename(file?.name) || detectKindFromMime(file?.type);
  }

  function formatBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes < 0) return "Size not reported";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) {
      return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
    }
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function countWords(text) {
    const value = String(text || "").trim();
    if (!value) return 0;
    return value.split(/\s+/u).length;
  }

  /* The aggregate size of the selected documents, in bytes. */
  function totalBytesOf(files) {
    return Array.from(files || []).reduce((total, entry) => {
      const size = Number(entry?.size);
      return total + (Number.isFinite(size) && size > 0 ? size : 0);
    }, 0);
  }

  /*
   * The chip carries the primary reference (page or paragraph); the context
   * carries the secondary one. Schema 1.1 gives DOCX paragraphs a `section`
   * instead of a page, so the section is the context of a paragraph reference.
   */
  function formatLocator(locator) {
    if (!locator) return "No reference";
    if (locator.kind === "page") return `Page ${locator.page}`;
    if (locator.kind === "paragraph") return `Paragraph ${locator.paragraph}`;
    return "No reference";
  }

  function formatLocatorContext(locator) {
    if (!locator) return "";
    if (locator.kind === "paragraph" && locator.section) {
      return locator.section;
    }
    return "";
  }

  function validateFiles(files, options = {}) {
    const maxDocuments = options.maxDocuments ?? MAX_DOCUMENTS;
    const existingCount = options.existingCount ?? 0;
    const accepted = [];
    const rejected = [];
    let slots = Math.max(0, maxDocuments - existingCount);

    for (const file of Array.from(files || [])) {
      const name = typeof file?.name === "string" ? file.name.trim() : "";
      if (!name) {
        rejected.push({
          file,
          name: "",
          code: "missing_name",
          message: "A selected file has no usable filename.",
        });
        continue;
      }

      const kind = detectDocumentKind(file);
      if (!kind) {
        rejected.push({
          file,
          name,
          code: "unsupported_type",
          message: `“${name}” is not a PDF or DOCX file.`,
        });
        continue;
      }

      const size = Number(file.size);
      if (!Number.isFinite(size) || size <= 0) {
        rejected.push({
          file,
          name,
          code: "empty_file",
          message: `“${name}” is empty. Choose a file with content.`,
        });
        continue;
      }

      if (slots <= 0) {
        rejected.push({
          file,
          name,
          code: "too_many",
          message: `“${name}” was not added. The workspace accepts up to ${maxDocuments} documents.`,
        });
        continue;
      }

      accepted.push(file);
      slots -= 1;
    }

    return {
      accepted,
      rejected,
      maxDocuments,
      remainingSlots: slots,
      atLimit: slots === 0,
    };
  }

  /*
   * Locators are preserved exactly as the parser shapes them:
   *   PDF:    { kind: "page", page: 3 }
   *   DOCX:   { kind: "paragraph", paragraph: 4, section: "Experience" }
   * `section` is kept verbatim (string or null) and never invented.
   */
  function normalizeLocator(raw, path, { required = true } = {}) {
    let value = raw?.locator ?? raw?.reference ?? null;
    if (
      value === undefined ||
      value === null ||
      (isPlainObject(value) && Object.keys(value).length === 0)
    ) {
      if (raw && (raw.page !== undefined || raw.paragraph !== undefined)) {
        value = raw;
      }
    }

    if (value === undefined || value === null) {
      if (required) fail(path, "page or paragraph reference is required");
      return null;
    }
    if (!isPlainObject(value)) fail(path, "expected an object");

    const kind =
      value.kind ||
      (value.page !== undefined
        ? "page"
        : value.paragraph !== undefined
          ? "paragraph"
          : null);

    if (kind === "page") {
      const page = value.page;
      if (!Number.isInteger(page) || page < 1) {
        fail(`${path}.page`, "expected a 1-based page number");
      }
      return { kind: "page", page, paragraph: null, section: null };
    }

    if (kind === "paragraph") {
      const paragraph = value.paragraph;
      if (!Number.isInteger(paragraph) || paragraph < 1) {
        fail(`${path}.paragraph`, "expected a 1-based paragraph number");
      }
      return {
        kind: "paragraph",
        paragraph,
        page: null,
        section: readOptionalString(value.section, `${path}.section`),
      };
    }

    fail(`${path}.kind`, "expected “page” or “paragraph”");
  }

  /*
   * Canonical warnings are { code, message }. The code list is open, so unknown
   * codes are preserved and rendered from their message. The schema does not
   * define severity or a locator, so neither is fabricated; if a future schema
   * adds them they are passed through unchanged.
   */
  function normalizeWarning(raw, path) {
    requireObject(raw, path);
    const code = readString(raw.code, `${path}.code`);
    const message = readString(raw.message, `${path}.message`);
    const severity =
      typeof raw.severity === "string" && raw.severity ? raw.severity : null;
    return {
      code,
      message,
      severity,
      locator: raw.locator ? normalizeLocator(raw, path, { required: false }) : null,
    };
  }

  function normalizeBatchError(raw, path) {
    if (raw === undefined || raw === null) return null;
    requireObject(raw, path);
    return {
      code: readString(raw.code, `${path}.code`),
      message: readString(raw.message, `${path}.message`),
    };
  }

  function normalizeMetadata(raw, path) {
    requireObject(raw, path);
    return {
      size_bytes: readCount(raw.size_bytes, `${path}.size_bytes`),
      page_count: readOptionalCount(raw.page_count, `${path}.page_count`),
      paragraph_count: readOptionalCount(
        raw.paragraph_count,
        `${path}.paragraph_count`,
      ),
    };
  }

  function normalizeStatusCounts(raw, path) {
    requireObject(raw, path);
    const counts = {};
    for (const status of STATUS_COUNT_KEYS) {
      if (!(status in raw)) fail(path, `missing status count “${status}”`);
      counts[status] = readCount(raw[status], `${path}.${status}`);
    }
    return counts;
  }

  function normalizeLimits(raw, path) {
    requireObject(raw, path);
    const limits = {};
    for (const key of LIMIT_KEYS) {
      const value = raw[key];
      if (!Number.isInteger(value) || value <= 0) {
        fail(`${path}.${key}`, "expected a positive integer");
      }
      limits[key] = value;
    }
    return limits;
  }

  function normalizeSegment(raw, index, documentId, path) {
    requireObject(raw, path);
    const text = readString(raw.text, `${path}.text`, { allowEmpty: true });
    return {
      id: `${documentId}:s${index + 1}`,
      text,
      locator: normalizeLocator(raw, path, { required: true }),
      wordCount: countWords(text),
    };
  }

  function mediaTypeForFormat(format) {
    if (format === "pdf") return PDF_MIME;
    if (format === "docx") return DOCX_MIME;
    return null;
  }

  function normalizeDocument(raw, position) {
    const path = `documents[${position}]`;
    requireObject(raw, path);

    // Identifier is provided by the HTTP transport, not derived by the UI.
    const id = readString(raw.document_id, `${path}.document_id`);
    const index = readCount(raw.index, `${path}.index`);
    const filename = readString(raw.filename, `${path}.filename`);
    const format = readString(raw.format, `${path}.format`);
    if (!DOCUMENT_FORMATS.includes(format)) {
      fail(`${path}.format`, `unknown document format “${format}”`);
    }

    const status = readString(raw.status, `${path}.status`);
    if (!PARSER_DOCUMENT_STATUSES.includes(status)) {
      fail(`${path}.status`, `unknown document status “${status}”`);
    }

    const text = readString(raw.text, `${path}.text`, { allowEmpty: true });

    const segmentsRaw = raw.segments;
    if (!Array.isArray(segmentsRaw)) {
      fail(`${path}.segments`, "expected an array");
    }
    const segments = segmentsRaw.map((segment, segmentIndex) =>
      normalizeSegment(segment, segmentIndex, id, `${path}.segments[${segmentIndex}]`),
    );

    const joined = segments.map((segment) => segment.text).join("\n\n");
    if (text !== joined) {
      fail(`${path}.text`, "does not match the concatenated segment text");
    }

    const metadata = normalizeMetadata(raw.metadata, `${path}.metadata`);
    if (!Array.isArray(raw.warnings)) {
      fail(`${path}.warnings`, "expected an array");
    }
    const warnings = raw.warnings.map((warning, warningIndex) =>
      normalizeWarning(warning, `${path}.warnings[${warningIndex}]`),
    );

    const visualStatus = PARSER_DOCUMENT_STATUS_TO_VISUAL[status];
    const kind = DOCUMENT_FORMATS.includes(format) ? format : "unknown";

    return {
      id,
      index,
      filename,
      format,
      kind,
      mediaType: mediaTypeForFormat(format),
      // Visual status for the workspace, original parser status kept beside it.
      status: visualStatus,
      parserStatus: status,
      sizeBytes: metadata.size_bytes,
      pageCount: metadata.page_count,
      paragraphCount: metadata.paragraph_count,
      metadata,
      warnings,
      error: null,
      fullText: text,
      segments,
    };
  }

  function normalizeBatch(raw, path) {
    requireObject(raw, path);
    const status = readString(raw.status, `${path}.status`);
    if (!BATCH_STATUSES.includes(status)) {
      fail(`${path}.status`, `unknown batch status “${status}”`);
    }
    return {
      status,
      documentCount: readCount(raw.document_count, `${path}.document_count`),
      totalBytes: readCount(raw.total_bytes, `${path}.total_bytes`),
      statusCounts: normalizeStatusCounts(raw.status_counts, `${path}.status_counts`),
      limits: normalizeLimits(raw.limits, `${path}.limits`),
      error: normalizeBatchError(raw.error, `${path}.error`),
    };
  }

  /*
   * A rejected batch is not a batch with results: nothing was processed, so it
   * carries no documents and no status counts. It does keep the number of
   * documents that were submitted and the parser's own error code and message.
   * Nothing here is rewritten and no placeholder document is created.
   */
  function readRejectedBatch(batch, documents, jobId) {
    if (documents.length) {
      fail("documents", "a rejected batch must return no documents");
    }

    const processed = STATUS_COUNT_KEYS.reduce(
      (total, status) => total + batch.statusCounts[status],
      0,
    );
    if (processed !== 0) {
      fail("batch.status_counts", "a rejected batch must not count a processed document");
    }

    if (!isPlainObject(batch.error)) {
      fail("batch.error", "a rejected batch must report an error");
    }

    const code = readString(batch.error.code, "batch.error.code");
    const message = readString(batch.error.message, "batch.error.message");

    return {
      code,
      message,
      jobId: jobId ?? null,
      // The submitted count and size are kept exactly as the parser reported.
      documentCount: batch.documentCount,
      totalBytes: batch.totalBytes,
      statusCounts: batch.statusCounts,
      limits: batch.limits,
    };
  }

  function rejectedBatchError(rejection, details = {}) {
    return new CvBatchRejectedError(rejection.message, {
      code: rejection.code,
      details: {
        jobId: rejection.jobId,
        batch: "rejected",
        error: { code: rejection.code, message: rejection.message },
        documentCount: rejection.documentCount,
        totalBytes: rejection.totalBytes,
        statusCounts: rejection.statusCounts,
        limits: rejection.limits,
        ...details,
      },
    });
  }

  function normalizeBatchEnvelope(raw) {
    requireObject(raw, "response");

    const schemaVersion = readString(raw.schema_version, "schema_version");
    if (schemaVersion !== SCHEMA_VERSION) {
      throw new CvContractError(
        `Unsupported parser schema_version “${schemaVersion}”. This adapter supports “${SCHEMA_VERSION}”.`,
        { schemaVersion, supported: SCHEMA_VERSION },
      );
    }

    const transportVersion = readString(
      raw.transport_version,
      "transport_version",
    );
    if (transportVersion !== TRANSPORT_VERSION) {
      throw new CvContractError(
        `Unsupported transport_version “${transportVersion}”. This adapter supports “${TRANSPORT_VERSION}”.`,
        { transportVersion, supported: TRANSPORT_VERSION },
      );
    }

    const jobId = readString(raw.job_id, "job_id");
    const batch = normalizeBatch(raw.batch, "batch");

    if (!Array.isArray(raw.documents)) {
      fail("documents", "expected an array");
    }
    const documents = raw.documents.map((document, index) =>
      normalizeDocument(document, index),
    );

    // A rejected batch is validated on its own terms: no documents, no
    // processed counts, and the submitted document count is kept as it is.
    if (batch.status === "rejected") {
      throw rejectedBatchError(readRejectedBatch(batch, documents, jobId));
    }

    if (batch.documentCount !== documents.length) {
      fail(
        "batch.document_count",
        `expected ${documents.length} to match documents.length`,
      );
    }

    const counted = STATUS_COUNT_KEYS.reduce(
      (total, status) => total + batch.statusCounts[status],
      0,
    );
    if (counted !== documents.length) {
      fail(
        "batch.status_counts",
        `expected counts to sum to ${documents.length}`,
      );
    }

    if (batch.error) {
      fail("batch.error", "expected null for a completed or partial batch");
    }

    const jobStatus = BATCH_STATUS_TO_VISUAL[batch.status];
    if (!jobStatus) {
      fail("batch.status", `no visual status for “${batch.status}”`);
    }

    return {
      id: jobId,
      // Visual status plus the original parser batch status.
      status: jobStatus,
      parserStatus: batch.status,
      schemaVersion,
      transportVersion,
      contractVersion: schemaVersion,
      contractVersionMatches: schemaVersion === CONTRACT_VERSION,
      documentCount: batch.documentCount,
      totalBytes: batch.totalBytes,
      statusCounts: batch.statusCounts,
      limits: batch.limits,
      batchError: batch.error,
      warnings: [],
      error: null,
      documents,
    };
  }

  function isTerminalJobStatus(status) {
    return TERMINAL_JOB_STATUSES.includes(status);
  }

  function summarizeExtraction(job) {
    const documents = Array.isArray(job?.documents) ? job.documents : [];
    const summary = {
      total: documents.length,
      extracted: 0,
      needsReview: 0,
      failed: 0,
      pending: 0,
      finished: 0,
      warnings: 0,
      segments: 0,
    };

    for (const document of documents) {
      summary.segments += Array.isArray(document.segments)
        ? document.segments.length
        : 0;
      summary.warnings += Array.isArray(document.warnings)
        ? document.warnings.length
        : 0;

      if (document.status === "extracted") summary.extracted += 1;
      else if (document.status === "needs_review") summary.needsReview += 1;
      else if (document.status === "failed") summary.failed += 1;
      else summary.pending += 1;
    }

    summary.finished =
      summary.extracted + summary.needsReview + summary.failed;
    return summary;
  }

  function abortError() {
    if (typeof DOMException === "function") {
      return new DOMException("The request was aborted.", "AbortError");
    }
    const error = new Error("The request was aborted.");
    error.name = "AbortError";
    return error;
  }

  function delay(milliseconds, signal) {
    return new Promise((resolve, reject) => {
      if (signal?.aborted) {
        reject(abortError());
        return;
      }

      const timer = setTimeout(() => {
        cleanup();
        resolve();
      }, Math.max(0, milliseconds));

      function onAbort() {
        clearTimeout(timer);
        cleanup();
        reject(signal.reason || abortError());
      }

      function cleanup() {
        signal?.removeEventListener("abort", onAbort);
      }

      signal?.addEventListener("abort", onAbort, { once: true });
    });
  }

  class CvApiAdapter {
    constructor(options = {}) {
      this.baseUrl = String(options.baseUrl || DEFAULT_API_BASE).replace(/\/+$/, "");
      this.fetchImpl = options.fetchImpl || globalThis.fetch?.bind(globalThis);
      this.pollIntervalMs = options.pollIntervalMs ?? 1200;
      this.timeoutMs = options.timeoutMs ?? 120000;
      this.now = options.now || (() => Date.now());
      this.requestToken = options.requestToken || "1";

      if (typeof this.fetchImpl !== "function") {
        throw new CvError("This browser cannot call the extraction service.", {
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
        throw new CvError(
          `Could not reach the extraction service. ${error?.message || "The request failed."}`,
          { code: "network_error", details: error },
        );
      }

      const text = await response.text();
      let payload = null;
      if (text) {
        try {
          payload = JSON.parse(text);
        } catch {
          throw new CvContractError(
            `The extraction service returned HTTP ${response.status} with a non-JSON body.`,
            { status: response.status },
          );
        }
      }

      if (!response.ok) {
        // A rejected batch arrives as an error response that still carries the
        // parser object. It is validated exactly like a direct normalization,
        // so the original code, message and submitted count survive.
        if (isPlainObject(payload?.batch) && payload.batch.status === "rejected") {
          const batch = normalizeBatch(payload.batch, "batch");
          const documents = Array.isArray(payload.documents) ? payload.documents : [];
          const rejection = readRejectedBatch(
            batch,
            documents,
            typeof payload.job_id === "string" ? payload.job_id : null,
          );
          throw rejectedBatchError(rejection, { status: response.status });
        }

        const rawError = payload?.error;
        const code = isPlainObject(rawError)
          ? rawError.code
          : (payload?.code ?? null);
        const message =
          (isPlainObject(rawError) ? rawError.message : rawError) ||
          payload?.message ||
          `The extraction service returned HTTP ${response.status}.`;

        // A rejected batch is a parser outcome, not a transport failure. Keep
        // the parser's own error code instead of collapsing it to http_error.
        if (BATCH_ERROR_CODES.includes(code)) {
          throw new CvBatchRejectedError(String(message), {
            code,
            details: { status: response.status, payload },
          });
        }

        throw new CvHttpError(response.status, String(message), {
          code,
          payload,
        });
      }

      if (!isPlainObject(payload)) {
        throw new CvContractError(
          "The extraction service returned an empty or non-object JSON body.",
          { status: response.status },
        );
      }
      return payload;
    }

    createExtraction(files, { signal } = {}) {
      const list = Array.from(files || []);
      if (!list.length) {
        return Promise.reject(
          new CvError("Choose at least one document before extracting.", {
            code: "no_documents",
          }),
        );
      }
      if (list.length > MAX_DOCUMENTS) {
        return Promise.reject(
          new CvError(
            `The workspace accepts up to ${MAX_DOCUMENTS} documents at a time.`,
            { code: "too_many_documents" },
          ),
        );
      }

      // The aggregate size is checked before a request is built, so an
      // oversized selection never reaches the network. The parser applies the
      // same limit and stays authoritative for it.
      const totalBytes = totalBytesOf(list);
      if (totalBytes > MAX_BATCH_BYTES) {
        const limitMiB = Math.round(MAX_BATCH_BYTES / (1024 * 1024));
        return Promise.reject(
          new CvError(
            `The selected documents total ${formatBytes(totalBytes)}, which is over the ${limitMiB} MiB batch limit. Remove a document or use smaller files and try again.`,
            {
              code: "batch_too_large",
              details: { totalBytes, maxBatchBytes: MAX_BATCH_BYTES },
            },
          ),
        );
      }

      const body = new FormData();
      for (const file of list) {
        body.append("files", file, file.name || "document");
      }

      return this.request("/extractions", {
        method: "POST",
        body,
        headers: {
          Accept: "application/json",
          "X-JobLens-Request": this.requestToken,
        },
        signal,
      }).then(normalizeBatchEnvelope);
    }

    getExtraction(jobId, { signal } = {}) {
      if (typeof jobId !== "string" || !jobId.trim()) {
        return Promise.reject(
          new CvContractError("A job id is required to fetch the extraction."),
        );
      }
      return this.request(`/extractions/${encodeURIComponent(jobId)}`, {
        headers: { Accept: "application/json" },
        signal,
      }).then(normalizeBatchEnvelope);
    }

    /*
     * Schema 1.1 batches are terminal, so the POST response is normally the
     * final answer and this is not needed. It stays for transports that might
     * return a known terminal envelope over GET, and to keep the public adapter
     * surface stable. A rejected batch still surfaces as an error.
     */
    async waitForExtraction(jobId, { onUpdate, signal } = {}) {
      const deadline = this.now() + this.timeoutMs;

      for (;;) {
        const job = await this.getExtraction(jobId, { signal });
        if (typeof onUpdate === "function") onUpdate(job);
        if (isTerminalJobStatus(job.status)) return job;

        if (this.now() >= deadline) {
          throw new CvTimeoutError(
            `The parser did not finish within ${Math.round(this.timeoutMs / 1000)} seconds.`,
            { jobId, timeoutMs: this.timeoutMs },
          );
        }
        await delay(this.pollIntervalMs, signal);
      }
    }

    async parseJob(jobPosting, { signal } = {}) {
      const body = JSON.stringify({
        title: jobPosting?.title || null,
        company: jobPosting?.company || null,
        location: jobPosting?.location || null,
        text: jobPosting?.text || "",
      });
      return this.request("/jobs", {
        method: "POST",
        body,
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-JobLens-Request": this.requestToken,
        },
        signal,
      });
    }

    async validateApprovedProfile(job, approvedProfile, { signal } = {}) {
      const source = approvedProfile.source || globalThis.JobLensProfileAdapter.buildProfileRequest(job);
      const body = JSON.stringify({ ...source, approved_profile: approvedProfile, confirmed: true });
      return this.request("/approved-profiles", {
        method: "POST",
        body,
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-JobLens-Request": this.requestToken,
        },
        signal,
      });
    }

    async generateDraft(approvedProfile, jobPosting, source, { signal } = {}) {
      const body = JSON.stringify({
        approved_profile: approvedProfile,
        job_posting: {
          title: jobPosting?.title || null,
          company: jobPosting?.company || null,
          location: jobPosting?.location || null,
          raw_text: jobPosting?.text || "",
        },
        source: source || null,
      });
      return this.request("/cv-drafts", {
        method: "POST",
        body,
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-JobLens-Request": this.requestToken,
        },
        signal,
      });
    }

    async editDraftItem(draft, itemId, text, { signal } = {}) {
      const body = JSON.stringify({ draft, item_id: itemId, text });
      return this.request("/cv-drafts/edit", {
        method: "POST",
        body,
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-JobLens-Request": this.requestToken,
        },
        signal,
      });
    }

    async approveDraftItem(draft, itemId, { signal } = {}) {
      const body = JSON.stringify({ draft, item_id: itemId, confirmed: true, attested: true });
      return this.request("/cv-drafts/approve", {
        method: "POST",
        body,
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-JobLens-Request": this.requestToken,
        },
        signal,
      });
    }

    async exportPdf(draft, approvedProfile, { signal } = {}) {
      const body = JSON.stringify({ draft, approved_profile: approvedProfile, confirmed: true, contact: draft.candidate });
      const response = await this.fetchImpl(this.endpoint("/cv-drafts/export/pdf"), {
        method: "POST",
        body,
        headers: {
          "Content-Type": "application/json",
          "X-JobLens-Request": this.requestToken,
          Accept: "application/pdf",
        },
        signal,
        credentials: "same-origin",
      });
      if (!response.ok) {
        let message = `Export failed (HTTP ${response.status}).`;
        try {
          const p = await response.json();
          message = (p?.error?.message || p?.message || message);
        } catch {}
        throw new CvHttpError(response.status, message, { payload: null });
      }
      const blob = await response.blob();
      return blob;
    }

    async exportDocx(draft, approvedProfile, { signal } = {}) {
      const body = JSON.stringify({ draft, approved_profile: approvedProfile, confirmed: true, contact: draft.candidate });
      const response = await this.fetchImpl(this.endpoint("/cv-drafts/export/docx"), {
        method: "POST",
        body,
        headers: {
          "Content-Type": "application/json",
          "X-JobLens-Request": this.requestToken,
          Accept: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
        signal,
        credentials: "same-origin",
      });
      if (!response.ok) {
        let message = `Export failed (HTTP ${response.status}).`;
        try {
          const p = await response.json();
          message = (p?.error?.message || p?.message || message);
        } catch {}
        throw new CvHttpError(response.status, message, { payload: null });
      }
      const blob = await response.blob();
      return blob;
    }
  }

  return Object.freeze({
    SCHEMA_VERSION,
    TRANSPORT_VERSION,
    CONTRACT_VERSION,
    MAX_DOCUMENTS,
    MAX_BATCH_BYTES,
    DEFAULT_API_BASE,
    PDF_MIME,
    DOCX_MIME,
    SUPPORTED_EXTENSIONS,
    SUPPORTED_MIME_TYPES,
    BATCH_STATUSES,
    PARSER_DOCUMENT_STATUSES,
    DOCUMENT_FORMATS,
    STATUS_COUNT_KEYS,
    LIMIT_KEYS,
    BATCH_ERROR_CODES,
    PARSER_DOCUMENT_STATUS_TO_VISUAL,
    BATCH_STATUS_TO_VISUAL,
    JOB_STATUSES,
    DOCUMENT_STATUSES,
    DOCUMENT_STATUS_META,
    JOB_STATUS_META,
    CvError,
    CvContractError,
    CvHttpError,
    CvTimeoutError,
    CvBatchRejectedError,
    CvApiAdapter,
    validateFiles,
    normalizeBatchEnvelope,
    normalizeLocator,
    summarizeExtraction,
    isTerminalJobStatus,
    formatBytes,
    formatLocator,
    formatLocatorContext,
    countWords,
    totalBytesOf,
    detectDocumentKind,
  });
});
