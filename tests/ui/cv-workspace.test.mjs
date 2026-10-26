import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const require = createRequire(import.meta.url);
const HERE = dirname(fileURLToPath(import.meta.url));
const WORKSPACE = join(HERE, "..", "..", "web", "workspace");
const cv = require(join(WORKSPACE, "api-adapter.js"));

function fixture(name) {
  return JSON.parse(readFileSync(join(WORKSPACE, "fixtures", `${name}.json`), "utf8"));
}

function file(name, size = 1024, type = "") {
  return { name, size, type };
}

// FormData.append requires a real Blob/File, unlike the plain objects the
// validation helpers accept.
function blobFile(name, size = 1024, type = "") {
  return new File([new Uint8Array(size)], name, { type });
}

function jsonResponse(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(payload),
  };
}

function textResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => body,
  };
}

const LIMITS = {
  max_documents: 5,
  max_file_bytes: 10485760,
  max_batch_bytes: 26214400,
  max_text_chars: 200000,
  max_pdf_pages: 100,
  max_docx_paragraphs: 20000,
  max_docx_xml_bytes: 10485760,
};

const STATUS_KEYS = [
  "extracted",
  "partial",
  "empty",
  "scanned_pdf",
  "encrypted",
  "malformed",
  "unsupported_format",
  "too_large",
];

/* A minimal valid envelope, so negative tests can break exactly one field. */
function envelope(overrides = {}) {
  const base = {
    schema_version: "1.1",
    transport_version: "1.0",
    job_id: "job-test",
    batch: {
      status: "completed",
      document_count: 1,
      total_bytes: 1024,
      status_counts: Object.fromEntries(
        STATUS_KEYS.map((status) => [status, status === "extracted" ? 1 : 0]),
      ),
      limits: { ...LIMITS },
      error: null,
    },
    documents: [
      {
        document_id: "doc-test-0",
        index: 0,
        filename: "sample-cv.pdf",
        format: "pdf",
        status: "extracted",
        text: "Extracted text.",
        segments: [
          { locator: { kind: "page", page: 1 }, text: "Extracted text." },
        ],
        warnings: [],
        metadata: { size_bytes: 1024, page_count: 1, paragraph_count: null },
      },
    ],
  };
  return { ...base, ...overrides };
}

function documentEnvelope(overrides = {}) {
  const payload = envelope();
  return { ...payload, documents: [{ ...payload.documents[0], ...overrides }] };
}

test("the public adapter surface used by app.js is preserved", () => {
  for (const name of [
    "SCHEMA_VERSION",
    "TRANSPORT_VERSION",
    "CONTRACT_VERSION",
    "MAX_DOCUMENTS",
    "MAX_BATCH_BYTES",
    "DEFAULT_API_BASE",
    "PDF_MIME",
    "DOCX_MIME",
    "SUPPORTED_EXTENSIONS",
    "SUPPORTED_MIME_TYPES",
    "BATCH_STATUSES",
    "PARSER_DOCUMENT_STATUSES",
    "DOCUMENT_FORMATS",
    "DOCUMENT_STATUS_META",
    "JOB_STATUS_META",
    "CvError",
    "CvContractError",
    "CvHttpError",
    "CvTimeoutError",
    "CvBatchRejectedError",
    "CvApiAdapter",
    "validateFiles",
    "normalizeBatchEnvelope",
    "summarizeExtraction",
    "isTerminalJobStatus",
    "formatBytes",
    "formatLocator",
    "formatLocatorContext",
    "countWords",
    "totalBytesOf",
    "detectDocumentKind",
  ]) {
    assert.ok(cv[name] !== undefined, name);
  }

  assert.equal(cv.SCHEMA_VERSION, "1.1");
  assert.equal(cv.TRANSPORT_VERSION, "1.0");
  assert.equal(cv.CONTRACT_VERSION, "1.1");
  // The frontend batch limit matches the parser's default max_batch_bytes.
  assert.equal(cv.MAX_BATCH_BYTES, 25 * 1024 * 1024);
});

test("validateFiles accepts supported files and counts remaining slots", () => {
  const result = cv.validateFiles([
    file("a.pdf", 2048, "application/pdf"),
    file("b.docx", 4096),
  ]);

  assert.equal(result.accepted.length, 2);
  assert.equal(result.rejected.length, 0);
  assert.equal(result.remainingSlots, cv.MAX_DOCUMENTS - 2);
  assert.equal(result.atLimit, false);
});

test("validateFiles rejects unsupported, empty and unnamed files with reasons", () => {
  const result = cv.validateFiles([
    file("notes.txt", 100, "text/plain"),
    file("empty.pdf", 0, "application/pdf"),
    file("", 100),
    file("ok.pdf", 500),
  ]);

  assert.deepEqual(
    result.accepted.map((entry) => entry.name),
    ["ok.pdf"],
  );
  assert.deepEqual(
    result.rejected.map((entry) => entry.code),
    ["unsupported_type", "empty_file", "missing_name"],
  );
  for (const rejection of result.rejected) {
    assert.ok(rejection.message.length > 0);
  }
});

test("validateFiles enforces the five document limit across existing and new files", () => {
  const incoming = ["a.pdf", "b.pdf", "c.pdf", "d.pdf"].map((name) => file(name, 100));
  const result = cv.validateFiles(incoming, { existingCount: 3 });

  assert.deepEqual(
    result.accepted.map((entry) => entry.name),
    ["a.pdf", "b.pdf"],
  );
  assert.deepEqual(
    result.rejected.map((entry) => entry.code),
    ["too_many", "too_many"],
  );
  assert.equal(result.atLimit, true);
  assert.equal(result.maxDocuments, cv.MAX_DOCUMENTS);
});

test("detectDocumentKind uses the extension first and the MIME type second", () => {
  assert.equal(cv.detectDocumentKind(file("cv.PDF")), "pdf");
  assert.equal(cv.detectDocumentKind(file("cv.docx")), "docx");
  assert.equal(
    cv.detectDocumentKind(file("cv", 1, cv.DOCX_MIME)),
    "docx",
  );
  assert.equal(cv.detectDocumentKind(file("cv", 1, "text/plain")), null);
});

test("small helpers format bytes, locators and words deterministically", () => {
  assert.equal(cv.formatBytes(512), "512 B");
  assert.equal(cv.formatBytes(2048), "2.0 KB");
  assert.equal(cv.formatBytes(3 * 1024 * 1024), "3.0 MB");
  assert.equal(cv.formatBytes(-1), "Size not reported");

  assert.equal(cv.formatLocator({ kind: "page", page: 3 }), "Page 3");
  assert.equal(
    cv.formatLocator({ kind: "paragraph", paragraph: 12 }),
    "Paragraph 12",
  );
  assert.equal(
    cv.formatLocator({ kind: "paragraph", paragraph: 12, section: "Experience" }),
    "Paragraph 12",
  );
  assert.equal(cv.formatLocator(null), "No reference");
  assert.equal(
    cv.formatLocatorContext({ kind: "paragraph", paragraph: 2, section: "Portfolio" }),
    "Portfolio",
  );
  assert.equal(cv.formatLocatorContext({ kind: "page", page: 4 }), "");

  assert.equal(cv.countWords("two words"), 2);
  assert.equal(cv.countWords("   "), 0);
});

test("a completed batch keeps the transport identifiers and the batch diagnostics", () => {
  const job = cv.normalizeBatchEnvelope(fixture("batch-completed"));

  // Identifiers come from the transport, not from the client.
  assert.equal(job.id, "job-synthetic-completed");
  assert.equal(job.documents[0].id, "doc-synthetic-cv-0");
  assert.equal(job.documents[1].id, "doc-synthetic-letter-1");

  assert.equal(job.status, "complete");
  assert.equal(job.parserStatus, "completed");
  assert.equal(job.schemaVersion, "1.1");
  assert.equal(job.transportVersion, "1.0");
  assert.equal(job.contractVersion, "1.1");
  assert.equal(job.contractVersionMatches, true);
  assert.equal(job.documentCount, 2);
  assert.equal(job.totalBytes, 27360);
  assert.equal(job.batchError, null);
  assert.deepEqual(job.warnings, []);
  assert.equal(job.error, null);

  // Every parser status count is preserved, not just the ones that occurred.
  assert.deepEqual(Object.keys(job.statusCounts).sort(), [...STATUS_KEYS].sort());
  assert.equal(job.statusCounts.extracted, 2);
  assert.equal(job.statusCounts.too_large, 0);
  assert.deepEqual(job.limits, LIMITS);

  // The normalized job does not keep a deep copy of the raw response.
  assert.equal(job.raw, undefined);
});

test("document index, format, metadata and exact text are preserved", () => {
  const job = cv.normalizeBatchEnvelope(fixture("batch-completed"));
  const [cvDoc, letter] = job.documents;

  assert.equal(cvDoc.index, 0);
  assert.equal(letter.index, 1);
  assert.equal(cvDoc.filename, "sample-cv.pdf");
  assert.equal(cvDoc.format, "pdf");
  assert.equal(cvDoc.kind, "pdf");
  assert.equal(cvDoc.mediaType, cv.PDF_MIME);
  assert.equal(letter.format, "docx");
  assert.equal(letter.kind, "docx");
  assert.equal(letter.mediaType, cv.DOCX_MIME);

  assert.deepEqual(cvDoc.metadata, {
    size_bytes: 18240,
    page_count: 2,
    paragraph_count: null,
  });
  assert.equal(cvDoc.sizeBytes, 18240);
  assert.equal(cvDoc.pageCount, 2);
  assert.equal(cvDoc.paragraphCount, null);
  assert.equal(letter.paragraphCount, 5);
  assert.equal(letter.pageCount, null);

  const raw = fixture("batch-completed");
  assert.equal(cvDoc.fullText, raw.documents[0].text);
  assert.equal(letter.fullText, raw.documents[1].text);
});

test("every locator is preserved, including the DOCX section", () => {
  const job = cv.normalizeBatchEnvelope(fixture("batch-completed"));
  const [cvDoc, letter] = job.documents;

  assert.deepEqual(cvDoc.segments[0].locator, {
    kind: "page",
    page: 1,
    paragraph: null,
    section: null,
  });
  assert.deepEqual(cvDoc.segments[1].locator, {
    kind: "page",
    page: 2,
    paragraph: null,
    section: null,
  });
  assert.deepEqual(letter.segments[0].locator, {
    kind: "paragraph",
    paragraph: 1,
    page: null,
    section: null,
  });
  assert.deepEqual(letter.segments[1].locator, {
    kind: "paragraph",
    paragraph: 4,
    page: null,
    section: "Experience",
  });

  assert.deepEqual(
    cvDoc.segments.map((segment) => segment.id),
    ["doc-synthetic-cv-0:s1", "doc-synthetic-cv-0:s2"],
  );
  assert.ok(cvDoc.segments[0].wordCount > 0);
});

test("all eight parser document statuses map to the visual statuses", () => {
  const seen = new Map();

  for (const name of ["batch-completed", "batch-partial", "batch-status-coverage"]) {
    const job = cv.normalizeBatchEnvelope(fixture(name));
    for (const document of job.documents) {
      seen.set(document.parserStatus, document.status);
    }
  }

  assert.deepEqual([...seen.keys()].sort(), [...STATUS_KEYS].sort());
  assert.equal(seen.get("extracted"), "extracted");
  assert.equal(seen.get("partial"), "needs_review");
  assert.equal(seen.get("empty"), "failed");
  assert.equal(seen.get("scanned_pdf"), "failed");
  assert.equal(seen.get("encrypted"), "failed");
  assert.equal(seen.get("malformed"), "failed");
  assert.equal(seen.get("unsupported_format"), "failed");
  assert.equal(seen.get("too_large"), "failed");
});

test("a partial batch keeps the parser status and reports no text for failures", () => {
  const job = cv.normalizeBatchEnvelope(fixture("batch-partial"));
  const summary = cv.summarizeExtraction(job);

  assert.equal(job.status, "partial");
  assert.equal(job.parserStatus, "partial");
  assert.equal(summary.total, 5);
  assert.equal(summary.extracted, 1);
  assert.equal(summary.needsReview, 1);
  assert.equal(summary.failed, 3);
  assert.equal(summary.finished, 5);
  assert.equal(summary.pending, 0);

  const [, review, empty, scanned, encrypted] = job.documents;

  assert.equal(review.status, "needs_review");
  assert.equal(review.parserStatus, "partial");
  assert.equal(review.fullText.length > 0, true);
  assert.equal(review.segments.length, 1);

  for (const document of [empty, scanned, encrypted]) {
    assert.equal(document.status, "failed");
    assert.equal(document.fullText, "");
    assert.equal(document.segments.length, 0);
    assert.equal(document.error, null);
    assert.ok(document.warnings.length > 0);
  }

  assert.equal(empty.parserStatus, "empty");
  assert.equal(scanned.parserStatus, "scanned_pdf");
  assert.equal(encrypted.parserStatus, "encrypted");
});

test("warnings keep their code and never gain an invented severity or locator", () => {
  const job = cv.normalizeBatchEnvelope(fixture("batch-partial"));
  const warning = job.documents[1].warnings[0];

  assert.equal(warning.code, "text_truncated");
  assert.equal(typeof warning.message, "string");
  assert.ok(warning.message.length > 0);
  assert.equal(warning.severity, null);
  assert.equal(warning.locator, null);
});

test("document.format is the authority after extraction", () => {
  const job = cv.normalizeBatchEnvelope(fixture("batch-status-coverage"));
  const [mismatch] = job.documents;

  // The filename says PDF, the parser says DOCX.
  assert.equal(mismatch.filename, "sample-named-pdf.pdf");
  assert.equal(mismatch.format, "docx");
  assert.equal(mismatch.kind, "docx");
  assert.equal(mismatch.mediaType, cv.DOCX_MIME);
  assert.equal(mismatch.warnings[0].code, "format_mismatch");
  assert.equal(mismatch.warnings[0].severity, null);
});

test("unknown warning codes are preserved instead of being dropped", () => {
  const payload = documentEnvelope({
    warnings: [{ code: "a_code_this_build_has_never_seen", message: "Kept as is." }],
  });
  const job = cv.normalizeBatchEnvelope(payload);

  assert.equal(job.documents[0].warnings.length, 1);
  assert.equal(job.documents[0].warnings[0].code, "a_code_this_build_has_never_seen");
  assert.equal(job.documents[0].warnings[0].message, "Kept as is.");
  assert.equal(job.documents[0].warnings[0].severity, null);
  assert.equal(job.documents[0].warnings[0].locator, null);
});

test("a rejected batch is an error that keeps the parser code", () => {
  assert.throws(
    () => cv.normalizeBatchEnvelope(fixture("batch-rejected")),
    (error) => {
      assert.equal(error.name, "CvBatchRejectedError");
      assert.equal(error.code, "empty_batch");
      assert.match(error.message, /at least one document/);
      return true;
    },
  );
});

test("a rejected batch keeps the submitted document count and reports no results", () => {
  assert.throws(
    () => cv.normalizeBatchEnvelope(fixture("batch-rejected-too-large")),
    (error) => {
      assert.equal(error.name, "CvBatchRejectedError");
      assert.equal(error.code, "batch_too_large");
      assert.equal(error.message, "The batch exceeds the configured total size limit.");
      // The submitted count and size survive the rejection.
      assert.equal(error.details.documentCount, 3);
      assert.equal(error.details.totalBytes, 27262976);
      assert.equal(error.details.jobId, "job-synthetic-rejected-too-large");
      // Nothing was processed, so no document is invented.
      assert.deepEqual(error.details.statusCounts, {
        extracted: 0,
        partial: 0,
        empty: 0,
        scanned_pdf: 0,
        encrypted: 0,
        malformed: 0,
        unsupported_format: 0,
        too_large: 0,
      });
      return true;
    },
  );
});

test("a rejected batch must not carry documents or processed counts", () => {
  const withDocument = fixture("batch-rejected-too-large");
  withDocument.documents = [
    {
      document_id: "doc-should-not-exist",
      index: 0,
      filename: "sample-cv.pdf",
      format: "pdf",
      status: "extracted",
      text: "text",
      segments: [{ locator: { kind: "page", page: 1 }, text: "text" }],
      warnings: [],
      metadata: { size_bytes: 10, page_count: 1, paragraph_count: null },
    },
  ];
  assert.throws(
    () => cv.normalizeBatchEnvelope(withDocument),
    /documents: a rejected batch must return no documents/,
  );

  const withCounts = fixture("batch-rejected-too-large");
  withCounts.batch.status_counts.extracted = 1;
  assert.throws(
    () => cv.normalizeBatchEnvelope(withCounts),
    /batch.status_counts: a rejected batch must not count a processed document/,
  );

  const withoutError = fixture("batch-rejected-too-large");
  withoutError.batch.error = null;
  assert.throws(
    () => cv.normalizeBatchEnvelope(withoutError),
    /batch.error: a rejected batch must report an error/,
  );
});

test("a rejected batch answered with a non-2xx keeps its code and submitted count", async () => {
  const adapter = new cv.CvApiAdapter({
    fetchImpl: async () => jsonResponse(fixture("batch-rejected-too-large"), 413),
  });

  await assert.rejects(adapter.createExtraction([blobFile("a.pdf", 10)]), (error) => {
    assert.equal(error.name, "CvBatchRejectedError");
    assert.equal(error.code, "batch_too_large");
    assert.equal(error.message, "The batch exceeds the configured total size limit.");
    assert.equal(error.details.documentCount, 3);
    assert.equal(error.details.status, 413);
    return true;
  });
});

test("a raw 413 from the server keeps its transport error code", async () => {
  const adapter = new cv.CvApiAdapter({
    fetchImpl: async () =>
      jsonResponse(
        {
          transport_version: "1.0",
          schema_version: "1.1",
          job_id: "job-1",
          error: { code: "request_too_large", message: "The request exceeds the local size limit." },
          documents: [],
        },
        413,
      ),
  });

  await assert.rejects(adapter.createExtraction([blobFile("a.pdf", 10)]), (error) => {
    assert.equal(error.name, "CvHttpError");
    assert.equal(error.status, 413);
    assert.equal(error.details.code, "request_too_large");
    assert.match(error.message, /local size limit/);
    return true;
  });
});

test("a rejected batch stays an error when the transport answers with a non-2xx", async () => {
  const adapter = new cv.CvApiAdapter({
    fetchImpl: async () =>
      jsonResponse(
        { error: { code: "too_many_documents", message: "Too many documents." } },
        400,
      ),
  });

  await assert.rejects(adapter.createExtraction([blobFile("a.pdf", 10)]), (error) => {
    assert.equal(error.name, "CvBatchRejectedError");
    assert.equal(error.code, "too_many_documents");
    return true;
  });
});

test("the schema and transport versions are validated", () => {
  assert.throws(
    () => cv.normalizeBatchEnvelope(envelope({ schema_version: "1.0" })),
    (error) => {
      assert.equal(error.name, "CvContractError");
      assert.equal(error.code, "contract_error");
      assert.match(error.message, /schema_version/);
      return true;
    },
  );

  assert.throws(
    () => cv.normalizeBatchEnvelope(envelope({ transport_version: "2.0" })),
    (error) => {
      assert.equal(error.name, "CvContractError");
      assert.match(error.message, /transport_version/);
      return true;
    },
  );

  assert.throws(
    () => cv.normalizeBatchEnvelope(envelope({ schema_version: undefined })),
    /schema_version: expected a string/,
  );
});

test("the batch diagnostics are validated", () => {
  assert.throws(
    () => cv.normalizeBatchEnvelope(envelope({ job_id: "" })),
    /job_id: expected a non-empty string/,
  );

  assert.throws(
    () => cv.normalizeBatchEnvelope(envelope({ job_id: undefined })),
    /job_id: expected a string/,
  );

  const badStatus = envelope();
  badStatus.batch.status = "finished";
  assert.throws(() => cv.normalizeBatchEnvelope(badStatus), /unknown batch status/);

  const badCount = envelope();
  badCount.batch.document_count = 2;
  assert.throws(
    () => cv.normalizeBatchEnvelope(badCount),
    /document_count: expected 1 to match documents.length/,
  );

  const badCounts = envelope();
  badCounts.batch.status_counts.extracted = 3;
  assert.throws(
    () => cv.normalizeBatchEnvelope(badCounts),
    /status_counts: expected counts to sum to 1/,
  );

  const missingCountKey = envelope();
  delete missingCountKey.batch.status_counts.too_large;
  assert.throws(
    () => cv.normalizeBatchEnvelope(missingCountKey),
    /missing status count “too_large”/,
  );

  const errorOnComplete = envelope();
  errorOnComplete.batch.error = { code: "empty_batch", message: "nope" };
  assert.throws(
    () => cv.normalizeBatchEnvelope(errorOnComplete),
    /batch.error: expected null for a completed or partial batch/,
  );

  const badLimits = envelope();
  badLimits.batch.limits.max_file_bytes = 0;
  assert.throws(
    () => cv.normalizeBatchEnvelope(badLimits),
    /limits.max_file_bytes: expected a positive integer/,
  );
});

test("document fields are validated", () => {
  assert.throws(
    () => cv.normalizeBatchEnvelope(documentEnvelope({ document_id: undefined })),
    /document_id: expected a string/,
  );

  assert.throws(
    () => cv.normalizeBatchEnvelope(documentEnvelope({ status: "finished" })),
    /unknown document status “finished”/,
  );

  assert.throws(
    () => cv.normalizeBatchEnvelope(documentEnvelope({ format: "rtf" })),
    /unknown document format “rtf”/,
  );

  assert.throws(
    () => cv.normalizeBatchEnvelope(documentEnvelope({ index: -1 })),
    /index: expected a non-negative integer/,
  );

  assert.throws(
    () => cv.normalizeBatchEnvelope(documentEnvelope({ metadata: undefined })),
    /metadata: expected an object/,
  );

  assert.throws(
    () =>
      cv.normalizeBatchEnvelope(
        documentEnvelope({ metadata: { page_count: 1, paragraph_count: null } }),
      ),
    /size_bytes: expected a non-negative integer/,
  );

  assert.throws(
    () => cv.normalizeBatchEnvelope(documentEnvelope({ warnings: undefined })),
    /warnings: expected an array/,
  );

  assert.throws(
    () => cv.normalizeBatchEnvelope(documentEnvelope({ segments: undefined })),
    /segments: expected an array/,
  );
});

test("the text of a document must match its segments", () => {
  assert.throws(
    () =>
      cv.normalizeBatchEnvelope(
        documentEnvelope({
          text: "Something the segments do not say.",
          segments: [{ locator: { kind: "page", page: 1 }, text: "Extracted text." }],
        }),
      ),
    (error) => {
      assert.equal(error.name, "CvContractError");
      assert.match(error.message, /does not match the concatenated segment text/);
      return true;
    },
  );
});

test("locators must be 1-based pages or paragraphs", () => {
  assert.throws(
    () =>
      cv.normalizeBatchEnvelope(
        documentEnvelope({
          text: "",
          segments: [{ text: "" }],
        }),
      ),
    /page or paragraph reference is required/,
  );

  assert.throws(
    () =>
      cv.normalizeBatchEnvelope(
        documentEnvelope({
          text: "x",
          segments: [{ locator: { kind: "page", page: 0 }, text: "x" }],
        }),
      ),
    /1-based page number/,
  );

  assert.throws(
    () =>
      cv.normalizeBatchEnvelope(
        documentEnvelope({
          text: "x",
          segments: [{ locator: { kind: "line", page: 1 }, text: "x" }],
        }),
      ),
    /expected “page” or “paragraph”/,
  );
});

test("a malformed payload is rejected instead of being repaired", () => {
  assert.throws(() => cv.normalizeBatchEnvelope(null), /response: expected an object/);
  assert.throws(
    () => cv.normalizeBatchEnvelope({ schema_version: "1.1" }),
    /transport_version: expected a string/,
  );
  assert.throws(
    () => cv.normalizeBatchEnvelope(envelope({ documents: undefined })),
    /documents: expected an array/,
  );
});

test("summarizeExtraction tolerates empty and unknown input", () => {
  assert.deepEqual(cv.summarizeExtraction(null), {
    total: 0,
    extracted: 0,
    needsReview: 0,
    failed: 0,
    pending: 0,
    finished: 0,
    warnings: 0,
    segments: 0,
  });
});

test("createExtraction posts multipart files and normalizes the response", async () => {
  const calls = [];
  const adapter = new cv.CvApiAdapter({
    baseUrl: "/api/cv/",
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      return jsonResponse(fixture("batch-completed"));
    },
  });

  const job = await adapter.createExtraction([
    blobFile("sample-cv.pdf", 1024, cv.PDF_MIME),
    blobFile("sample-cover-letter.docx", 2048, cv.DOCX_MIME),
  ]);

  // One POST, no polling: the response is already terminal.
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/cv/extractions");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.headers.Accept, "application/json");
  assert.equal(calls[0].options.credentials, "same-origin");
  assert.ok(calls[0].options.body instanceof FormData);
  const uploaded = calls[0].options.body.getAll("files");
  assert.deepEqual(
    uploaded.map((entry) => entry.name),
    ["sample-cv.pdf", "sample-cover-letter.docx"],
  );

  assert.equal(job.status, "complete");
  assert.equal(job.parserStatus, "completed");
  assert.equal(cv.isTerminalJobStatus(job.status), true);
});

test("the API base stays configurable for a same-origin deployment", async () => {
  const urls = [];
  const adapter = new cv.CvApiAdapter({
    baseUrl: "http://127.0.0.1:9000/api/cv/",
    fetchImpl: async (url) => {
      urls.push(url);
      return jsonResponse(fixture("batch-completed"));
    },
  });

  await adapter.createExtraction([blobFile("sample-cv.pdf", 10)]);
  assert.deepEqual(urls, ["http://127.0.0.1:9000/api/cv/extractions"]);
});

test("createExtraction refuses empty and oversized selections before fetching", async () => {
  let fetchCalls = 0;
  const adapter = new cv.CvApiAdapter({
    fetchImpl: async () => {
      fetchCalls += 1;
      return jsonResponse(fixture("batch-completed"));
    },
  });

  await assert.rejects(adapter.createExtraction([]), (error) => {
    assert.equal(error.code, "no_documents");
    return true;
  });

  const tooMany = Array.from({ length: 6 }, (_, index) => file(`f${index}.pdf`, 10));
  await assert.rejects(adapter.createExtraction(tooMany), (error) => {
    assert.equal(error.code, "too_many_documents");
    return true;
  });

  assert.equal(fetchCalls, 0);
});

test("the aggregate batch size is checked before a request is built", async () => {
  let fetchCalls = 0;
  const adapter = new cv.CvApiAdapter({
    fetchImpl: async () => {
      fetchCalls += 1;
      return jsonResponse(fixture("batch-completed"));
    },
  });

  const limit = cv.MAX_BATCH_BYTES;
  const half = limit / 2;

  // Exactly the limit is allowed and does reach the server.
  await adapter.createExtraction([
    blobFile("a.pdf", half),
    blobFile("b.pdf", half),
  ]);
  assert.equal(fetchCalls, 1);

  // One byte over the limit is refused without a request.
  await assert.rejects(
    adapter.createExtraction([blobFile("a.pdf", limit), blobFile("b.pdf", 1)]),
    (error) => {
      assert.equal(error.code, "batch_too_large");
      assert.equal(error.details.totalBytes, limit + 1);
      assert.equal(error.details.maxBatchBytes, limit);
      assert.match(error.message, /25 MiB batch limit/);
      assert.match(error.message, /Remove a document or use smaller files/);
      return true;
    },
  );
  assert.equal(fetchCalls, 1);
});

test("the aggregate size is measured over the selected documents", () => {
  assert.equal(
    cv.totalBytesOf([file("a.pdf", 1024), file("b.pdf", 2048)]),
    3072,
  );
  assert.equal(cv.totalBytesOf([]), 0);
  assert.equal(cv.totalBytesOf(null), 0);
});

test("waitForExtraction reads the terminal batch once instead of polling", async () => {
  const urls = [];
  const updates = [];
  const adapter = new cv.CvApiAdapter({
    baseUrl: "/api/cv",
    pollIntervalMs: 0,
    fetchImpl: async (url) => {
      urls.push(url);
      return jsonResponse(fixture("batch-completed"));
    },
  });

  const job = await adapter.waitForExtraction("job id/with space", {
    onUpdate: (update) => updates.push(update.status),
  });

  assert.equal(job.status, "complete");
  assert.equal(urls.length, 1);
  assert.equal(urls[0], "/api/cv/extractions/job%20id%2Fwith%20space");
  assert.deepEqual(updates, ["complete"]);
});

test("getExtraction requires a job id and never fetches without one", async () => {
  let fetchCalls = 0;
  const adapter = new cv.CvApiAdapter({
    fetchImpl: async () => {
      fetchCalls += 1;
      return jsonResponse(fixture("batch-completed"));
    },
  });

  await assert.rejects(adapter.getExtraction("  "), (error) => {
    assert.equal(error.name, "CvContractError");
    return true;
  });
  assert.equal(fetchCalls, 0);
});

test("non-2xx responses become CvHttpError with the parser error code", async () => {
  const adapter = new cv.CvApiAdapter({
    fetchImpl: async () =>
      jsonResponse(
        { error: { code: "parser_unavailable", message: "The parser is not wired up." } },
        503,
      ),
  });

  await assert.rejects(adapter.getExtraction("job-1"), (error) => {
    assert.equal(error.name, "CvHttpError");
    assert.equal(error.status, 503);
    assert.equal(error.details.code, "parser_unavailable");
    assert.match(error.message, /not wired up/);
    return true;
  });
});

test("non-JSON, empty and network failures map to contract and network errors", async () => {
  const htmlAdapter = new cv.CvApiAdapter({
    fetchImpl: async () => textResponse("<html>not json</html>", 200),
  });
  await assert.rejects(htmlAdapter.getExtraction("job-1"), (error) => {
    assert.equal(error.name, "CvContractError");
    assert.match(error.message, /non-JSON body/);
    return true;
  });

  const emptyAdapter = new cv.CvApiAdapter({
    fetchImpl: async () => textResponse("", 200),
  });
  await assert.rejects(emptyAdapter.getExtraction("job-1"), (error) => {
    assert.equal(error.name, "CvContractError");
    assert.match(error.message, /empty or non-object JSON body/);
    return true;
  });

  const offlineAdapter = new cv.CvApiAdapter({
    fetchImpl: async () => {
      throw new TypeError("Failed to fetch");
    },
  });
  await assert.rejects(offlineAdapter.getExtraction("job-1"), (error) => {
    assert.equal(error.name, "CvError");
    assert.equal(error.code, "network_error");
    return true;
  });
});

test("the adapter rejects construction when fetch is unavailable", () => {
  const originalFetch = Object.getOwnPropertyDescriptor(globalThis, "fetch");
  delete globalThis.fetch;
  try {
    assert.throws(
      () => new cv.CvApiAdapter({ fetchImpl: null }),
      (error) => {
        assert.equal(error.code, "fetch_unavailable");
        return true;
      },
    );
  } finally {
    if (originalFetch) Object.defineProperty(globalThis, "fetch", originalFetch);
  }
});
