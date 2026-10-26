"use strict";

(() => {
  const cv = window.JobLensCV;
  const cvp = window.JobLensProfileAdapter;
  const cvr = window.JobLensProfileReview;
  const cvz = window.JobLensReconciliation;
  const cvt = window.JobLensTailor;
  const $ = (id) => document.getElementById(id);

  const PHASE = Object.freeze({
    IDLE: "idle",
    READY: "ready",
    UPLOADING: "uploading",
    REPORT: "report",
    ERROR: "error",
  });

  const VIEW = Object.freeze({
    EXTRACTION: "extraction",
    PROFILE: "profile",
    RECONCILIATION: "reconciliation",
    TAILOR: "tailor",
  });

  const PREVIEW_SOURCE_FIXTURE = "./fixtures/profile-preview-source.json";
  const PREVIEW_ENVELOPE_FIXTURE = "./fixtures/profile-synthetic.json";
  const PREVIEW_SUGGESTION_FIXTURE = "./fixtures/profile-synthetic-recommendation.json";
  const PREVIEW_MULTI_SOURCE = "./fixtures/profile-reconciliation-source.json";
  const PREVIEW_MULTI_ENVELOPE = "./fixtures/profile-reconciliation-synthetic.json";

  /*
   * The user-facing language is English. The adapters keep the wire format and
   * its identifiers untouched; only labels, helpers and explanations are
   * translated here. Nothing in this map invents a fact or a relationship.
   */
  const CATEGORY_ES = Object.freeze({
    skill: { label: "Skills", singular: "Skill" },
    experience: { label: "Experience", singular: "Experience" },
    education: { label: "Education", singular: "Education" },
    project: { label: "Projects", singular: "Project" },
    language: { label: "Languages", singular: "Language" },
    certification: { label: "Certifications", singular: "Certification" },
    achievement: { label: "Achievements", singular: "Achievement" },
    contribution: { label: "Contributions", singular: "Contribution" },
    employment: { label: "Employment", singular: "Employment" },
    organization: { label: "Organizations", singular: "Organization" },
    degree: { label: "Degrees", singular: "Degree" },
    technology: { label: "Technologies", singular: "Technology" },
  });

  const DOC_STATUS_ES = Object.freeze({
    queued: { label: "Queued", description: "Waiting for the document reader." },
    processing: { label: "Reading", description: "The reader is working on this document." },
    extracted: { label: "Has text", description: "The reader returned text for this document." },
    needs_review: {
      label: "To review",
      description: "The reader returned incomplete text or warnings. Check it before trusting it.",
    },
    failed: { label: "No text", description: "The reader returned no usable text." },
  });

  const JOB_STATUS_ES = Object.freeze({
    queued: { label: "Queued", description: "The reader accepted the job and has not started yet." },
    processing: { label: "Reading", description: "The reader is still working." },
    complete: { label: "Completed", description: "Every document was read in full." },
    partial: {
      label: "Partial",
      description: "The job finished, but at least one document is incomplete.",
    },
    failed: { label: "Failed", description: "The reading job failed." },
  });

  const FIELD_ES = Object.freeze({
    name: "Name",
    role: "Role",
    level: "Level",
    field: "Field of study",
    language: "Language",
    stated_level: "Stated level",
  });

  const WARNING_ES = Object.freeze({
    pages_without_text: "Some pages have no extractable text.",
    internal_error: "The reader could not process the document.",
  });

  const ATTRIBUTE_ES = Object.freeze({
    name: "Name",
    proficiency: "Level",
    stated_level: "Stated level",
    role: "Role",
    organization: "Organization",
    start: "Start",
    end: "End",
    duration_months: "Duration (months)",
    duration_exact: "Duration precision",
    technologies: "Technologies",
    project: "Project",
    quantities: "Figures",
    template: "Template",
    text: "Text",
    level: "Level",
    field: "Field",
    language: "Language",
    date: "Date",
  });

  const CONFLICT_RELATIONS = Object.freeze([
    "contradictory",
    "potentially_conflicting",
    "uncertain",
  ]);

  let adapter = null;
  let profileAdapter = null;
  let profileAdapterError = null;

  const state = {
    files: [],
    fileSequence: 0,
    phase: PHASE.IDLE,
    job: null,
    selectedDocumentId: null,
    selectedSegmentId: null,
    error: null,
    notice: "",
    alertMessages: [],
    revision: 0,
    abortController: null,
    lastAnnouncedJobId: null,
    view: VIEW.EXTRACTION,
    profile: null,
    profileState: "idle",
    profileError: null,
    profileView: null,
    profileEditing: null,
    conflictForm: null,
    review: null,
    reconciliation: null,
    profileFilter: "all",
    tailor: {
      jobPosting: { title: "", company: "", location: "", text: "" },
      draft: null,
      generating: false,
      error: null,
      jobStatus: "",
    },
    reconciliationAttention: 0,
    nextAction: "choose",
  };

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    if (!cv) {
      renderAdapterFailure();
      return;
    }

    bindEvents();

    try {
      adapter = new cv.CvApiAdapter({ baseUrl: apiBase() });
    } catch (error) {
      state.error = error;
      state.phase = PHASE.ERROR;
      renderAll();
      focusElement("error-heading");
      return;
    }

    // The profile engine is optional and separate: a missing profile adapter
    // must not stop the extraction workspace from working.
    state.review = null;
    if (cvp) {
      try {
        profileAdapter = new cvp.CvProfileAdapter({ baseUrl: apiBase() });
      } catch (error) {
        profileAdapterError = error;
      }
    } else {
      profileAdapterError = new Error(
        "The profile adapter did not load. Check that profile-adapter.js is served next to this page.",
      );
    }

    renderAll();

    window.addEventListener("pagehide", () => {
      state.abortController?.abort();
    });
  }

  function apiBase() {
    const meta = document.querySelector('meta[name="joblens-cv-api-base"]');
    const configured = meta?.getAttribute("content")?.trim();
    return configured || cv.DEFAULT_API_BASE;
  }

  function renderAdapterFailure() {
    const message =
      "The CV API adapter did not load. Check that api-adapter.js is served next to this page.";
    for (const id of ["empty-state", "ready-state", "loading-state", "report"]) {
      $(id).hidden = true;
    }
    $("error-state").hidden = false;
    setText("error-heading", "Could not show the extraction.");
    setText("error-message", message);
    setText(
      "error-hint",
      "Interface files are missing. Start the preview server or mount every file in web/workspace/.",
    );
    $("retry").disabled = true;
    focusElement("error-heading");
  }

  function bindEvents() {
    $("file-input").addEventListener("change", (event) => {
      addFiles(event.target.files);
      event.target.value = "";
    });

    const dropzone = $("dropzone");
    ["dragenter", "dragover"].forEach((type) => {
      dropzone.addEventListener(type, (event) => {
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
        if (!isBusy()) dropzone.classList.add("is-dragging");
      });
    });
    ["dragleave", "dragend"].forEach((type) => {
      dropzone.addEventListener(type, () => dropzone.classList.remove("is-dragging"));
    });
    dropzone.addEventListener("drop", (event) => {
      event.preventDefault();
      dropzone.classList.remove("is-dragging");
      if (!isBusy()) addFiles(event.dataTransfer.files);
    });

    $("extract").addEventListener("click", startExtraction);
    $("extract-ready").addEventListener("click", startExtraction);
    $("clear").addEventListener("click", clearAll);
    $("cancel").addEventListener("click", cancelExtraction);
    $("retry").addEventListener("click", startExtraction);
    $("dismiss-error").addEventListener("click", dismissError);
    $("previous-segment").addEventListener("click", () => moveSegment(-1));
    $("next-segment").addEventListener("click", () => moveSegment(1));

    $("view-extraction").addEventListener("click", () => switchView(VIEW.EXTRACTION));
    $("view-profile").addEventListener("click", () => switchView(VIEW.PROFILE));
    $("view-reconciliation").addEventListener("click", () =>
      switchView(VIEW.RECONCILIATION),
    );
    $("view-tailor").addEventListener("click", () => switchView(VIEW.TAILOR));
    for (const id of ["view-extraction", "view-profile", "view-reconciliation", "view-tailor"]) {
      $(id).addEventListener("keydown", (event) => {
        const order = [VIEW.EXTRACTION, VIEW.PROFILE, VIEW.RECONCILIATION, VIEW.TAILOR];
        if (event.key === "Home" || event.key === "End") {
          event.preventDefault();
          const next = event.key === "Home" ? order[0] : order[order.length - 1];
          switchView(next);
          focusElement(`view-${next}`);
          return;
        }
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        const index = order.indexOf(state.view);
        const next = order[(index + (event.key === "ArrowLeft" ? -1 : 1) + order.length) % order.length];
        switchView(next);
        focusElement(`view-${next}`);
      });
    }

    $("profile-build").addEventListener("click", buildProfile);
    $("profile-preview").addEventListener("click", () =>
      loadSyntheticProfile(PREVIEW_ENVELOPE_FIXTURE),
    );
    $("profile-preview-suggestion").addEventListener("click", () =>
      loadSyntheticProfile(PREVIEW_SUGGESTION_FIXTURE),
    );
    $("profile-clear").addEventListener("click", clearProfile);
    $("profile-export-approved").addEventListener("click", exportApprovedProfile);
    $("profile-import-approved").addEventListener("change", importApprovedProfile);
    $("reconciliation-build").addEventListener("click", buildReconciliation);
    $("reconciliation-preview").addEventListener("click", () =>
      loadSyntheticProfile(PREVIEW_ENVELOPE_FIXTURE),
    );
    $("reconciliation-preview-multi").addEventListener("click", () =>
      loadSyntheticProfile(PREVIEW_MULTI_ENVELOPE, PREVIEW_MULTI_SOURCE),
    );
    $("reconciliation-clear").addEventListener("click", clearReconciliation);
    $("tailor-job-form").addEventListener("submit", (event) => {
      event.preventDefault();
      submitTailorJob();
    });
    $("tailor-import-approved").addEventListener("change", importTailorApprovedProfile);
    $("tailor-generate").addEventListener("click", () => generateTailorDraft());
    $("tailor-export-pdf").addEventListener("click", () => exportTailor("pdf"));
    $("tailor-export-docx").addEventListener("click", () => exportTailor("docx"));
    $("next-step-action").addEventListener("click", runNextAction);
    $("reconciliation-open-profile").addEventListener("click", () =>
      switchView(VIEW.PROFILE),
    );
  }

  function el(tag, options = {}) {
    const node = document.createElement(tag);
    if (options.className) node.className = options.className;
    if (options.text !== undefined) node.textContent = options.text;

    if (options.attrs) {
      for (const [name, value] of Object.entries(options.attrs)) {
        if (value === undefined || value === null || value === false) continue;
        node.setAttribute(name, value === true ? "" : String(value));
      }
    }

    if (options.children) {
      for (const child of options.children) {
        if (child) node.append(child);
      }
    }
    return node;
  }

  function setText(id, value) {
    const node = $(id);
    if (node) node.textContent = value ?? "";
  }

  function clearNode(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function plural(count, singular, pluralForm) {
    const word = count === 1 ? singular : pluralForm || `${singular}s`;
    return `${count} ${word}`;
  }

  /* Presentation only: the engine keeps its lowercase subject labels. */
  function displaySubject(label) {
    const text = String(label ?? "");
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
  }

  function documentMeta(status) {
    const base =
      cv?.DOCUMENT_STATUS_META?.[status] || {
        label: status || "Desconocido",
        tone: "neutral",
        description: "The reader did not describe this status.",
      };
    const spanish = DOC_STATUS_ES[status];
    return {
      ...base,
      label: spanish?.label || base.label,
      description: spanish?.description || base.description,
    };
  }

  function jobMeta(status) {
    const base =
      cv?.JOB_STATUS_META?.[status] || {
        label: status || "Desconocido",
        tone: "neutral",
        description: "The reader did not describe the analysis status.",
      };
    const spanish = JOB_STATUS_ES[status];
    return {
      ...base,
      label: spanish?.label || base.label,
      description: spanish?.description || base.description,
    };
  }

  function categoryLabel(category, singular = false) {
    const meta = CATEGORY_ES[category];
    if (meta) return singular ? meta.singular : meta.label;
    return category || "Data";
  }

  function locatorLabel(locator) {
    if (!locator) return "No reference";
    if (locator.kind === "page") return `Page ${locator.page}`;
    if (locator.kind === "paragraph") {
      return `Paragraph ${locator.paragraph}${locator.section ? ` · ${locator.section}` : ""}`;
    }
    return "No reference";
  }

  function attributeLabel(name) {
    return ATTRIBUTE_ES[name] || name;
  }

  function statusPill(meta) {
    return el("span", {
      className: `status-pill status-${meta.tone}`,
      children: [
        el("span", { className: "status-dot", attrs: { "aria-hidden": "true" } }),
        document.createTextNode(meta.label),
      ],
    });
  }

  function applyStatusPill(node, meta) {
    node.className = `status-pill status-${meta.tone}`;
    node.replaceChildren(
      el("span", { className: "status-dot", attrs: { "aria-hidden": "true" } }),
      document.createTextNode(meta.label),
    );
  }

  function fileKindLabel(kind) {
    if (kind === "pdf") return "PDF";
    if (kind === "docx") return "DOCX";
    return "FILE";
  }

  function isBusy() {
    if (state.phase === PHASE.UPLOADING) return true;
    return Boolean(
      state.phase === PHASE.REPORT &&
        state.job &&
        !cv.isTerminalJobStatus(state.job.status),
    );
  }

  function selectedDocument() {
    if (!state.job || !Array.isArray(state.job.documents)) return null;
    return (
      state.job.documents.find((doc) => doc.id === state.selectedDocumentId) || null
    );
  }

  function firstSegmentId(doc) {
    return Array.isArray(doc?.segments) && doc.segments.length
      ? doc.segments[0].id
      : null;
  }

  function focusElement(id) {
    const node = $(id);
    if (node && typeof node.focus === "function") node.focus();
  }

  function formatDocumentMeta(doc) {
    const parts = [fileKindLabel(doc.kind)];
    if (doc.sizeBytes !== null && doc.sizeBytes !== undefined) {
      parts.push(cv.formatBytes(doc.sizeBytes));
    }
    if (doc.pageCount !== null && doc.pageCount !== undefined) {
      parts.push(plural(doc.pageCount, "page"));
    }
    if (doc.paragraphCount !== null && doc.paragraphCount !== undefined) {
      parts.push(plural(doc.paragraphCount, "paragraph"));
    }
    if (doc.segments.length) {
      parts.push(plural(doc.segments.length, "text block"));
    }
    return parts.join(" · ");
  }

  function wordCountFor(doc) {
    return doc.segments.reduce(
      (total, segment) => total + (segment.wordCount || cv.countWords(segment.text)),
      0,
    );
  }

  function isSyntheticSession() {
    return Boolean(state.profile && state.profile.synthetic === true);
  }

  function renderDataMode() {
    const synthetic = isSyntheticSession();
    const hasDocuments = Boolean(
      (state.job && state.job.documents && state.job.documents.length) ||
        state.files.length,
    );
    const masthead = synthetic
      ? "Synthetic sample"
      : hasDocuments
        ? "Your local documents"
        : "No data loaded";
    setText("data-mode-label", masthead);
    setText(
      "footer-data-mode",
      synthetic ? "synthetic sample" : "local, in-memory session",
    );
  }

  function renderAll() {
    const active = document.activeElement;
    const activeId =
      active && $("report")?.contains(active) && active.id ? active.id : "";
    document.body.classList.toggle("has-job", Boolean(state.job));
    renderDataMode();
    renderSelection();
    renderMainState(activeId);
    renderControls();
    renderViewSwitch();
    renderProfile();
    renderReconciliation();
    renderTailor();
    renderNextStep();
  }

  /*
   * One guided suggestion, always derived from the state the user can see.
   * It never triggers an approval or a conflict resolution.
   */
  function nextStepFor() {
    if (
      state.view === VIEW.RECONCILIATION &&
      state.reconciliation &&
      state.reconciliationAttention
    ) {
      const count = state.reconciliationAttention;
      return {
        action: "review-reconciliation",
        label:
          count === 1
            ? "1 fact needs your judgement."
            : `${count} facts need your judgement.`,
        cta: "See what needs attention",
      };
    }
    if (!state.files.length && !state.job) {
      return {
        action: "choose",
        label: "Choose one or two documents to begin.",
        cta: "Choose files",
      };
    }
    if (state.files.length && !state.job) {
      return {
        action: "extract",
        label: "Analyse the text in your documents.",
        cta: "Analyse documents",
      };
    }
    if (state.job && state.profileState !== "ready") {
      return {
        action: "build-profile",
        label: "Create the profile and review the proposed facts.",
        cta: "Create profile",
      };
    }
    if (state.profileState === "ready") {
      const counts = state.profileView?.counts;
      if (counts?.proposed) {
        return {
          action: "review-profile",
          label: `${plural(counts.proposed, "proposal")} left to review in the profile.`,
          cta: "Review proposals",
        };
      }
      if (!state.reconciliation) {
        return {
          action: "reconcile",
          label: "Check whether your documents contradict each other.",
          cta: "Compare documents",
        };
      }
      if (state.reconciliationAttention) {
        const count = state.reconciliationAttention;
        return {
          action: "review-reconciliation",
          label:
            count === 1
              ? "1 decision needs your confirmation."
              : `${count} decisions need your confirmation.`,
          cta: "See what needs attention",
        };
      }
      return {
        action: "done",
        label: "All reviewed: no pending conflicts.",
        cta: "View profile",
      };
    }
    return {
      action: "choose",
      label: "Add your documents to begin.",
      cta: "Choose files",
    };
  }

  function renderNextStep() {
    const next = nextStepFor();
    state.nextAction = next.action;
    setText("next-step-label", next.label);
    setText("next-step-action", next.cta);
    $("next-step").hidden = false;
  }

  function runNextAction() {
    switch (state.nextAction) {
      case "choose":
        $("file-input").click();
        break;
      case "extract":
        startExtraction();
        break;
      case "build-profile":
        switchView(VIEW.PROFILE);
        buildProfile();
        break;
      case "review-profile": {
        switchView(VIEW.PROFILE);
        const first = $("profile-groups").querySelector(".proposal-proposed .proposal-label");
        if (first && typeof first.focus === "function") {
          first.focus({ preventScroll: false });
        }
        break;
      }
      case "reconcile":
        switchView(VIEW.RECONCILIATION);
        buildReconciliation();
        break;
      case "review-reconciliation":
        switchView(VIEW.RECONCILIATION);
        focusElement("attention-heading");
        break;
      default:
        switchView(VIEW.PROFILE);
        break;
    }
  }

  function renderControls() {
    const busy = isBusy();
    const hasFiles = state.files.length > 0;
    const label =
      state.phase === PHASE.UPLOADING
        ? "Starting…"
        : busy
          ? "Analysing…"
          : "Analyse documents";

    for (const id of ["extract", "extract-ready"]) {
      const button = $(id);
      if (!button) continue;
      button.disabled = !hasFiles || busy;
      button.textContent = label;
    }

    $("clear").disabled = !hasFiles || busy;
    $("cancel").hidden = !busy;
    $("file-input").disabled = busy;
    $("dropzone").classList.toggle("is-disabled", busy);
    $("retry").disabled = !hasFiles;
  }

  function renderSelection() {
    setText("selection-count", `${state.files.length} / ${cv.MAX_DOCUMENTS}`);

    const list = $("selection-list");
    clearNode(list);
    const busy = isBusy();
    const matches = matchDocumentsToFiles();

    state.files.forEach((entry, index) => {
      const local = localFileStatus(matches[index]);
      const remove = el("button", {
        className: "queue-remove",
        attrs: {
          type: "button",
          "aria-label": `Remove ${entry.name}`,
          disabled: busy ? true : undefined,
        },
        text: "Remove",
      });
      remove.addEventListener("click", () => removeFile(entry.uid));

      const card = el("li", {
        className: `queue-card ${local.modifier}`,
        children: [
          el("div", {
            className: "queue-main",
            children: [
              el("strong", {
                className: "queue-name",
                text: entry.name,
                attrs: { title: entry.name },
              }),
              el("span", {
                className: "queue-meta",
                children: [
                  el("span", {
                    className: "queue-file-kind",
                    text: fileKindLabel(entry.kind),
                  }),
                  document.createTextNode(
                    `· ${cv.formatBytes(entry.size)} · ${local.label}`,
                  ),
                ],
              }),
            ],
          }),
          remove,
        ],
      });
      list.append(card);
    });

    $("selection-empty").hidden = state.files.length > 0;
    renderAlert();
  }

  function matchDocumentsToFiles() {
    if (state.phase !== PHASE.REPORT || !state.job) return [];
    const remaining = state.job.documents.slice();
    return state.files.map((entry) => {
      const index = remaining.findIndex((doc) => doc.filename === entry.name);
      if (index < 0) return null;
      return remaining.splice(index, 1)[0];
    });
  }

  function localFileStatus(doc) {
    if (state.phase === PHASE.UPLOADING) {
      return { label: "Enviando", modifier: "queue-sending" };
    }

    if (state.phase === PHASE.REPORT && state.job) {
      if (!doc) {
        return { label: "No devuelto", modifier: "queue-failed" };
      }
      const meta = documentMeta(doc.status);
      const modifier = {
        queued: "queue-queued",
        processing: "queue-processing",
        extracted: "queue-done",
        needs_review: "queue-queued",
        failed: "queue-failed",
      }[doc.status] || "queue-ready";
      return { label: meta.label, modifier };
    }

    if (state.phase === PHASE.ERROR) {
      return { label: "Not sent", modifier: "queue-failed" };
    }

    return { label: "Ready", modifier: "queue-ready" };
  }

  function renderAlert() {
    const alert = $("selection-alert");
    clearNode(alert);
    alert.hidden = state.alertMessages.length === 0;
    for (const message of state.alertMessages) {
      alert.append(el("p", { text: message }));
    }
  }

  function renderMainState(activeId = "") {
    const sections = [
      "empty-state",
      "ready-state",
      "loading-state",
      "error-state",
      "report",
    ];
    for (const id of sections) $(id).hidden = true;

    $("results").setAttribute("aria-busy", isBusy() ? "true" : "false");

    if (state.phase === PHASE.IDLE) {
      $("empty-state").hidden = false;
      return;
    }

    if (state.phase === PHASE.READY) {
      renderReady();
      $("ready-state").hidden = false;
      return;
    }

    if (state.phase === PHASE.UPLOADING) {
      $("loading-state").hidden = false;
      return;
    }

    if (state.phase === PHASE.ERROR) {
      renderError();
      $("error-state").hidden = false;
      return;
    }

    if (state.phase === PHASE.REPORT && state.job) {
      renderReport(activeId);
      $("report").hidden = false;
    }
  }

  function renderReady() {
    const count = state.files.length;
    setText(
      "ready-heading",
      count === 1 ? "One document is ready." : `${count} documents are ready.`,
    );

    const base =
      "Nothing has been read yet. Analyse the documents to see the text, references, and warnings.";
    setText("ready-copy", state.notice ? `${state.notice} ${base}` : base);

    const list = $("ready-list");
    clearNode(list);
    for (const entry of state.files) {
      list.append(
        el("li", {
          children: [
            el("span", {
              className: "queue-file-kind",
              text: fileKindLabel(entry.kind),
            }),
            el("span", { text: entry.name }),
          ],
        }),
      );
    }
  }

  function renderError() {
    const error = state.error || new Error("Unexpected error.");
    setText("error-message", error.message || "Unexpected error.");

    const hint = errorHint(error);
    const code = error.code ? `Code: ${error.code}. ` : "";
    setText("error-hint", `${code}${hint}`);
  }

  function errorHint(error) {
    if (error?.name === "CvContractError" || error?.code === "contract_error") {
      return "The response does not match reader schema 1.1. Compare it with docs/cv-workspace-contract.md and update web/workspace/api-adapter.js.";
    }
    if (error?.code === "empty_batch") {
      return "The reader rejected the request because it contained no documents. Choose at least one PDF or DOCX and try again.";
    }
    if (error?.code === "too_many_documents") {
      return "The reader rejected the batch because it contained more documents than allowed. Remove one and try again.";
    }
    if (error?.code === "batch_too_large") {
      return "The documents exceed the 25 MiB limit, so the request was not sent. Remove a document or use smaller files.";
    }
    if (error?.code === "request_too_large" || error?.details?.code === "request_too_large") {
      return "The server rejected the request because the body was too large (HTTP 413). The limit is 25 MiB; remove a document or use smaller files.";
    }
    if (error?.status === 413) {
      return "The reader returned HTTP 413 because the request was too large. The limit is 25 MiB; remove a document or use smaller files.";
    }
    if (error?.code === "timeout") {
      return "The screen stopped waiting after the timeout. The reader may still be working; trying again starts a new job.";
    }
    if (error?.code === "network_error") {
      return "Check that the reading service is running and that the joblens-cv-api-base tag points to its /api/cv base.";
    }
    if (error?.code === "adapter_unavailable" || error?.code === "fetch_unavailable") {
      return "This browser could not create the API adapter. Use a current browser with fetch support and reload the page.";
    }
    if (error?.status) {
      return `The reader returned HTTP ${error.status}. Check that the route is mounted at the configured API base.`;
    }
    if (error?.code === "no_documents") {
      return "Choose at least one PDF or DOCX file.";
    }
    return "Check the reading service and the documented contract, then try again.";
  }

  function renderReport(activeId = "") {
    const job = state.job;
    if (!job) return;

    const summary = cv.summarizeExtraction(job);
    const processing = job.status === "queued" || job.status === "processing";

    setText(
      "report-title",
      processing ? "Analysing documents" : "Analysis report",
    );
    const subtitle = $("report-subtitle");
    subtitle.textContent = processing
      ? `${plural(summary.total, "document")} · the reader is still working`
      : `${plural(summary.total, "document")} · ${plural(summary.extracted, "with text", "with text")}`;
    subtitle.title = `Job ${job.id}`;

    applyJobBadge(job);
    applyContractBadge(job);
    renderJobBanner(job, summary);
    renderWarnings($("job-warnings"), job.warnings);
    renderSummary(summary);
    renderDocumentTabs(job);
    renderReader(selectedDocument());

    if (activeId) {
      const restored = document.getElementById(activeId);
      if (restored && typeof restored.focus === "function" && !restored.disabled) {
        restored.focus({ preventScroll: true });
      }
    }
  }

  function applyJobBadge(job) {
    const meta = jobMeta(job.status);
    const badge = $("job-badge");
    badge.className = `badge badge-${meta.tone}`;
    badge.textContent = meta.label;
    badge.title = meta.description;
  }

  function applyContractBadge(job) {
    const badge = $("contract-badge");
    if (!job.contractVersion) {
      badge.className = "badge badge-warn";
      badge.textContent = "Contract version not stated";
      badge.title =
        "The response does not include schema_version. The adapter accepted the content but cannot confirm that the versions match.";
      return;
    }
    if (job.contractVersionMatches) {
      badge.className = "badge badge-ok";
      badge.textContent = `Contract v${job.contractVersion}`;
      badge.title = "The response declares the schema version this screen was built for.";
      return;
    }
    badge.className = "badge badge-warn";
    badge.textContent = `Contract v${job.contractVersion} · adapter v${cv.CONTRACT_VERSION}`;
    badge.title =
      "The reader declared a different contract version. Check docs/cv-workspace-contract.md before trusting the conversion.";
  }

  function renderJobBanner(job, summary) {
    const banner = $("job-banner");
    let tone = jobMeta(job.status).tone;
    let title = jobMeta(job.status).label;
    let copy = jobMeta(job.status).description;

    if (job.status === "queued") {
      tone = "info";
      title = "Analysis queued";
      copy = "The reader accepted the job but has not returned text yet. Nothing is marked as read early.";
    } else if (job.status === "processing") {
      tone = "info";
      title = "Analysing documents";
      copy =
        "The statuses below reflect the reader's latest response. You can leave this tab open: the screen will keep checking.";
    } else if (job.status === "complete") {
      if (summary.warnings > 0) {
        tone = "warn";
        title = "Completed with warnings";
        copy = `${plural(summary.warnings, "reader warning", "reader warnings")} to review. Check each document before using the text.`;
      } else {
        tone = "ok";
        title = "Every document finished";
        copy = "Review the text and the page or paragraph references below.";
      }
    } else if (job.status === "partial") {
      tone = "warn";
      title = "Completed with incomplete information";
      copy = `${plural(summary.needsReview, "document")} to review${summary.failed ? ` and ${plural(summary.failed, "document")} with no text` : ""}. Nothing was filled in.`;
    } else if (job.status === "failed") {
      tone = "error";
      title = "The analysis failed";
      copy = job.error?.message
        ? `The reader reported: ${job.error.message}`
        : "The reader reported a failure without an error message.";
    }

    banner.className = `banner banner-${tone}`;
    banner.hidden = false;
    setText("job-banner-title", title);
    setText("job-banner-copy", copy);

    const progressWrap = $("job-progress-wrap");
    const showProgress =
      (job.status === "queued" || job.status === "processing") && summary.total > 0;
    progressWrap.hidden = !showProgress;

    if (showProgress) {
      const progress = $("job-progress");
      progress.max = summary.total;
      progress.value = summary.finished;
      progress.setAttribute(
        "aria-valuetext",
        `${summary.finished} of ${summary.total} documents finished`,
      );
      setText("job-progress-label", "Documents finished");
      setText(
        "job-progress-count",
        `${summary.finished} / ${summary.total}`,
      );
    }
  }

  function renderSummary(summary) {
    setText("summary-total", String(summary.total));
    setText(
      "summary-total-note",
      summary.total
        ? `${plural(summary.segments, "text block")} returned`
        : "No documents returned",
    );

    setText("summary-extracted", String(summary.extracted));
    setText(
      "summary-extracted-note",
      summary.extracted ? "Text available" : "None yet",
    );

    setText("summary-review", String(summary.needsReview));
    setText(
      "summary-review-note",
      summary.warnings
        ? `${plural(summary.warnings, "reader warning", "reader warnings")} in total`
        : "No reader warnings",
    );

    setText("summary-failed", String(summary.failed));
    setText(
      "summary-failed-note",
      summary.failed ? "Could not read" : "None",
    );
  }

  function renderDocumentTabs(job) {
    const container = $("document-tabs");
    clearNode(container);
    const documents = job.documents;

    setText("documents-count", plural(documents.length, "document"));
    $("documents-empty").hidden = documents.length > 0;

    if (!documents.length) {
      state.selectedDocumentId = null;
      state.selectedSegmentId = null;
      return;
    }

    if (!documents.some((doc) => doc.id === state.selectedDocumentId)) {
      state.selectedDocumentId = documents[0].id;
      state.selectedSegmentId = firstSegmentId(documents[0]);
    }

    documents.forEach((doc, index) => {
      const meta = documentMeta(doc.status);
      const selected = doc.id === state.selectedDocumentId;

      const warnings = doc.warnings.slice(0, 2);
      const warningItems = warnings.map((warning) =>
        el("span", {
          className: "doc-warning",
          children: [
            el("span", {
              text: warning.severity === "info" ? "Info:" : "Warning:",
              attrs: { "aria-hidden": "true" },
            }),
            el("span", {
              text:
                WARNING_ES[warning.code] ||
                "The reader left a warning about this document.",
            }),
          ],
        }),
      );
      if (doc.error) {
        warningItems.push(
          el("span", {
            className: "doc-warning doc-warning-error",
            children: [
              el("span", {
                text: "Error:",
                attrs: { "aria-hidden": "true" },
              }),
              el("span", { text: doc.error.message }),
            ],
          }),
        );
      }
      const hiddenWarnings =
        doc.warnings.length + (doc.error ? 1 : 0) - warningItems.length;
      if (hiddenWarnings > 0) {
        warningItems.push(
          el("span", {
            className: "doc-warning-more",
            text: `+${hiddenWarnings} more`,
          }),
        );
      }

      const issueCount = doc.warnings.length + (doc.error ? 1 : 0);
      const action =
        doc.status === "failed"
          ? doc.error || !doc.warnings.length
            ? "See error"
            : "See warnings"
          : doc.status === "queued" || doc.status === "processing"
            ? "Waiting"
            : "See text";

      const button = el("button", {
        className: `doc-card doc-status-${doc.status}`,
        attrs: {
          type: "button",
          role: "tab",
          id: `doc-tab-${index}`,
          "aria-selected": selected ? "true" : "false",
          "aria-controls": "cv-reader",
          tabindex: selected ? "0" : "-1",
        },
        children: [
          el("span", {
            className: "doc-card-top",
            children: [
              el("span", {
                className: "file-kind",
                text: fileKindLabel(doc.kind),
              }),
              statusPill(meta),
            ],
          }),
          el("strong", {
            className: "doc-name",
            text: doc.filename,
            attrs: { title: doc.filename },
          }),
          el("span", {
            className: "doc-meta",
            text: formatDocumentMeta(doc),
          }),
          warningItems.length
            ? el("span", { className: "doc-warnings", children: warningItems })
            : null,
          el("span", {
            className: "doc-card-foot",
            children: [
              el("span", {
                text: issueCount
                  ? plural(issueCount, "warning", "warnings")
                  : "No warnings",
              }),
              el("span", { text: action }),
            ],
          }),
        ],
      });
      button.dataset.documentId = doc.id;
      button.addEventListener("click", () => selectDocument(doc.id));
      button.addEventListener("keydown", onTabKeydown);
      container.append(button);
    });

    const selectedTab = container.querySelector('[aria-selected="true"]');
    if (selectedTab) {
      $("cv-reader").setAttribute("aria-labelledby", selectedTab.id);
    }
  }

  function onTabKeydown(event) {
    const tabs = Array.from(
      $("document-tabs").querySelectorAll('[role="tab"]'),
    );
    const currentIndex = tabs.indexOf(event.currentTarget);
    let nextIndex = currentIndex;

    if (event.key === "ArrowRight") {
      nextIndex = (currentIndex + 1) % tabs.length;
    } else if (event.key === "ArrowLeft") {
      nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = tabs.length - 1;
    } else {
      return;
    }

    event.preventDefault();
    const target = state.job?.documents[nextIndex];
    if (!target) return;
    state.selectedDocumentId = target.id;
    state.selectedSegmentId = firstSegmentId(target);
    updateDocumentSelection();
    tabs[nextIndex]?.focus();
  }

  function updateDocumentSelection() {
    const tabs = Array.from(
      $("document-tabs").querySelectorAll('[role="tab"]'),
    );
    let selectedTab = null;
    for (const tab of tabs) {
      const selected = tab.dataset.documentId === state.selectedDocumentId;
      tab.setAttribute("aria-selected", selected ? "true" : "false");
      tab.setAttribute("tabindex", selected ? "0" : "-1");
      if (selected) selectedTab = tab;
    }
    if (selectedTab) {
      $("cv-reader").setAttribute("aria-labelledby", selectedTab.id);
    }
    renderReader(selectedDocument());
  }

  function selectDocument(documentId) {
    if (!state.job) return;
    const doc = state.job.documents.find((item) => item.id === documentId);
    if (!doc) return;
    state.selectedDocumentId = doc.id;
    state.selectedSegmentId = firstSegmentId(doc);
    updateDocumentSelection();
  }

  function renderReader(doc) {
    clearNode($("reader-warnings"));
    $("reader-warnings").hidden = true;

    if (!doc) {
      setText("reader-title", "No document selected");
      setText("reader-meta", "");
      applyStatusPill($("reader-status"), {
        label: "No document",
        tone: "neutral",
      });
      $("reader-grid").hidden = true;
      $("reader-state").hidden = false;
      setText(
        "reader-state",
        "Choose a document card to see the text the reader returned.",
      );
      return;
    }

    setText("reader-title", doc.filename);
    const words = wordCountFor(doc);
    setText(
      "reader-meta",
      `${formatDocumentMeta(doc)}${words ? ` · ${plural(words, "word")}` : ""}`,
    );
    applyStatusPill($("reader-status"), documentMeta(doc.status));
    renderWarnings($("reader-warnings"), doc.warnings);

    if (!doc.segments.length) {
      $("reader-grid").hidden = true;
      $("reader-state").hidden = false;

      if (doc.error) {
        setText(
          "reader-state",
          `The reader could not extract this document. ${doc.error.message}`,
        );
      } else if (doc.status === "queued") {
        setText(
          "reader-state",
          "There is no text yet. The document is queued and the reader has not started.",
        );
      } else if (doc.status === "processing") {
        setText(
          "reader-state",
          "There is no text yet. The reader is still working on this document.",
        );
      } else if (doc.status === "failed") {
        const reason = doc.warnings[0]?.message;
        setText(
          "reader-state",
          reason
            ? `The reader returned no usable text for this document. ${reason}`
            : "The reader marked this document as failed without an error message. Nothing was filled in.",
        );
      } else {
        setText(
          "reader-state",
          `The reader marked this document as “${documentMeta(doc.status).label.toLowerCase()}” but returned no text blocks. This can happen with scanned pages or a reader limitation.`,
        );
      }
      return;
    }

    if (
      !state.selectedSegmentId ||
      !doc.segments.some((segment) => segment.id === state.selectedSegmentId)
    ) {
      state.selectedSegmentId = doc.segments[0].id;
    }

    $("reader-state").hidden = true;
    $("reader-grid").hidden = false;
    renderOutline(doc);
    renderSource(doc);
  }

  function renderOutline(doc) {
    const list = $("outline-list");
    clearNode(list);
    setText("outline-count", String(doc.segments.length));

    doc.segments.forEach((segment, index) => {
      const selected = segment.id === state.selectedSegmentId;
      const collapsed = segment.text.trim().replace(/\s+/g, " ");
      const preview = collapsed
        ? collapsed.length > 70
          ? `${collapsed.slice(0, 70).trimEnd()}…`
          : collapsed
        : "No text in this block";

      const chip = el("span", {
        className: "ref-chip",
        children: [document.createTextNode(locatorLabel(segment.locator))],
      });
      const context = cv.formatLocatorContext(segment.locator);
      if (context) {
        chip.append(el("span", { className: "ref-context", text: context }));
      }

      const button = el("button", {
        className: "outline-item",
        attrs: {
          type: "button",
          id: `outline-item-${index}`,
          "aria-current": selected ? "true" : undefined,
        },
        children: [chip, el("span", { className: "outline-preview", text: preview })],
      });
      button.dataset.segmentId = segment.id;
      button.addEventListener("click", () => selectSegment(segment.id));
      list.append(button);
    });
  }

  function updateOutlineSelection() {
    const items = $("outline-list").querySelectorAll("[data-segment-id]");
    for (const item of items) {
      if (item.dataset.segmentId === state.selectedSegmentId) {
        item.setAttribute("aria-current", "true");
      } else {
        item.removeAttribute("aria-current");
      }
    }
  }

  function renderSource(doc) {
    const segments = doc.segments;
    const index = segments.findIndex(
      (segment) => segment.id === state.selectedSegmentId,
    );
    const segment = index >= 0 ? segments[index] : segments[0];
    if (!segment) return;

    const position = index >= 0 ? index : 0;
    const words = segment.wordCount || cv.countWords(segment.text);

    const reference = el("p", {
      className: "source-reference",
      children: [
        el("span", {
          className: "ref-chip",
          children: [document.createTextNode(locatorLabel(segment.locator))],
        }),
        el("span", {
          className: "source-reference-note",
          text: `Reference ${position + 1} of ${segments.length}`,
        }),
      ],
    });
    const context = cv.formatLocatorContext(segment.locator);
    if (context) {
      reference.append(el("span", { className: "source-reference-note", text: context }));
    }

    const textClass = segment.text.trim()
      ? "source-text"
      : "source-text source-text-empty";

    $("source-block").replaceChildren(
      reference,
      el("p", {
        className: textClass,
        text: segment.text.trim()
          ? segment.text
          : "This block has no extractable text.",
      }),
    );

    setText(
      "source-position",
      `Reference ${position + 1} of ${segments.length} · ${plural(words, "word")}`,
    );
    $("previous-segment").disabled = position <= 0;
    $("next-segment").disabled = position >= segments.length - 1;
  }

  function selectSegment(segmentId) {
    const document = selectedDocument();
    if (!document) return;
    if (!document.segments.some((segment) => segment.id === segmentId)) return;

    state.selectedSegmentId = segmentId;
    updateOutlineSelection();
    renderSource(document);

    if (window.matchMedia("(max-width: 720px)").matches) {
      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      $("source-block").scrollIntoView({
        behavior: reduced ? "auto" : "smooth",
        block: "nearest",
      });
    }
  }

  function moveSegment(direction) {
    const document = selectedDocument();
    if (!document || !document.segments.length) return;
    const index = document.segments.findIndex(
      (segment) => segment.id === state.selectedSegmentId,
    );
    const next = Math.min(
      document.segments.length - 1,
      Math.max(0, index + direction),
    );
    if (next === index) return;
    selectSegment(document.segments[next].id);
  }

  function renderWarnings(container, warnings) {
    clearNode(container);
    const items = Array.isArray(warnings) ? warnings : [];
    container.hidden = items.length === 0;

    for (const warning of items) {
      const summary = WARNING_ES[warning.code] || "Warning from the document reader.";

      container.append(
        el("div", {
          className: `warning-card${warning.severity === "info" ? " warning-card-info" : ""}`,
          children: [
            el("span", {
              className: "warning-severity",
              text: warning.severity === "info" ? "Info" : "Warning",
            }),
            el("div", {
              className: "warning-copy",
              children: [
                el("p", { className: "warning-summary-line", text: summary }),
                el("p", {
                  className: "warning-engine-text",
                  text: `Engine text: “${warning.message}”`,
                }),
                warning.locator
                  ? el("span", {
                      className: "warning-ref",
                      text: locatorLabel(warning.locator),
                    })
                  : null,
              ],
            }),
          ],
        }),
      );
    }
  }

  /* Candidate profile ---------------------------------------------------
   *
   * The profile engine shares the local application origin with the parser.
   * This view shows the proposals the engine returned, checks every quotation
   * against the extracted text of this session, and records human decisions in
   * memory.
   *
   * The transitions mirror the engine's review reducer: an edit creates a new
   * proposed revision and supersedes the edited fact, an approval is refused
   * without checked evidence, and a conflict is only cleared by a recorded
   * resolution that says which proposals stand behind it and why.
   */

  function switchView(view) {
    if (state.view === view) return;
    state.view = view;
    renderAll();
    if (view === VIEW.PROFILE) {
      focusElement("profile-title");
    } else if (view === VIEW.RECONCILIATION) {
      focusElement("reconciliation-title");
    } else if (view === VIEW.TAILOR) {
      focusElement("tailor-title");
    } else if (state.phase === PHASE.REPORT) {
      focusElement("report-title");
    }
  }

  function renderViewSwitch() {
    const order = [VIEW.EXTRACTION, VIEW.PROFILE, VIEW.RECONCILIATION, VIEW.TAILOR];
    for (const view of order) {
      const selected = state.view === view;
      const tab = $(`view-${view}`);
      tab.classList.toggle("is-active", selected);
      tab.setAttribute("aria-selected", String(selected));
      tab.setAttribute("tabindex", selected ? "0" : "-1");
      tab.classList.toggle("is-done", viewDone(view));
    }
    $("extraction-view").hidden = state.view !== VIEW.EXTRACTION;
    $("tailor-view").hidden = state.view !== VIEW.TAILOR;
  }

  function viewDone(view) {
    if (view === VIEW.EXTRACTION) return Boolean(state.job);
    if (view === VIEW.PROFILE) return state.profileState === "ready";
    if (view === VIEW.RECONCILIATION) return Boolean(state.reconciliation);
    return state.profileState === "ready";
  }

  function announce(message) {
    // Both review views have their own live region; the visible one is the
    // one that is announced.
    setText("profile-status", message || "");
    setText("reconciliation-status", message || "");
  }

  function findProposal(proposalId) {
    const proposals = state.profileView?.proposals || [];
    return proposals.find((proposal) => proposal.id === proposalId) || null;
  }

  function refreshProfileView() {
    if (!state.profile || !cvr) {
      state.profileView = null;
      return;
    }
    state.profileView = cvr.buildViewModel(
      state.profile.profile,
      state.review,
      cvp,
    );

  }

  /* Both review views show the same decisions, so they are refreshed together. */
  function renderReviewViews() {
    refreshProfileView();
    renderProfile();
    renderReconciliation();
  }

  function proposalStatusMeta(proposal) {
    if (proposal.status === "approved") {
      return { label: "Approved", tone: "ok" };
    }
    if (proposal.status === "rejected") {
      return { label: "Rejected", tone: "error" };
    }
    if (proposal.status === "superseded") {
      return { label: "Superseded", tone: "neutral" };
    }
    return { label: "To review", tone: "warn" };
  }

  function evidenceRefLabel(evidence) {
    const name = evidence.document?.filename || evidence.documentId;
    return `${name} · ${locatorLabel(evidence.locator)}`;
  }

  function renderEvidence(proposal) {
    if (!proposal.evidence.length) {
      return el("p", {
        className: "evidence-unverified",
        text: "This proposal has no citation, so it cannot be approved.",
      });
    }

    const details = el("details", { className: "evidence-details" });
    details.append(
      el("summary", {
        text: `See ${plural(proposal.evidence.length, "original quote", "original quotes")}`,
      }),
    );

    const fieldset = el("fieldset", {
      className: "proposal-evidence",
      children: [
        el("legend", {
          text: `Citations compared with this session’s extracted text (${proposal.evidence.length})`,
        }),
      ],
    });

    for (const evidence of proposal.evidence) {
      const supportTone =
        evidence.supportTone === "ok"
          ? "ok"
          : evidence.supportTone === "warn"
            ? "warn"
            : "neutral";
      const citation =
        evidence.verified === true
          ? { label: "Citation matched", tone: "ok" }
          : evidence.verified === false
            ? { label: "Citation mismatch", tone: "error" }
            : { label: "Citation not checked", tone: "neutral" };

      fieldset.append(
        el("div", {
          className: "evidence-item",
          children: [
            el("div", {
              className: "evidence-ref",
              children: [
                el("span", { text: evidenceRefLabel(evidence) }),
                el("span", {
                  className: `badge badge-${supportTone}`,
                  text: evidence.supportLabel,
                  attrs: { title: evidence.supportDescription },
                }),
                el("span", {
                  className: `badge badge-${citation.tone}`,
                  text: citation.label,
                  attrs: {
                    title:
                      evidence.verified === true
                        ? "The quote matches the extracted text at the stated offsets."
                        : evidence.verified === false
                          ? "The quote does not match the extracted text at the stated offsets."
                          : "This session has not checked the citation yet.",
                  },
                }),
              ],
            }),
            el("blockquote", {
              className: "evidence-quote",
              text: evidence.quote ? `“${evidence.quote}”` : "(no quote)",
            }),
            evidence.reason
              ? el("p", { className: "evidence-unverified", text: evidence.reason })
              : null,
          ],
        }),
      );
    }

    details.append(fieldset);
    return details;
  }

  function proposalSourceSummary(proposal) {
    if (!proposal.evidence.length) return "No citation · cannot be approved";
    const documents = new Set();
    for (const evidence of proposal.evidence) {
      documents.add(evidence.document?.filename || evidence.documentId);
    }
    const explicit = proposal.evidence.filter(
      (evidence) => evidence.support === "explicit_claim",
    ).length;
    const mentions = proposal.evidence.filter(
      (evidence) => evidence.support === "keyword_mention",
    ).length;
    const mismatches = proposal.evidence.filter(
      (evidence) => evidence.verified !== true,
    ).length;
    const parts = [plural(proposal.evidence.length, "quote", "quotes")];
    parts.push(plural(documents.size, "document"));
    if (mismatches) {
      parts.push(plural(mismatches, "citation mismatch", "citation mismatches"));
    } else {
      parts.push("citations matched");
    }
    if (explicit) parts.push(plural(explicit, "explicit claim", "explicit claims"));
    if (mentions) parts.push(plural(mentions, "keyword mention", "keyword mentions"));
    return parts.join(" · ");
  }

  function renderProposalConflicts(proposal) {
    if (!proposal.conflicts.length) return null;

    const box = el("div", { className: "proposal-conflicts" });
    for (const conflict of proposal.conflicts) {
      const card = el("div", {
        className: `conflict-card${conflict.resolved ? " conflict-resolved" : ""}`,
        children: [
          el("strong", {
            text: conflict.resolved ? "Conflict resolved" : "Conflict pending",
          }),
          el("span", {
            text: conflict.message
              ? `${conflict.message} `
              : "The engine found a conflict with another proposal. ",
          }),
          el("span", {
            text: conflict.known
              ? `Conflict ${conflict.conflictId}.`
              : `Conflict ${conflict.conflictId} is not in the response.`,
          }),
        ],
      });

      if (conflict.resolved && conflict.resolution) {
        card.append(
          el("span", {
            className: "conflict-record",
            text: `Recorded in the log: kept ${
              conflict.resolution.kept.join(", ") || "nothing"
            }. Note: ${conflict.resolution.note}`,
          }),
        );
      } else if (conflict.resolved === false) {
        card.append(
          el("span", {
            className: "conflict-record",
            text: "Resolve it in the conflicts section before approving this fact.",
          }),
        );
      }

      box.append(card);
    }
    return box;
  }

  function renderConflictResolutionForm(conflict) {
    const form = el("form", {
      className: "proposal-edit",
      attrs: {
        "aria-label": `Resolve conflict ${conflict.conflictId}`,
      },
    });

    const choices = el("fieldset", { className: "conflict-choices" });
    choices.append(
      el("legend", { text: "Which proposals do you keep?" }),
    );

    for (const proposalId of conflict.proposalIds) {
      const proposal = findProposal(proposalId);
      const inputId = `conflict-${conflict.conflictId}-${proposalId}`;
      const input = el("input", {
        attrs: { id: inputId, name: proposalId, type: "checkbox" },
      });
      choices.append(
        el("div", {
          className: "proposal-field proposal-field-inline",
          children: [
            el("label", {
              attrs: { for: inputId },
              text: proposal
                ? `${proposal.label} (${categoryLabel(proposal.category, true).toLowerCase()})`
                : proposalId,
            }),
            input,
          ],
        }),
      );
    }

    const noteId = `conflict-note-${conflict.conflictId}`;
    const note = el("textarea", {
      attrs: {
        id: noteId,
        name: "note",
        rows: "3",
        placeholder: "Why is it resolved this way?",
      },
    });

    form.append(choices);
    form.append(
      el("div", {
        className: "proposal-field",
        children: [
          el("label", { attrs: { for: noteId }, text: "How did you resolve it?" }),
          note,
        ],
      }),
    );
    form.append(
      el("div", {
        className: "proposal-actions",
        children: [
          el("button", {
            className: "button button-compact button-primary",
            attrs: { type: "submit" },
            text: "Record decision",
          }),
          el("button", {
            className: "button button-compact button-quiet",
            attrs: { type: "button" },
            text: "Cancel",
          }),
        ],
      }),
    );

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      resolveConflict(conflict.conflictId, form);
    });
    form.querySelectorAll("button")[1].addEventListener("click", () => {
      state.conflictForm = null;
      renderProfile();
    });

    return form;
  }

  function renderConflictQuotes(conflict) {
    const box = el("ul", { className: "conflict-quotes" });

    for (const proposalId of conflict.proposalIds) {
      const proposal = findProposal(proposalId);
      if (!proposal) continue;

      const item = el("li", { className: "conflict-quote-item" });
      item.append(el("strong", { text: proposal.label }));
      for (const evidence of proposal.evidence.slice(0, 2)) {
        item.append(
          el("span", {
            className: "conflict-quote-ref",
            text: evidenceRefLabel(evidence),
          }),
        );
        item.append(
          el("blockquote", {
            className: "evidence-quote",
            text: evidence.quote ? `“${evidence.quote}”` : "(no quote)",
          }),
        );
      }
      box.append(item);
    }

    return box;
  }

  function renderConflictsSection() {
    const container = $("profile-conflicts");
    clearNode(container);

    const conflicts = state.profileView?.conflicts || [];
    setText("profile-conflicts-count", plural(conflicts.length, "conflict"));
    $("profile-conflicts-empty").hidden = conflicts.length > 0;

    for (const conflict of conflicts) {
      const card = el("article", {
        className: `conflict-card${conflict.resolved ? " conflict-resolved" : ""}`,
        attrs: { "aria-labelledby": `conflict-${conflict.conflictId}` },
      });

      const heading = conflict.resolved
        ? "Conflict resolved"
        : conflict.resolutionHint && conflict.suggestion
            ? "Engine suggestion"
            : "Unresolved conflict";

      card.append(
        el("strong", {
          attrs: { id: `conflict-${conflict.conflictId}` },
          text: heading,
        }),
        el("p", {
          className: "conflict-message",
          text: conflict.message
            ? `Engine text: “${conflict.message}”`
            : "The engine detected a conflict without a message.",
        }),
        el("p", {
          className: "conflict-meta",
          text: `${categoryLabel(conflict.category)} · ${plural(
            conflict.proposalIds.length,
            "proposal",
          )} · ${conflict.conflictId}`,
        }),
      );

      if (conflict.resolutionHint && conflict.suggestion) {
        card.append(
          el("p", {
            className: "conflict-recommendation",
            text: `The engine suggests keeping: ${conflict.suggestion.label}`,
          }),
        );
        card.append(
          el("p", {
            className: "conflict-explanation",
            text: `The engine explains: ${conflict.resolutionHint.explanation}`,
          }),
        );
        card.append(
          el("p", {
            className: "conflict-meta",
            text: "This is an engine suggestion. This screen has not confirmed the level, date, or claim, and accepting it approves no fact.",
          }),
        );
      } else if (conflict.resolutionHintIssue) {
        card.append(
          el("p", {
            className: "conflict-meta",
            text: `The engine suggestion could not be used: ${conflict.resolutionHintIssue}. Resolve the conflict manually.`,
          }),
        );
      }

      card.append(renderConflictQuotes(conflict));

      if (conflict.resolved && conflict.resolution) {
        card.append(
          el("p", {
            className: "conflict-record",
            text: `Resolved at step ${conflict.resolution.sequence} by ${
              conflict.resolution.source === "recommendation"
                ? "the engine suggestion"
                : "you"
            }. Kept: ${conflict.resolution.kept.join(", ") || "nothing"}. Note: ${
              conflict.resolution.note
            }`,
          }),
        );
      } else if (state.conflictForm === conflict.conflictId) {
        card.append(renderConflictResolutionForm(conflict));
      } else {
        const actions = el("div", { className: "proposal-actions" });

        if (conflict.resolutionHint && conflict.suggestion) {
          const use = el("button", {
            className: "button button-compact button-secondary",
            attrs: {
              type: "button",
              "aria-label": `Record the engine suggestion for ${conflict.conflictId}`,
            },
            text: "Record suggestion",
          });
          use.addEventListener("click", () => useRecommendation(conflict.conflictId));
          actions.append(use);
        }

        const resolve = el("button", {
          className: "button button-compact button-primary",
          attrs: {
            type: "button",
            "aria-label": `Resolve ${conflict.conflictId} manually`,
          },
          text: conflict.resolutionHint ? "Resolve manually" : "Resolve this conflict",
        });
        resolve.addEventListener("click", () => {
          state.conflictForm = conflict.conflictId;
          renderProfile();
          const field = document.querySelector(
            '#profile-conflicts input[type="checkbox"]',
          );
          if (field && typeof field.focus === "function") field.focus();
        });
        actions.append(resolve);

        card.append(actions);
      }

      container.append(card);
    }
  }

  function renderSupersededSection() {
    const container = $("profile-superseded");
    clearNode(container);

    const superseded = state.profileView?.superseded || [];
    setText(
      "profile-superseded-count",
      plural(superseded.length, "revision", "revisions"),
    );
    $("profile-superseded-empty").hidden = superseded.length > 0;

    for (const proposal of superseded) {
      container.append(
        el("article", {
          className: "proposal-card proposal-superseded",
          attrs: {
            id: `proposal-${proposal.id}`,
            "aria-labelledby": `proposal-label-${proposal.id}`,
          },
          children: [
            el("div", {
              className: "proposal-head",
              children: [
                el("span", {
                  className: "proposal-category",
                  text: categoryLabel(proposal.category, true),
                }),
                statusPill(proposalStatusMeta(proposal)),
              ],
            }),
            el("h4", {
              className: "proposal-label",
              attrs: { id: `proposal-label-${proposal.id}`, tabindex: "-1" },
              text: displaySubject(proposal.label),
            }),
            el("p", {
              className: "proposal-note",
              text: proposal.isRevision
                ? "This revision was replaced by a later edit."
                : "A revision replaced this fact. Its approval does not carry over.",
            }),
          ],
        }),
      );
    }
  }

  function renderHistorySection() {
    const container = $("profile-history");
    clearNode(container);

    const history = state.profileView?.history || [];
    setText("profile-history-count", plural(history.length, "step"));
    $("profile-history-empty").hidden = history.length > 0;

    const list = el("ol", { className: "history-list" });
    for (const event of history) {
      let text = "";
      if (event.kind === "approve") {
        text = `You approved ${event.label || event.proposal_id}.`;
      } else if (event.kind === "reject") {
        text = `You rejected ${event.label || event.proposal_id}.`;
      } else if (event.kind === "edit") {
        text = `You edited ${event.label || event.proposal_id}; a revision was created${
          event.supported ? "" : " without a quote to support it"
        }. The earlier approval was revoked.`;
      } else if (event.kind === "resolve_conflict") {
        text = `You resolved conflict ${event.detail?.conflict_id} manually: kept ${
          (event.detail?.kept || []).join(", ") || "nothing"
        }. Note: ${event.detail?.note}`;
      } else if (event.kind === "use_recommendation") {
        text = `You recorded the engine suggestion for conflict ${
          event.detail?.conflict_id
        }: kept ${(event.detail?.kept || []).join(", ") || "nothing"}. The facts remain proposed. Note: ${event.detail?.note}`;
      }

      list.append(
        el("li", {
          className: "history-item",
          children: [
            el("span", { className: "history-step", text: String(event.sequence) }),
            el("span", { text }),
          ],
        }),
      );
    }
    container.append(list);
  }

  function renderEditForm(proposal) {
    const form = el("form", {
      className: "proposal-edit",
      attrs: {
        "aria-label": `Edit ${categoryLabel(proposal.category, true).toLowerCase()} ${proposal.label}`,
      },
    });

    const editable = proposal.fields.filter(
      (field) =>
        field === proposal.primaryField ||
        Object.prototype.hasOwnProperty.call(proposal.value, field),
    );

    for (const field of editable) {
      const inputId = `proposal-field-${proposal.id}-${field}`;
      let input;
      if (field === "level") {
        input = el("select", { attrs: { id: inputId, name: field } });
        for (const level of cvp.DEGREE_LEVELS) {
          input.append(
            el("option", {
              attrs: {
                value: level,
                selected: proposal.value[field] === level ? true : undefined,
              },
              text: level,
            }),
          );
        }
      } else {
        input = el("input", {
          attrs: {
            id: inputId,
            name: field,
            type: "text",
            value: proposal.value[field] ?? "",
          },
        });
      }

      form.append(
        el("div", {
          className: "proposal-field",
          children: [
            el("label", {
              attrs: { for: inputId },
              text: FIELD_ES[field] || cvp.fieldLabel(field),
            }),
            input,
          ],
        }),
      );
    }

    form.append(
      el("div", {
        className: "proposal-actions",
        children: [
          el("button", {
            className: "button button-compact button-primary",
            attrs: { type: "submit" },
            text: "Save as new revision",
          }),
          el("button", {
            className: "button button-compact button-quiet",
            attrs: { type: "button" },
            text: "Cancel",
          }),
        ],
      }),
    );

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      saveProposalEdit(proposal.id, form);
    });
    form.querySelectorAll("button")[1].addEventListener("click", () => {
      state.profileEditing = null;
      renderProfile();
      focusProposal(proposal.id);
    });

    return form;
  }

  /*
   * A suggestion only marks the proposal the engine actually put in
   * keepProposalIds. Marking every proposal of a conflict as "recommended"
   * was misleading: the engine keeps one side and drops the other.
   */
  function recommendationFor(proposal) {
    const globals = state.profileView?.conflicts || [];
    return (
      proposal.conflicts.find((conflict) => {
        if (conflict.resolved) return false;
        const global = globals.find(
          (item) => item.conflictId === conflict.conflictId,
        );
        return Boolean(
          global?.resolutionHint &&
            Array.isArray(global.resolutionHint.keepProposalIds) &&
            global.resolutionHint.keepProposalIds.includes(proposal.id),
        );
      }) || null
    );
  }

  function renderProposalCard(proposal) {
    const card = el("article", {
      className: `proposal-card proposal-${proposal.status}`,
      attrs: {
        id: `proposal-${proposal.id}`,
        "aria-labelledby": `proposal-label-${proposal.id}`,
      },
    });

    const head = el("div", {
      className: "proposal-head",
      children: [
        el("span", {
          className: "proposal-category",
          text: categoryLabel(proposal.category, true),
        }),
        statusPill(proposalStatusMeta(proposal)),
      ],
    });

    const recommended = recommendationFor(proposal);
    if (recommended) {
      head.append(
        el("span", {
          className: "badge badge-active",
          text: "Suggested",
          attrs: {
            title:
              "The engine suggests keeping this proposal in a conflict. It is not an approval.",
          },
        }),
      );
    }
    if (proposal.isRevision) {
      head.append(
        el("span", {
          className: "badge badge-active",
          text: "Revision",
          attrs: { title: `New revision of ${proposal.revisionOf}` },
        }),
      );
    }
    if (proposal.unresolvedConflicts) {
      head.append(
        el("span", {
          className: "badge badge-warn",
          text: plural(proposal.unresolvedConflicts, "conflict"),
        }),
      );
    }
    if (proposal.conflicts.length && !proposal.unresolvedConflicts) {
      head.append(
        el("span", {
          className: "badge badge-warn",
          text: proposal.conflicts.some((conflict) => conflict.kept === false)
            ? "Not kept"
            : "Conflict resolved",
        }),
      );
    }
    if (!proposal.evidence.length) {
      head.append(el("span", { className: "badge badge-warn", text: "No quote" }));
    } else if (proposal.evidence.some((entry) => entry.verified !== true)) {
      head.append(
        el("span", {
          className: "badge badge-error",
          text: "Citation mismatch",
          attrs: { title: "The quote does not match the text extracted in this session." },
        }),
      );
    }

    card.append(head);
    card.append(
      el("h4", {
        className: "proposal-label",
        attrs: { id: `proposal-label-${proposal.id}`, tabindex: "-1" },
        text: displaySubject(proposal.label),
      }),
    );
    card.append(
      el("p", {
        className: "proposal-sources",
        text: proposalSourceSummary(proposal),
      }),
    );

    if (proposal.details.length) {
      const details = el("dl", { className: "proposal-details" });
      for (const detail of proposal.details) {
        details.append(
          el("dt", { text: FIELD_ES[detail.key] || detail.label }),
        );
        const value =
          detail.key === "stated_level" || detail.key === "level"
            ? detail.value.toUpperCase()
            : detail.value === "not stated"
              ? "not stated"
              : detail.value;
        details.append(el("dd", { text: value }));
      }
      card.append(details);
    }

    if (proposal.revisionOf) {
      card.append(
        el("p", {
          className: "proposal-note",
          text: "This is a new revision. It starts as a proposal and the earlier approval was revoked.",
        }),
      );
    }

    if (!proposal.canApprove && proposal.approveReason) {
      card.append(
        el("p", {
          className: "proposal-note proposal-note-error",
          text: `Cannot approve yet: ${proposal.approveReason}`,
        }),
      );
    }

    card.append(renderEvidence(proposal));

    const conflicts = renderProposalConflicts(proposal);
    if (conflicts) card.append(conflicts);

    const label = categoryLabel(proposal.category, true).toLowerCase();
    const approve = el("button", {
      className: "button button-compact button-primary",
      attrs: {
        type: "button",
        "aria-label": `Approve ${proposal.label} (${label})`,
      },
      text: "Approve",
    });
    approve.disabled = !proposal.canApprove;
    if (!proposal.canApprove) approve.title = proposal.approveReason;
    approve.addEventListener("click", () => approveProposal(proposal.id));

    const reject = el("button", {
      className: "button button-compact button-secondary",
      attrs: {
        type: "button",
        "aria-label": `Reject ${proposal.label} (${label})`,
      },
      text: "Reject",
    });
    reject.disabled = proposal.isSuperseded;
    reject.addEventListener("click", () => rejectProposal(proposal.id));

    const edit = el("button", {
      className: "button button-compact button-quiet",
      attrs: {
        type: "button",
        "aria-label": `Edit ${proposal.label} (${label})`,
      },
      text: "Edit",
    });
    edit.disabled = proposal.isSuperseded;
    edit.addEventListener("click", () => openProposalEditor(proposal.id));

    card.append(
      el("div", {
        className: "proposal-actions",
        children: [approve, reject, edit],
      }),
    );

    if (state.profileEditing === proposal.id) {
      card.append(renderEditForm(proposal));
    }

    return card;
  }

  function focusProposal(proposalId) {
    const node = document.getElementById(`proposal-label-${proposalId}`);
    if (node && typeof node.focus === "function") {
      node.focus({ preventScroll: true });
    }
  }

  function approveProposal(proposalId) {
    const proposal = findProposal(proposalId);
    if (!proposal) return;

    const result = cvr.applyReviewAction(
      state.review,
      { kind: "approve", proposalId },
      { adapter: cvp },
    );
    if (!result.applied) {
      announce(result.reason);
      return;
    }

    state.review = result.state;
    renderReviewViews();
    announce(`You approved ${proposal.label}.`);
    focusProposal(proposalId);
  }

  function rejectProposal(proposalId) {
    const proposal = findProposal(proposalId);
    if (!proposal) return;

    const result = cvr.applyReviewAction(
      state.review,
      { kind: "reject", proposalId },
      { adapter: cvp },
    );
    if (!result.applied) {
      announce(result.reason);
      return;
    }

    state.review = result.state;
    renderReviewViews();
    announce(`You rejected ${proposal.label}.`);
    focusProposal(proposalId);
  }

  function openProposalEditor(proposalId) {
    state.profileEditing = proposalId;
    renderProfile();

    const form = document.querySelector(`#proposal-${proposalId} .proposal-edit`);
    const first = form?.querySelector("input, select");
    if (first && typeof first.focus === "function") {
      first.focus();
    }
  }

  function saveProposalEdit(proposalId, form) {
    const proposal = findProposal(proposalId);
    if (!proposal) return;

    const value = { ...proposal.value };
    for (const field of proposal.fields) {
      const input = form.querySelector(`[name="${field}"]`);
      if (!input) continue;
      value[field] = input.value.trim();
    }

    const result = cvr.applyReviewAction(
      state.review,
      { kind: "edit", proposalId, value },
      { adapter: cvp },
    );
    if (!result.applied) {
      announce(result.reason);
      return;
    }

    state.review = result.state;
    state.profileEditing = null;
    renderReviewViews();
    announce(
      result.supported
        ? "Saved as a new revision. It is proposed again and the earlier approval was revoked."
        : "Saved as a new revision. No quote supports the new text, so it cannot be approved.",
    );
    focusProposal(result.revisionId);
  }

  function resolveConflict(conflictId, form) {
    const kept = Array.from(
      form.querySelectorAll('input[type="checkbox"]'),
    )
      .filter((input) => input.checked)
      .map((input) => input.name);
    const note = form.querySelector('textarea[name="note"]')?.value.trim() || "";

    const result = cvr.applyReviewAction(
      state.review,
      { kind: "resolve_conflict", conflictId, kept, note },
      { adapter: cvp },
    );
    if (!result.applied) {
      announce(result.reason);
      return;
    }

    state.review = result.state;
    state.conflictForm = null;
    renderReviewViews();
    announce(
      `Conflict ${conflictId} resolved manually. The decision is in this tab’s log.`,
    );
  }

  /*
   * Taking the suggestion of the backend records a decision about the
   * conflict. It never approves a fact: the proposals stay proposed until the
   * reviewer approves them one by one.
   */
  function useRecommendation(conflictId) {
    const result = cvr.applyReviewAction(
      state.review,
      { kind: "use_recommendation", conflictId },
      { adapter: cvp },
    );
    if (!result.applied) {
      announce(result.reason);
      return;
    }

    state.review = result.state;
    state.conflictForm = null;
    renderReviewViews();
    announce(
      `Suggestion recorded for conflict ${conflictId}. The facts remain proposed until you approve them.`,
    );
  }

  function profileErrorHint(error) {
    if (error?.code === "contract_error") {
      return "The profile response does not match schema 0.1. Compare it with docs/cv-profile-workspace.md and update web/workspace/profile-adapter.js.";
    }
    if (error?.status === 404) {
      return "There is no profile route at the configured API base. The profile engine is not mounted in this screen yet.";
    }
    if (error?.status === 503) {
      return "The profile engine is not available on this server. No proposals were returned.";
    }
    if (error?.code === "network_error") {
      return "Could not reach the profile service. Check that the server exposes the profile route at the configured API base.";
    }
    return "The profile request failed. Check the error above and try again.";
  }

  async function buildProfile() {
    if (!profileAdapter) {
      state.profileState = "error";
      state.profileError = profileAdapterError;
      renderProfile();
      return;
    }
    if (!state.job || !state.job.documents?.length) {
      announce("Analyse a document first: the profile is built from the extracted text.");
      return;
    }

    state.profileState = "loading";
    state.profileError = null;
    renderProfile();

    try {
      const profile = await profileAdapter.createProfile(state.job);
      state.profile = { profile, synthetic: false, label: "" };
      state.profileState = "ready";
      state.profileError = null;
      state.profileEditing = null;
      state.conflictForm = null;
      state.review = cvr.createReviewState(profile);
      renderReviewViews();
      announce(
        `The profile engine returned ${plural(profile.counts.total, "proposal")}. Nothing is approved yet.`,
      );
    } catch (error) {
      state.profileState = "error";
      state.profileError = error;
      state.profile = null;
      state.profileView = null;
      renderProfile();
    }
  }

  async function loadSyntheticProfile(
    envelopeUrl = PREVIEW_ENVELOPE_FIXTURE,
    sourceUrl = PREVIEW_SOURCE_FIXTURE,
  ) {
    if (!profileAdapter) {
      state.profileState = "error";
      state.profileError = profileAdapterError;
      renderProfile();
      return;
    }

    state.profileState = "loading";
    state.profileError = null;
    renderProfile();

    try {
      const result = await profileAdapter.loadPreview(sourceUrl, envelopeUrl);
      state.profile = {
        profile: result.profile,
        synthetic: true,
        label: result.label,
      };
      state.profileState = "ready";
      state.profileError = null;
      state.profileEditing = null;
      state.conflictForm = null;
      state.review = cvr.createReviewState(result.profile);
      renderReviewViews();
      announce(
        `Synthetic sample loaded with ${plural(result.profile.counts.total, "proposal")}.`,
      );
    } catch (error) {
      state.profileState = "error";
      state.profileError = error;
      state.profile = null;
      state.profileView = null;
      renderProfile();
    }
  }

  function clearProfile() {
    state.profile = null;
    state.profileView = null;
    state.profileState = "idle";
    state.profileError = null;
    state.profileEditing = null;
    state.conflictForm = null;
    state.review = null;
    state.profileFilter = "all";
    renderProfile();
    announce("Review cleared. Your decisions only existed in this tab.");
  }

  function buildApprovedProfilePayload() {
    const profile = state.profile;
    const review = state.review;
    if (!profile || !review) return null;
    const approved = (state.profileView?.proposals || []).filter((p) => p.status === "approved");
    const job = state.job;
    const documents = (job?.documents || []).map((d) => ({
      document_id: d.id,
      index: d.index,
      filename: d.filename,
      status: d.status,
      format: d.format,
      segment_count: (d.segments || []).length,
      text_length: (d.fullText || "").length,
    }));
    const facts = approved.map((p) => ({
      fact_id: p.id,
      category: p.category,
      value: p.value,
      evidence: (p.evidence || []).map((e) => ({
        document_id: e.documentId,
        segment_index: e.segmentIndex,
        locator: Object.fromEntries(Object.entries(e.locator).filter(([,v]) => v !== null)),
        quote: e.quote,
        start: e.start,
        end: e.end,
        support: e.support,
      })),
      source_document_ids: [...new Set((p.evidence || []).map((e) => e.documentId))],
      review_sequence: review.sequence || 0,
    }));
    return {
      approved_profile_version: "0.1",
      parser_schema_version: profile.profile.parserSchemaVersion,
      profile_schema_version: profile.profile.schemaVersion,
      job_id: profile.profile.jobId,
      documents,
      facts,
      candidate: { full_name: null, email: null, phone: null, location: null, links: [] },
      review_sequence: review.sequence || 0,
      review_history: (review.history || []).map((h) => ({ ...h })),
      warnings: profile.profile.warnings || [],
    };
  }

  async function exportApprovedProfile() {
    let payload = buildApprovedProfilePayload();
    if (!payload || !payload.facts.length) {
      announce("No approved facts to export.");
      return;
    }
    if (!window.confirm("Confirm that you explicitly approved these facts and want to save their private source evidence locally?")) return;
    try {
      const result = await new cv.CvApiAdapter({ baseUrl: apiBase() }).validateApprovedProfile(state.job, payload);
      payload = result.approved_profile;
    } catch (error) { announce(error.message); return; }
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "approved-profile.json";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    state.tailor.approvedProfile = payload;
    announce("Approved profile exported and loaded for tailoring.");
    renderTailor();
  }

  async function importApprovedProfile(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const payload = JSON.parse(text);
      if (!window.confirm("Revalidate and confirm the approved facts in this private profile?")) return;
      const job = state.job;
      const result = await new cv.CvApiAdapter({ baseUrl: apiBase() }).validateApprovedProfile(job, payload);
      state.tailor.approvedProfile = result.approved_profile || payload;
      announce("Approved profile imported and validated.");
      renderTailor();
    } catch (error) {
      state.tailor.error = error?.message || "Import failed.";
      renderTailor();
    } finally {
      event.target.value = "";
    }
  }

  function filterMatchesProposal(proposal, filter) {
    if (filter === "proposed") return proposal.status === "proposed";
    if (filter === "approved") return proposal.status === "approved";
    if (filter === "rejected") return proposal.status === "rejected";
    return true;
  }

  function renderProfileFilters() {
    const container = $("profile-filters");
    clearNode(container);
    const counts = state.profileView?.counts;
    container.hidden = !counts;
    if (!counts) return;

    const options = [
      { id: "all", label: `All (${counts.total})` },
      { id: "proposed", label: `To review (${counts.proposed})` },
      { id: "approved", label: `Approved (${counts.approved})` },
      { id: "rejected", label: `Rejected (${counts.rejected})` },
    ];
    if (!options.some((option) => option.id === state.profileFilter)) {
      state.profileFilter = "all";
    }

    for (const option of options) {
      const active = state.profileFilter === option.id;
      const chip = el("button", {
        className: `filter-chip${active ? " is-active" : ""}`,
        attrs: {
          type: "button",
          "aria-pressed": active ? "true" : "false",
        },
        text: option.label,
      });
      chip.addEventListener("click", () => {
        state.profileFilter = option.id;
        renderProfile();
      });
      container.append(chip);
    }
  }

  function renderProfile() {
    const view = $("profile-view");
    view.hidden = state.view !== VIEW.PROFILE;

    const badge = $("profile-badge");
    const schemaBadge = $("profile-schema-badge");
    const banner = $("profile-banner");
    const build = $("profile-build");
    const preview = $("profile-preview");
    const previewSuggestion = $("profile-preview-suggestion");
    const clear = $("profile-clear");
    const groups = $("profile-groups");
    const empty = $("profile-empty");

    clearNode(groups);

    const loading = state.profileState === "loading";
    const ready = state.profileState === "ready" && state.profileView;
    const hasExtraction = Boolean(state.job && state.job.documents?.length);

    build.disabled = loading || !hasExtraction;
    preview.disabled = true;
    previewSuggestion.disabled = true;
    clear.hidden = !ready;
    build.textContent = loading ? "Creating…" : "Create the profile from these documents";
    preview.textContent = loading ? "Loading…" : "Load synthetic sample";
    previewSuggestion.textContent = loading
      ? "Loading…"
      : "Load synthetic sample with a suggestion";

    if (ready) {
      const counts = state.profileView.counts;

      badge.className = state.profile.synthetic ? "badge badge-warn" : "badge badge-ok";
      badge.textContent = state.profile.synthetic ? "Synthetic sample" : "Engine profile";
      badge.title = state.profile.synthetic
        ? "Sample data for the review interface. It is not a real person or reader text."
        : "Proposals returned by the profile engine.";
      schemaBadge.className = "badge badge-neutral";
      schemaBadge.textContent = `Schema ${state.profile.profile.schemaVersion}`;

      setText(
        "profile-title",
        state.profile.synthetic ? "Review the sample proposals" : "Review these facts",
      );
      setText(
        "profile-subtitle",
        `${plural(counts.total, "proposal")} · ${counts.proposed} to review · decisions stay in this tab`,
      );

      banner.hidden = false;
      if (state.profile.synthetic) {
        banner.className = "banner banner-warn";
        setText("profile-banner-title", "Sample data");
        setText(
          "profile-banner-copy",
          `${state.profile.label} These proposals exist to test the interface. They are not a real person, reader text, or a real profile.`,
        );
        setText(
          "profile-hint",
          "The reader produced none of this. Clear the sample to leave this view.",
        );
      } else {
        banner.className = "banner banner-ok";
        setText("profile-banner-title", "Profile ready");
        setText(
          "profile-banner-copy",
          `The profile engine returned ${plural(counts.total, "proposal")}. Every fact remains a proposal until you approve it here.`,
        );
        setText(
          "profile-hint",
          "Approve, reject, or edit each fact. Editing creates a new revision. Nothing is stored: refreshing loses your decisions.",
        );
      }

      setText("profile-count-proposed", String(counts.proposed));
      setText(
        "profile-count-proposed-note",
        counts.proposed ? "Awaiting your decision" : "Nothing pending",
      );
      setText("profile-count-approved", String(counts.approved));
      setText(
        "profile-count-approved-note",
        counts.approved ? "Decided by you" : "None yet",
      );
      setText("profile-count-rejected", String(counts.rejected));
      setText(
        "profile-count-rejected-note",
        counts.rejected ? "Will not be used" : "None",
      );
      setText("profile-count-unresolved", String(counts.unresolved));
      setText(
        "profile-count-unresolved-note",
        counts.unresolved
          ? `${plural(counts.unresolved, "conflict")} to resolve`
          : counts.conflicts
            ? "None blocking"
            : "None",
      );
      setText("profile-count-superseded", String(counts.superseded));
      setText(
        "profile-count-superseded-note",
        counts.superseded ? "Earlier versions, in the log" : "No versions",
      );

      renderProfileFilters();

      let visible = 0;
      for (const group of state.profileView.groups) {
        const proposals = group.proposals.filter((proposal) =>
          filterMatchesProposal(proposal, state.profileFilter),
        );
        if (!proposals.length) continue;
        visible += proposals.length;

        const section = el("section", {
          className: "profile-group",
          attrs: { "aria-labelledby": `profile-group-${group.category}` },
        });

        section.append(
          el("div", {
            className: "profile-group-head",
            children: [
              el("h3", {
                attrs: { id: `profile-group-${group.category}` },
                text: categoryLabel(group.category),
              }),
              el("span", {
                className: "count",
                text: plural(proposals.length, "proposal"),
              }),
            ],
          }),
        );

        const list = el("div", { className: "proposal-list" });
        for (const proposal of proposals) {
          list.append(renderProposalCard(proposal));
        }
        section.append(list);
        groups.append(section);
      }

      if (!counts.total) {
        empty.textContent = "The profile engine returned no proposals.";
        empty.hidden = false;
      } else if (!visible) {
        empty.textContent = "No proposals match this filter. Change the filter to see the rest.";
        empty.hidden = false;
      } else {
        empty.hidden = true;
      }

      renderConflictsSection();
      renderSupersededSection();
      renderHistorySection();
      return;
    }

    renderProfileFilters();
    empty.hidden = true;
    badge.className = "badge badge-neutral";
    schemaBadge.className = "badge badge-neutral";
    schemaBadge.textContent = "Schema —";

    if (loading) {
      badge.textContent = "Trabajando";
      badge.title = "Waiting for the profile service.";
      setText("profile-title", "Creating the profile");
      setText("profile-subtitle", "Waiting for the profile engine response.");
      banner.hidden = false;
      banner.className = "banner banner-info";
      setText("profile-banner-title", "Contacting the profile engine");
      setText(
        "profile-banner-copy",
        "There are no proposals until the service responds.",
      );
      setText("profile-hint", "");
      return;
    }

    if (state.profileState === "error") {
      const error = state.profileError || new Error("Could not create the profile.");
      badge.textContent = "Unavailable";
      badge.title = "The profile engine did not respond.";
      setText("profile-title", "Profile unavailable");
      setText("profile-subtitle", "The profile engine did not respond.");
      banner.hidden = false;
      banner.className = "banner banner-error";
      setText("profile-banner-title", "The profile engine did not respond");
      setText("profile-banner-copy", error.message || "Unknown error.");
      setText("profile-hint", profileErrorHint(error));
      return;
    }

    badge.textContent = "No profile";
    badge.title = "No profile is loaded yet.";
    setText("profile-title", "Review what we found");
    setText("profile-subtitle", "There is no profile yet.");
    banner.hidden = false;
    banner.className = "banner banner-info";
    setText("profile-banner-title", "Create a profile from the extracted text");
    setText(
      "profile-banner-copy",
      "The local engine proposes facts from this extraction. Your decisions stay in memory and are not sent to the server.",
    );
    setText(
      "profile-hint",
      hasExtraction
        ? "Create the profile and review its quotes before approving any proposal."
        : "Analyse PDF or DOCX documents first.",
    );
  }

  // Canonical reconciliation is a separate report, not a second profile review.
  let reconciliationRequest = 0;
  let reconciliationJob = null;
  let reconciliationLoading = false;
  let reconciliationError = "";

  function clearReconciliation() {
    reconciliationRequest += 1;
    reconciliationJob = null;
    reconciliationLoading = false;
    reconciliationError = "";
    state.reconciliation = null;
    state.reconciliationAttention = 0;
    renderAll();
    announce("Comparison cleared. Nothing was approved.");
  }

  async function buildReconciliation() {
    if (!state.job || !cvz) return;
    const job = state.job;
    const request = ++reconciliationRequest;
    reconciliationJob = job;
    reconciliationLoading = true;
    reconciliationError = "";
    state.reconciliation = null;
    renderReconciliation();
    try {
      const report = await new cvz.ReconciliationAdapter({baseUrl: apiBase()}).createReconciliation(job);
      if (request !== reconciliationRequest || state.job !== job) return;
      state.reconciliation = report;
    } catch (error) {
      if (request === reconciliationRequest && state.job === job) reconciliationError = error.message;
    } finally {
      if (request === reconciliationRequest) {
        reconciliationLoading = false;
        renderReconciliation();
      }
    }
  }

  function evidenceSupportLabel(support) {
    return support === "keyword_mention" ? "Keyword mention" : "Explicit claim";
  }

  function renderCanonicalEvidence(evidence) {
    const box = el("ul", {className: "conflict-quotes technical-evidence"});
    const source = cvp.sourceFromJob(state.job);
    for (const entry of evidence) {
      const document = source.documents.find(d => d.id === entry.document_id);
      const citationMatched = cvz.validateEvidence([entry], source)[0].verified;
      box.append(el("li", {children: [
        el("span", {className:"conflict-quote-ref", text: `${document?.filename || entry.document_id} · ${JSON.stringify(entry.locator)} · offsets ${entry.start}–${entry.end} · ${evidenceSupportLabel(entry.support)}`}),
        el("blockquote", {className:"evidence-quote", text: entry.quote}),
        el("span", {
          className: `badge badge-${citationMatched ? "ok" : "error"}`,
          text: citationMatched ? "Citation matched" : "Citation mismatch",
          attrs: { title: citationMatched
            ? "The quote matches the extracted text at the stated offsets."
            : "The quote does not match the extracted text at the stated offsets." },
        }),
      ]}));
    }
    return box;
  }

  function renderCanonicalAttributes(attributes) {
    return el("ul", {children: attributes.map(attribute => el("li", {
      text: `${attribute.name}: ${typeof attribute.value === "string" ? attribute.value : JSON.stringify(attribute.value)} (normalized: ${attribute.normalized})`,
    }))});
  }

  /*
   * The reconciliation view model only regroups the engine report. It never
   * derives a relationship, a decision or an approval. Counts are defined here
   * once so the summary and the cards cannot disagree.
   */
  function reconciliationViewModel(model) {
    const report = model.report;
    const claimById = new Map();
    for (const claim of report.claims) claimById.set(claim.claim_id, claim);
    const relationById = new Map();
    for (const relation of report.relationships) {
      relationById.set(relation.relationship_id, relation);
    }
    const documentById = new Map();
    for (const document of report.documents) {
      documentById.set(document.document_id, document);
    }

    const conflicts = report.relationships.filter((relation) =>
      CONFLICT_RELATIONS.includes(relation.relation),
    );
    const pending = report.decisions.filter(
      (decision) => decision.requires_user_confirmation,
    );
    const coveredRelationships = new Set();
    const coveredClaimIds = new Set();
    const consolidatedClaimIds = new Set();
    for (const consolidated of report.consolidated) {
      for (const id of consolidated.claim_ids || []) {
        consolidatedClaimIds.add(id);
        coveredClaimIds.add(id);
      }
    }
    for (const decision of report.decisions) {
      for (const id of decision.relationship_ids || []) coveredRelationships.add(id);
      for (const id of decision.keep_claim_ids || []) coveredClaimIds.add(id);
      for (const id of decision.merge_claim_ids || []) coveredClaimIds.add(id);
      for (const id of decision.alternative_claim_ids || []) coveredClaimIds.add(id);
    }

    const attention = [];
    for (const decision of report.decisions) {
      const merge = (decision.merge_claim_ids || [])
        .map((id) => claimById.get(id))
        .filter(Boolean);
      if (
        !decision.requires_user_confirmation &&
        decision.outcome === "auto_consolidate" &&
        merge.every((claim) => consolidatedClaimIds.has(claim.claim_id))
      ) {
        continue;
      }
      const relations = (decision.relationship_ids || [])
        .map((id) => relationById.get(id))
        .filter((relation) => relation && CONFLICT_RELATIONS.includes(relation.relation));
      const alternatives = (decision.alternative_claim_ids || [])
        .map((id) => claimById.get(id))
        .filter(Boolean);
      attention.push({
        key: decision.decision_id,
        kind: "decision",
        decision,
        keep: (decision.keep_claim_ids || [])
          .map((id) => claimById.get(id))
          .filter(Boolean),
        merge,
        alternatives,
        others: [...merge, ...alternatives],
        relations,
      });
    }

    const withoutDecision = [];
    for (const relation of conflicts) {
      if (coveredRelationships.has(relation.relationship_id)) continue;
      withoutDecision.push(relation);
      const candidates = [relation.left_claim_id, relation.right_claim_id]
        .map((id) => claimById.get(id))
        .filter(Boolean);
      attention.push({
        key: relation.relationship_id,
        kind: "relation",
        decision: null,
        keep: [],
        merge: [],
        alternatives: candidates,
        others: candidates,
        relations: [relation],
      });
    }

    attention.sort((left, right) => {
      const rank = (item) => {
        if (item.kind === "relation") return 2;
        if (item.decision.outcome === "recommend") return 0;
        return 1;
      };
      return rank(left) - rank(right);
    });

    return {
      report,
      claimById,
      relationById,
      documentById,
      conflicts,
      pending,
      attention,
      withoutDecision,
      coveredClaimIds,
      counts: {
        documents: report.documents.length,
        claims: report.claims.length,
        consolidations: report.consolidated.length,
        conflicts: conflicts.length,
        pending: pending.length,
        unresolved: withoutDecision.length,
      },
    };
  }

  function claimValue(claim) {
    if (!claim) return "";
    const attrs = new Map();
    for (const attribute of claim.attributes) attrs.set(attribute.name, attribute.value);
    if (claim.category === "language") {
      const level = attrs.get("proficiency") ?? attrs.get("stated_level");
      if (!level || /\([A-Za-z0-9]+\)/.test(claim.subject_label)) {
        return claim.subject_label;
      }
      return `${claim.subject_label} · ${String(level).toUpperCase()}`;
    }
    if (claim.category === "achievement" || claim.category === "contribution") {
      return String(attrs.get("text") || claim.subject_label);
    }
    if (claim.category === "employment" || claim.category === "experience") {
      const start = attrs.get("start");
      const end = attrs.get("end");
      const period = start || end ? `${start || "?"}–${end || "present"}` : null;
      return [
        attrs.get("role") || attrs.get("title") || claim.subject_label,
        attrs.get("organization"),
        period,
      ]
        .filter(Boolean)
        .join(" · ");
    }
    if (claim.category === "degree" || claim.category === "education") {
      const parts = [attrs.get("level"), attrs.get("field")].filter(Boolean);
      return parts.length ? parts.join(" · ") : claim.subject_label;
    }
    if (claim.category === "project") {
      const name = attrs.get("name") || claim.subject_label;
      const technologies = attrs.get("technologies");
      return technologies ? `${name} · ${technologies}` : name;
    }
    if (claim.category === "organization") {
      const name = attrs.get("name") || claim.subject_label;
      const role = attrs.get("role");
      return role ? `${name} · ${role}` : name;
    }
    if (claim.category === "skill" || claim.category === "technology" ||
        claim.category === "certification") {
      // The engine keeps a readable label for these categories; the
      // normalised name would read as "django" in the report.
      const label = claim.subject_label || attrs.get("name");
      return label === undefined || label === null ? "" : String(label);
    }
    const name = attrs.get("name");
    return name === undefined || name === null ? claim.subject_label : String(name);
  }

  function claimSource(claim, view) {
    const entry = claim?.evidence?.[0];
    if (!entry) return "No quote";
    const document = view.documentById.get(entry.document_id);
    return `${document?.filename || entry.document_id} · ${locatorLabel(entry.locator)}`;
  }

  function claimQuote(claim) {
    const entry = claim?.evidence?.[0];
    return entry?.quote ? `“${entry.quote}”` : "(no quote)";
  }

  function claimSupportLabel(claim) {
    return claim && claim.qualifier === "keyword_mention"
      ? "Keyword mention"
      : "Explicit claim";
  }

  function claimSupportDescription(claim) {
    return claim && claim.qualifier === "keyword_mention"
      ? "The words appear in the text, but the document does not state this as a fact."
      : "The document states this claim directly.";
  }

  function compareColumn(label, claims, tone, view) {
    const column = el("div", { className: `compare-col compare-${tone}` });
    column.append(el("span", { className: "compare-label", text: label }));
    for (const claim of claims) {
      column.append(
        el("p", { className: "compare-value", text: claimValue(claim) }),
        el("p", {
          className: "compare-support",
          children: [
            el("span", {
              className: `badge badge-${
                claim.qualifier === "keyword_mention" ? "warn" : "ok"
              }`,
              text: claimSupportLabel(claim),
              attrs: { title: claimSupportDescription(claim) },
            }),
            el("span", { className: "compare-source", text: claimSource(claim, view) }),
          ],
        }),
        el("blockquote", { className: "evidence-quote", text: claimQuote(claim) }),
      );
    }
    return column;
  }

  function differenceText(item) {
    const leftClaims = item.keep.length ? item.keep : [item.others[0]];
    const rightClaims = item.keep.length ? item.others : item.others.slice(1);
    if (!leftClaims[0] || !rightClaims[0]) return "";
    const collect = (claims) => {
      const map = new Map();
      for (const claim of claims) {
        for (const attribute of claim.attributes) map.set(attribute.name, attribute.value);
      }
      return map;
    };
    const kept = collect(leftClaims);
    const other = collect(rightClaims);
    const names = new Set([...kept.keys(), ...other.keys()]);
    const rows = [];
    for (const name of names) {
      if (["name", "text", "project", "template", "subject"].includes(name)) continue;
      const left = kept.get(name);
      const right = other.get(name);
      const format = (value) => {
        if (value === undefined || value === null || value === "") return "not stated";
        if (name === "proficiency") return String(value).toUpperCase();
        if (name === "duration_exact") {
          if (value === "exact") return "Exact";
          if (value === "approximate") return "Approximate";
        }
        return String(value);
      };
      if (format(left) === format(right)) continue;
      rows.push(`${attributeLabel(name)}: ${format(left)} / ${format(right)}`);
      if (rows.length >= 3) break;
    }
    return rows.length ? `Key difference · ${rows.join(" · ")}` : "";
  }

  function detectedText(item) {
    const relation = item.relations[0];
    const claim = item.keep[0] || item.others[0];
    const category = claim?.category;
    if (!relation) {
      return "The engine has asked for your confirmation on this fact.";
    }
    if (relation.relation === "contradictory") {
      if (category === "contribution") {
        return "The documents state different details or figures for the same project contribution.";
      }
      if (category === "achievement") {
        return "The documents give different figures for the same achievement.";
      }
      if (category === "employment" || category === "experience") {
        return "The documents give a different duration for the same role.";
      }
      return "The documents say incompatible things about the same fact.";
    }
    if (relation.relation === "potentially_conflicting") {
      if (category === "language") {
        return "The documents state different levels for the same language.";
      }
      return "The documents disagree on this fact and no document makes clear which is more recent.";
    }
    return "The engine is not sure these facts can be compared. It needs your judgement.";
  }

  function renderAttentionCard(item, view) {
    const decision = item.decision;
    const category = item.keep[0] || item.others[0];
    const card = el("article", {
      className: `attention-card attention-card-${decision ? decision.outcome : "undecided"}`,
    });

    const head = el("div", { className: "attention-head" });
    const tag =
      decision && decision.outcome === "recommend"
        ? "Recommendation · not approved"
        : decision
          ? "Needs your judgement"
          : "Conflict detected";
    head.append(
      el("span", {
        className: `attention-tag${
          decision && decision.outcome === "recommend"
            ? " attention-tag-rec"
            : " attention-tag-warn"
        }`,
        text: tag,
      }),
    );
    head.append(
      el("h4", {
        text: category
          ? `${displaySubject(category.subject_label)} · ${categoryLabel(category.category, true)}`
          : "Unidentified fact",
      }),
    );
    card.append(head);
    card.append(el("p", { className: "attention-why", text: detectedText(item) }));

    const compare = el("div", { className: "compare" });
    if (item.keep.length) {
      compare.append(
        compareColumn("Recommended for review · not approved", item.keep, "keep", view),
      );
      if (item.others.length) {
        compare.append(
          compareColumn(
            plural(item.others.length, "Retained alternative", "Retained alternatives"),
            item.others,
            "other",
            view,
          ),
        );
      }
    } else {
      item.others.forEach((claim, index) => {
        compare.append(
          compareColumn(`Retained claim ${String.fromCharCode(65 + index)}`, [claim], "other", view),
        );
      });
    }
    card.append(compare);

    const difference = differenceText(item);
    if (difference) {
      card.append(el("p", { className: "attention-diff", text: difference }));
    }

    const recommendation = el("div", { className: "attention-engine" });
    if (decision && decision.outcome === "recommend" && item.keep.length) {
      recommendation.append(
        el("p", {
          className: "attention-rec-title",
          text: `Recommendation only: keep “${claimValue(item.keep[0])}”. It is not approved, and ${
            item.others.length === 1
              ? "the other claim remains"
              : "the other claims remain"
          } fully retained and visible.`,
        }),
      );
    } else if (decision && decision.outcome === "unresolved") {
      recommendation.append(
        el("p", {
          className: "attention-rec-title",
          text: `No preference: the engine does not choose. ${plural(
            item.others.length,
            "candidate claim remains",
            "candidate claims remain",
          )} retained for your judgement.`,
        }),
      );
    } else if (decision) {
      recommendation.append(
        el("p", {
          className: "attention-rec-title",
          text: `Engine outcome: ${decision.outcome}. No claim is approved.`,
        }),
      );
    } else {
      recommendation.append(
        el("p", {
          className: "attention-rec-title",
          text: "The engine proposed no decision for this pair. Both claims remain for your judgement.",
        }),
      );
    }
    if (decision) {
      recommendation.append(
        el("p", {
          className: "attention-rec-why",
          text: `Engine text: “${decision.explanation}”`,
        }),
      );
    }
    card.append(recommendation);

    const go = el("button", {
      className: "button button-secondary button-compact",
      attrs: { type: "button" },
      text: "Go to Candidate Profile",
    });
    if (typeof go.addEventListener === "function") {
      go.addEventListener("click", () => switchView(VIEW.PROFILE));
    }
    card.append(el("div", { className: "proposal-actions", children: [go] }));

    return card;
  }

  function attributeDisplayValue(attribute) {
    const value = attribute.value;
    if (value === undefined || value === null || value === "") return "—";
    if (attribute.name === "proficiency" || attribute.name === "level") {
      return String(value).toUpperCase();
    }
    if (attribute.name === "duration_exact") {
      if (value === "exact") return "Exact";
      if (value === "approximate") return "Approximate";
      return String(value);
    }
    return typeof value === "string" ? value : JSON.stringify(value);
  }

  function canonicalAttributeList(attributes) {
    const list = el("dl", { className: "attribute-list" });
    for (const attribute of attributes) {
      list.append(el("dt", { text: attributeLabel(attribute.name) }));
      list.append(el("dd", { text: attributeDisplayValue(attribute) }));
    }
    return list;
  }

  function consolidationEvidenceKey(consolidated) {
    return (consolidated.evidence || [])
      .map((entry) => [
        entry.document_id,
        entry.segment_index,
        entry.start,
        entry.end,
        entry.quote,
      ].join("|"))
      .sort()
      .join("||");
  }

  function consolidationRenderGroups(consolidated) {
    const groups = [];
    const partner = new Map();
    for (const record of consolidated) {
      if (record.category !== "degree" && record.category !== "education") {
        groups.push([record]);
        continue;
      }
      const key = `${consolidationEvidenceKey(record)}|${JSON.stringify(record.attributes)}`;
      const existing = partner.get(key);
      if (existing) {
        existing.push(record);
        partner.delete(key);
      } else {
        const group = [record];
        groups.push(group);
        partner.set(key, group);
      }
    }
    return groups;
  }

  function qualifierSummary(qualifiers) {
    const explicit = qualifiers.includes("explicit_claim");
    const keyword = qualifiers.includes("keyword_mention");
    if (explicit && keyword) return "Includes explicit claims and keyword mentions.";
    if (keyword) return "Keyword mentions only; they are not explicit claims.";
    if (explicit) return "Explicit claims stated by the documents.";
    return "The source support is not stated.";
  }

  function renderConsolidatedCard(records, view) {
    const first = records[0];
    const companion = records.length > 1;
    const claimIds = [...new Set(records.flatMap((record) => record.claim_ids || []))];
    const documents = new Set();
    const evidence = [];
    const seenEvidence = new Set();
    for (const record of records) {
      for (const entry of record.evidence || []) {
        documents.add(entry.document_id);
        const key = [
          entry.document_id,
          entry.segment_index,
          entry.start,
          entry.end,
          entry.quote,
        ].join("|");
        if (!seenEvidence.has(key)) {
          seenEvidence.add(key);
          evidence.push(entry);
        }
      }
    }
    const qualifiers = [
      ...new Set(
        records.flatMap((record) => [
          ...(record.qualifiers || []),
          ...(record.claim_ids || [])
            .map((id) => view.claimById.get(id)?.qualifier)
            .filter(Boolean),
        ]),
      ),
    ];
    const categories = [
      ...new Set(records.map((record) => record.category)),
    ];

    const card = el("article", {
      className: `consolidated-card${companion ? " consolidated-companion" : ""}`,
    });
    const head = el("div", { className: "consolidated-head" });
    head.append(el("span", { className: "tag tag-ok", text: "Consolidated" }));
    head.append(
      el("h4", {
        text: `${displaySubject(first.subject_label)} · ${categories
          .map((category) => categoryLabel(category, true))
          .join(" + ")}`,
      }),
    );
    head.append(
      el("span", {
        className: "consolidated-count",
        text: `${plural(documents.size, "document")} · ${plural(
          claimIds.length,
          "claim",
          "claims",
        )}${companion ? ` · ${records.length} canonical records` : ""}`,
      }),
    );
    card.append(head);
    card.append(
      el("p", {
        className: "consolidated-desc",
        text: companion
          ? `The engine joined ${plural(
              claimIds.length,
              "claim",
              "claims",
            )} into ${records.length} canonical records for the same qualification. They are shown together to avoid repetition; the records themselves are not merged. Joining is not proof or approval.`
          : `The engine joined ${plural(
              claimIds.length,
              "claim",
              "claims",
            )} from ${plural(documents.size, "document")} because they state the same thing. Joining is not proof or approval.`,
      }),
    );
    card.append(canonicalAttributeList(first.attributes));
    card.append(
      el("p", {
        className: "consolidated-qualifiers",
        text: qualifierSummary(qualifiers),
      }),
    );
    if (qualifiers.includes("keyword_mention")) {
      card.append(
        el("p", {
          className: "field-note field-note-tight",
          text: "A keyword mention is not promoted to an explicit claim.",
        }),
      );
    }

    const details = el("details", { className: "evidence-details" });
    details.append(
      el("summary", {
        text: companion
          ? `See ${plural(evidence.length, "original quote", "original quotes")} once for both records`
          : `See ${plural(evidence.length, "original quote", "original quotes")}`,
      }),
    );
    if (companion) {
      const recordList = el("ul", { className: "conflict-quotes" });
      for (const record of records) {
        recordList.append(
          el("li", {
            children: [
              el("span", {
                className: "conflict-quote-ref",
                text: `${categoryLabel(record.category, true)} · ${plural(
                  record.claim_ids.length,
                  "claim",
                  "claims",
                )} · ${record.claim_ids.join(", ")}`,
              }),
            ],
          }),
        );
      }
      details.append(recordList);
    }
    const quotes = el("ul", { className: "conflict-quotes" });
    for (const entry of evidence) {
      const document = view.documentById.get(entry.document_id);
      quotes.append(
        el("li", {
          children: [
            el("span", {
              className: "conflict-quote-ref",
              text: `${document?.filename || entry.document_id} · ${locatorLabel(entry.locator)}`,
            }),
            el("blockquote", {
              className: "evidence-quote",
              text: entry.quote ? `“${entry.quote}”` : "(no quote)",
            }),
          ],
        }),
      );
    }
    details.append(quotes);
    card.append(details);
    return card;
  }

  function renderReconciliationSources(view) {
    const list = $("reconciliation-sources");
    clearNode(list);
    for (const document of view.report.documents) {
      const claims = view.report.claims.filter((claim) =>
        claim.evidence.some((entry) => entry.document_id === document.document_id),
      ).length;
      list.append(
        el("li", {
          className: "source-item",
          children: [
            el("span", { className: "source-name", text: document.filename }),
            el("span", {
              className: "source-meta",
              text: `${fileKindLabel(document.format)} · ${documentMeta(document.status).label}`,
            }),
            el("span", {
              className: "source-cites",
              text: plural(claims, "claim", "claims"),
            }),
          ],
        }),
      );
    }
  }

  function reconciliationFindings(view) {
    return view.report.claims.filter(
      (claim) => !view.coveredClaimIds.has(claim.claim_id),
    );
  }

  function degreeEvidenceKey(claim) {
    if (claim.category !== "degree" && claim.category !== "education") return null;
    const entry = claim.evidence && claim.evidence[0];
    if (!entry) return null;
    return [
      entry.document_id,
      entry.segment_index,
      entry.start,
      entry.end,
      entry.quote,
    ].join("|");
  }

  function remainderEntries(claims) {
    const groups = new Map();
    const entries = [];
    for (const claim of claims) {
      const key = degreeEvidenceKey(claim);
      if (key) {
        const existing = groups.get(key);
        if (existing) {
          // Degree and education are canonical claims from the same source
          // line. They are grouped for display only; neither is removed or
          // merged in the report.
          existing.claims.push(claim);
          continue;
        }
        const entry = { kind: "qualification", claims: [claim] };
        groups.set(key, entry);
        entries.push(entry);
        continue;
      }
      entries.push({ kind: "claim", claims: [claim] });
    }
    return entries;
  }

  function renderTailor() {
    const body = state.tailor;
    const profile = state.profileView;
    const proposals = profile?.proposals || [];
    const approved = proposals.filter((p) => p.status === "approved").length;
    const pending = proposals.filter((p) => p.status === "proposed").length;
    const conflicts = state.profileView?.conflicts?.length || 0;
    const ready = approved > 0 && pending === 0 && conflicts === 0;
    const approvedProfile = state.tailor.approvedProfile;
    const hasApprovedProfile = Boolean(approvedProfile && (approvedProfile.facts || []).length);
    const jobText = (state.tailor.jobPosting.text || "").trim();
    const canGenerate = hasApprovedProfile && jobText.length >= 40 && !state.tailor.generating;

    // Readiness
    const readiness = $("tailor-readiness-body");
    clearNode(readiness);
    readiness.append(
      el("div", {
        className: "tailor-readiness-grid",
        children: [
          el("article", { className: "tailor-readiness-card", children: [
            el("strong", { text: String(approved) }),
            el("span", { text: "approved facts available" }),
          ]}),
          el("article", { className: "tailor-readiness-card", children: [
            el("strong", { text: String(pending) }),
            el("span", { text: "facts not yet approved" }),
          ]}),
          el("article", { className: "tailor-readiness-card", children: [
            el("strong", { text: String(conflicts) }),
            el("span", { text: "outstanding conflicts" }),
          ]}),
          el("article", { className: "tailor-readiness-card", children: [
            el("strong", { text: ready ? "Ready" : "Not ready" }),
            el("span", { text: ready ? "Profile can be tailored" : "Review the profile first" }),
          ]}),
        ],
      }),
    );
    if (state.profileState !== "ready") {
      readiness.append(el("p", { className: "field-note", text: "Build the profile first (step 2) to see readiness." }));
    } else if (!ready) {
      readiness.append(el("p", { className: "field-note", text: "Open the Profile tab to approve facts or resolve conflicts before tailoring." }));
    }

    // Job posting form status
    const text = body.jobPosting.text.trim();
    body.jobStatus = text.length < 40
      ? "Paste at least 40 characters of the job posting."
      : text.length > 20000
        ? "The posting is too long."
        : "Posting ready.";
    setText("tailor-job-status", body.jobStatus);

    const approvedStatus = $("tailor-approved-status");
    if (approvedStatus) {
      approvedStatus.textContent = hasApprovedProfile
        ? `Approved profile loaded (${(approvedProfile.facts || []).length} facts).`
        : "No approved profile loaded. Export one from the Profile tab.";
    }

    const genBtn = $("tailor-generate");
    if (genBtn) {
      genBtn.disabled = !canGenerate;
      genBtn.textContent = state.tailor.generating ? "Generating..." : "Generate tailored CV";
    }

    // Editor
    const editor = $("tailor-editor-body");
    clearNode(editor);
    if (!body.draft) {
      const startBtn = el("button", { className: "button button-secondary button-inline", type: "button", text: "Start an empty draft" });
      startBtn.addEventListener("click", () => startTailorDraft());
      editor.append(el("div", { className: "section-empty", children: [
        el("p", { text: "No CV draft yet." }),
        el("p", { className: "field-note", text: "Approve and save your profile, paste a job posting, then generate an evidence-grounded draft." }),

      ]}));
    } else {
      const draft = body.draft;
      setText("tailor-draft-status", `${draft.sections.length} sections · ${draft.sections.reduce((n,s)=>n+s.items.length,0)} items`);
      const contact = el("div", { className: "tailor-contact" });
      contact.append(el("h4", { text: "Contact" }));
      for (const [key, label] of [["full_name","Full name"],["email","Email"],["phone","Phone"],["location","Location"]]) {
        const input = el("input", { className: "input", type: "text", attrs: { "data-tailor-contact": key, value: draft.candidate[key] || "" } });
        input.addEventListener("input", (e) => { draft.candidate[key] = e.target.value; renderTailorPreview(); });
        contact.append(el("label", { className: "field-label", text: label }), input);
      }
      const linksInput = el("input", { className: "input", type: "text", attrs: { "data-tailor-links": "1", value: (draft.candidate.links || []).join(", ") } });
      linksInput.addEventListener("input", (e) => {
        draft.candidate.links = e.target.value.split(",").map(s=>s.trim()).filter(Boolean);
        renderTailorPreview();
      });
      contact.append(el("label", { className: "field-label", text: "Links (comma separated)" }), linksInput);
      editor.append(contact);

      draft.sections.forEach((section, sIndex) => {
        const card = el("article", { className: "tailor-section" });
        const head = el("div", { className: "tailor-section-head" });
        const titleInput = el("input", { className: "input", type: "text", attrs: { value: section.title } });
        titleInput.addEventListener("input", (e) => { section.title = e.target.value; renderTailorPreview(); });
        head.append(titleInput);
        const removeBtn = el("button", { className: "button button-quiet button-inline", type: "button", text: "Remove section" });
        removeBtn.addEventListener("click", () => { draft.sections.splice(sIndex, 1); renderTailor(); });
        head.append(removeBtn);
        if (sIndex > 0) {
          const up = el("button", { className: "button button-quiet button-inline", type: "button", text: "↑" });
          up.addEventListener("click", () => { const a=draft.sections; [a[sIndex-1],a[sIndex]]=[a[sIndex],a[sIndex-1]]; renderTailor(); });
          head.append(up);
        }
        if (sIndex < draft.sections.length - 1) {
          const down = el("button", { className: "button button-quiet button-inline", type: "button", text: "↓" });
          down.addEventListener("click", () => { const a=draft.sections; [a[sIndex],a[sIndex+1]]=[a[sIndex+1],a[sIndex]]; renderTailor(); });
          head.append(down);
        }
        card.append(head);

        section.items.forEach((item, iIndex) => {
          const row = el("div", { className: "tailor-item" });
          const textarea = el("textarea", { className: "textarea", rows: 2, attrs: { "data-tailor-item": item.item_id } });
          textarea.value = item.text;
          textarea.addEventListener("input", (e) => { item.text = e.target.value; item.review_status = "needs_review"; renderTailorPreview(); });
          textarea.addEventListener("change", () => { editTailorItem(item.item_id, item.text); });
          row.append(textarea);
          const meta = el("div", { className: "tailor-item-meta" });
          meta.append(el("span", { className: `badge badge-${item.review_status === "approved" ? "ok" : "warn"}`, text: item.review_status === "approved" ? "Approved" : "Needs review" }));
          if (item.approved_fact_ids && item.approved_fact_ids.length) {
            meta.append(el("span", { className: "field-note", text: draft.review?.approvals?.[item.item_id]?.mode === "candidate_attested" ? "Candidate-attested wording · not documentary evidence" : `Source facts: ${item.approved_fact_ids.join(", ")}` }));
          }
          const approve = el("button", { className: "button button-quiet button-inline", type: "button", text: item.review_status === "approved" ? "Mark for review" : "Approve wording" });
          approve.addEventListener("click", () => {
            if (item.review_status === "approved") {
              // Editing invalidates approval; only the backend can revoke by edit.
              item.review_status = "needs_review";
              renderTailor();
            } else {
              approveTailorItem(item.item_id);
            }
          });
          meta.append(approve);
          const remove = el("button", { className: "button button-quiet button-inline", type: "button", text: "Remove" });
          remove.addEventListener("click", () => { section.items.splice(iIndex, 1); renderTailor(); });
          meta.append(remove);
          if (iIndex > 0) {
            const up = el("button", { className: "button button-quiet button-inline", type: "button", text: "↑" });
            up.addEventListener("click", () => { const a=section.items; [a[iIndex-1],a[iIndex]]=[a[iIndex],a[iIndex-1]]; renderTailor(); });
            meta.append(up);
          }
          if (iIndex < section.items.length - 1) {
            const down = el("button", { className: "button button-quiet button-inline", type: "button", text: "↓" });
            down.addEventListener("click", () => { const a=section.items; [a[iIndex],a[iIndex+1]]=[a[iIndex+1],a[iIndex]]; renderTailor(); });
            meta.append(down);
          }
          row.append(meta);
          card.append(row);
        });

        const addBtn = el("button", { className: "button button-secondary button-inline", type: "button", text: "Add item" });
        addBtn.addEventListener("click", () => {
          section.items.push({ item_id: `item-${Date.now()}-${section.items.length}`, text: "", approved_fact_ids: [], review_status: "needs_review" });
          renderTailor();
        });
        card.append(addBtn);
        editor.append(card);
      });

      const addSection = el("button", { className: "button button-secondary button-inline", type: "button", text: "Add section" });
      addSection.addEventListener("click", () => {
        const kind = "custom";
        draft.sections.push({ section_id: `section-${Date.now()}`, kind, title: "New section", items: [] });
        renderTailor();
      });
      editor.append(addSection);
    }

    renderTailorPreview();
    renderTailorExport();
  }

  function startTailorDraft() {
    const cvt = global.JobLensTailor;
    const job = state.tailor.jobPosting;
    const draft = cvt.emptyDraft(job);
    // Seed a familiar professional structure mirroring the reference CV.
    draft.sections = [
      { section_id: "summary", kind: "summary", title: "Summary", items: [] },
      { section_id: "experience", kind: "experience", title: "Experience", items: [] },
      { section_id: "projects", kind: "projects", title: "Projects", items: [] },
      { section_id: "education", kind: "education", title: "Education", items: [] },
      { section_id: "skills", kind: "skills", title: "Technical skills", items: [] },
    ];
    try { cvt.validateDraft(draft); } catch (e) { state.tailor.error = e.message; }
    state.tailor.draft = draft;
    state.tailor.error = null;
    renderTailor();
  }

  function submitTailorJob() {
    const title = $("tailor-job-title").value.trim();
    const company = $("tailor-job-company").value.trim();
    const location = $("tailor-job-location").value.trim();
    const text = $("tailor-job-text").value.trim();
    if (text.length < 40) {
      state.tailor.jobStatus = "Paste at least 40 characters of the job posting.";
      renderTailor();
      return;
    }
    if (text.length > 20000) {
      state.tailor.jobStatus = "The posting is too long.";
      renderTailor();
      return;
    }
    state.tailor.jobPosting = { title, company, location, text };
    state.tailor.jobStatus = "Parsing job posting...";
    state.tailor.parsedJob = null;
    renderTailor();
    (async () => {
      try {
        const parsed = await new cv.CvApiAdapter({ baseUrl: apiBase() }).parseJob(state.tailor.jobPosting);
        state.tailor.parsedJob = parsed;
        state.tailor.jobStatus = "Posting parsed. Ready to generate.";
      } catch (error) {
        state.tailor.parsedJob = null;
        state.tailor.jobStatus = error?.message || "Parsing failed.";
      }
      renderTailor();
    })();
  }

  async function generateTailorDraft() {
    const approved = state.tailor.approvedProfile;
    const jobPosting = state.tailor.jobPosting;
    if (!approved || !jobPosting.text) return;
    state.tailor.generating = true;
    state.tailor.error = null;
    renderTailor();
    try {
      const result = await new cv.CvApiAdapter({ baseUrl: apiBase() }).generateDraft(
        approved,
        { title: jobPosting.title, company: jobPosting.company, location: jobPosting.location, text: jobPosting.text, raw_text: jobPosting.text },
        approved.source || (state.job ? cvp.buildProfileRequest(state.job) : null),
      );
      state.tailor.draft = result.draft;
      state.tailor.parsedJob = result.job || state.tailor.parsedJob;
    } catch (error) {
      state.tailor.error = error?.message || "Generation failed.";
    } finally {
      state.tailor.generating = false;
      renderTailor();
    }
  }

  async function importTailorApprovedProfile(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const payload = JSON.parse(text);
      if (!window.confirm("Revalidate and confirm the approved facts in this private profile?")) return;
      const job = state.job;
      const result = await new cv.CvApiAdapter({ baseUrl: apiBase() }).validateApprovedProfile(job, payload);
      state.tailor.approvedProfile = result.approved_profile || payload;
      state.tailor.jobStatus = "Approved profile imported and validated.";
    } catch (error) {
      state.tailor.error = error?.message || "Import failed.";
    } finally {
      event.target.value = "";
      renderTailor();
    }
  }

  async function editTailorItem(itemId, text) {
    const draft = state.tailor.draft;
    if (!draft) return;
    try {
      const result = await new cv.CvApiAdapter({ baseUrl: apiBase() }).editDraftItem(draft, itemId, text);
      state.tailor.draft = result.draft;
    } catch (error) {
      state.tailor.error = error?.message || "Edit failed.";
    }
    renderTailor();
  }

  async function approveTailorItem(itemId) {
    const draft = state.tailor.draft;
    if (!draft) return;
    if (!window.confirm("Approve this exact wording? If you changed or added facts, you explicitly attest that they are accurate. Candidate-attested wording is not verified documentary evidence.")) return;
    try {
      const result = await new cv.CvApiAdapter({ baseUrl: apiBase() }).approveDraftItem(draft, itemId);
      state.tailor.draft = result.draft;
    } catch (error) {
      state.tailor.error = error?.message || "Approval failed.";
    }
    renderTailor();
  }

  async function exportTailor(kind) {
    const draft = state.tailor.draft;
    const approved = state.tailor.approvedProfile;
    if (!draft) return;
    if (!window.confirm("Confirm that the displayed name and contact details are correct and that you have reviewed this CV for export.")) return;
    try {
      const adapter = new cv.CvApiAdapter({ baseUrl: apiBase() });
      const blob = kind === "pdf" ? await adapter.exportPdf(draft, approved) : await adapter.exportDocx(draft, approved);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = kind === "pdf" ? "tailored-cv.pdf" : "tailored-cv.docx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      state.tailor.error = error?.message || "Export failed.";
      renderTailor();
    }
  }

  function renderTailorPreview() {
    const body = $("tailor-preview-body");
    clearNode(body);
    const draft = state.tailor.draft;
    if (!draft) {
      body.append(el("div", { className: "section-empty", text: "No draft to preview." }));
      return;
    }
    const preview = el("article", { className: "tailor-cv-preview" });
    preview.append(el("h3", { className: "tailor-cv-name", text: draft.candidate.full_name || "Your name" }));
    if (draft.target_job.title || draft.target_job.company) {
      preview.append(el("p", { className: "tailor-cv-headline", text: [draft.target_job.title, draft.target_job.company].filter(Boolean).join(" · ") }));
    }
    const contactLine = [draft.candidate.location, draft.candidate.email, draft.candidate.phone, ...(draft.candidate.links || [])].filter(Boolean).join(" · ");
    if (contactLine) preview.append(el("p", { className: "tailor-cv-contact", text: contactLine }));
    for (const section of draft.sections) {
      if (!section.items.length && !section.title) continue;
      preview.append(el("h4", { className: "tailor-cv-section", text: section.title }));
      const list = el("ul", { className: "tailor-cv-list" });
      for (const item of section.items) {
        if (!item.text.trim()) continue;
        const li = el("li", { text: item.text });
        if (item.review_status !== "approved") li.classList.add("tailor-cv-unreviewed");
        list.append(li);
      }
      if (list.children.length) preview.append(list);
    }
    body.append(preview);
  }

  function renderTailorExport() {
    const draft = state.tailor.draft;
    const items = draft ? draft.sections.flatMap((s) => s.items) : [];
    const eligible = Boolean(draft && items.length && items.every((i) => i.review_status === "approved"));
    $("tailor-export-pdf").disabled = !eligible;
    $("tailor-export-docx").disabled = !eligible;
  }

  function renderReconciliationFindings(claims, view) {
    const list = $("reconciliation-findings");
    clearNode(list);
    setText(
      "reconciliation-findings-count",
      plural(claims.length, "claim", "claims"),
    );
    $("reconciliation-findings-empty").hidden = claims.length > 0;
    for (const entry of remainderEntries(claims)) {
      const primary = entry.claims[0];
      const qualification = entry.kind === "qualification";
      const meta = qualification
        ? `${entry.claims
            .map((claim) => categoryLabel(claim.category, true))
            .join(" + ")} · ${plural(
            entry.claims.length,
            "canonical claim",
            "canonical claims",
          )} · ${claimSource(primary, view)}`
        : `${categoryLabel(primary.category, true)} · ${claimSource(primary, view)}`;
      const children = [
        el("span", { className: "finding-value", text: claimValue(primary) }),
        el("span", { className: "finding-meta", text: meta }),
        el("span", {
          className: `badge badge-${
            primary.qualifier === "keyword_mention" ? "warn" : "ok"
          }`,
          text: claimSupportLabel(primary),
          attrs: { title: claimSupportDescription(primary) },
        }),
      ];
      if (qualification) {
        children.push(
          el("span", {
            className: "finding-note",
            text: "Both records come from the same source line and remain separate canonical claims; they are grouped here only to avoid repetition.",
          }),
        );
      }
      const details = el("details", { className: "finding-quotes" });
      details.append(el("summary", { text: "Show exact quote and claim record" }));
      const quotes = el("ul", { className: "conflict-quotes" });
      for (const claim of entry.claims) {
        quotes.append(
          el("li", {
            children: [
              el("span", {
                className: "conflict-quote-ref",
                text: `${categoryLabel(claim.category, true)} · ${claim.claim_id} · ${claimSource(claim, view)}`,
              }),
              el("blockquote", {
                className: "evidence-quote",
                text: claimQuote(claim),
              }),
              el("span", {
                className: "badge badge-neutral",
                text: claimSupportLabel(claim),
              }),
            ],
          }),
        );
      }
      details.append(quotes);
      children.push(details);
      list.append(el("li", { className: "finding-item", children }));
    }
  }

  function renderReconciliationTechnical(model, view) {
    const container = $("reconciliation-groups");
    clearNode(container);

    container.append(
      el("p", {
        className: "tech-note",
        text: "Technical note: no approval, resolution or claim-to-proposal mapping is transferred between this reconciliation report and the Candidate Profile. Claim IDs are not proposal IDs.",
      }),
    );
    for (const warning of model.report.warnings) {
      container.append(
        el("p", { className: "tech-note", text: `Engine warning: ${warning}` }),
      );
    }

    for (const group of model.groups) {
      const section = el("section", { className: "reconciliation-entity" });
      section.append(
        el("h3", {
          text: `${categoryLabel(group.category)} · ${group.label}`,
        }),
      );
      section.append(
        el("p", {
          className: "tech-note",
          text: `Entity ${group.category}:${group.subject} · ${plural(
            group.claims.length,
            "claim",
            "claims",
          )} · ${plural(group.relationships.length, "relationship", "relationships")}`,
        }),
      );
      if (group.blocking) {
        section.append(
          el("p", {
            className: "tech-note",
            text: "Needs review: blocking evidence or a citation mismatch exists. This screen offers no approval.",
          }),
        );
      }

      for (const claim of group.claims) {
        const card = el("article", { className: "reconciliation-claim" });
        card.append(el("h4", { text: `${claim.subject_label} · ${claim.claim_id}` }));
        card.append(
          el("p", {
            className: "tech-note",
            text: `Support: ${claimSupportLabel(claim)} · ${
              model.verified.get(claim.claim_id)
                ? "the citation matches the extracted text exactly"
                : "citation mismatch against the extracted text"
            }`,
          }),
        );
        card.append(renderCanonicalAttributes(claim.attributes));
        card.append(renderCanonicalEvidence(claim.evidence));
        section.append(card);
      }

      for (const relation of group.relationships) {
        section.append(
          el("h4", {
            text: `${relation.relation}${relation.semantic ? " · semantic suggestion" : ""}`,
          }),
        );
        section.append(
          el("p", {
            className: "tech-note",
            text: `${relation.reason} · comparator: ${relation.basis} · attributes: ${relation.attributes.join(", ")}`,
          }),
        );
        section.append(
          el("p", {
            className: "tech-note",
            text: `${relation.left_claim_id} ↔ ${relation.right_claim_id} · relationship ${relation.relationship_id}`,
          }),
        );
        if (
          relation.semantic ||
          relation.relation === "uncertain" ||
          !cvz.RELATIONS.includes(relation.relation)
        ) {
          section.append(
            el("strong", {
              text: "Uncertain or semantic relationship: needs human review.",
            }),
          );
        }
        section.append(renderCanonicalEvidence(relation.evidence));
      }

      for (const decision of group.decisions) {
        section.append(el("h4", { text: `Engine outcome: ${decision.outcome}` }));
        section.append(el("p", { className: "tech-note", text: decision.explanation }));
        section.append(
          el("p", {
            className: "tech-note",
            text: `Kept: ${decision.keep_claim_ids.join(", ") || "none"} · merged: ${
              decision.merge_claim_ids.join(", ") || "none"
            } · retained alternatives: ${
              (decision.alternative_claim_ids || []).join(", ") || "none"
            } · requires confirmation: ${
              decision.requires_user_confirmation ? "yes" : "no"
            } · approval state: ${
              decision.approval_state || "not_approved"
            } · relationships: ${decision.relationship_ids.join(", ") || "none"}. No fact is approved.`,
          }),
        );
      }

      for (const consolidated of group.consolidated) {
        section.append(
          el("h4", {
            text: "Engine consolidation — keeps every source, not an approval",
          }),
        );
        section.append(
          el("p", {
            className: "tech-note",
            text: `Support: ${
              (consolidated.qualifiers || []).map(evidenceSupportLabel).join(", ") ||
              "not stated"
            } · approval state: ${consolidated.approval_state || "not_approved"}`,
          }),
        );
        section.append(renderCanonicalAttributes(consolidated.attributes));
        section.append(renderCanonicalEvidence(consolidated.evidence));
      }

      container.append(section);
    }
  }

  function renderReconciliation() {
    const panel = $("reconciliation-view");
    if (!panel) return;
    panel.hidden = state.view !== VIEW.RECONCILIATION;
    if (reconciliationJob && reconciliationJob !== state.job) {
      reconciliationRequest += 1;
      reconciliationJob = null;
      reconciliationLoading = false;
      reconciliationError = "";
      state.reconciliation = null;
    }

    const model = state.reconciliation;
    const view = model ? reconciliationViewModel(model) : null;
    $("reconciliation-results").hidden = !view;

    $("reconciliation-build").disabled = reconciliationLoading || !state.job || !cvz;
    $("reconciliation-preview").disabled = true;
    $("reconciliation-preview-multi").disabled = true;
    $("reconciliation-clear").hidden = !model;

    setText(
      "reconciliation-title",
      "Compare what your documents say",
    );

    if (reconciliationLoading) {
      setText(
        "reconciliation-subtitle",
        "Comparing the documents with the local Python engine…",
      );
    } else if (view) {
      setText(
        "reconciliation-subtitle",
        `${plural(view.counts.documents, "document")} · ${plural(
          view.counts.claims,
          "claim",
          "claims",
        )} · ${plural(
          view.counts.consolidations,
          "consolidation",
          "consolidations",
        )}`,
      );
    } else if (reconciliationError) {
      setText("reconciliation-subtitle", "Could not compare the documents.");
    } else if (!state.job) {
      setText(
        "reconciliation-subtitle",
        "Analyse your documents first so they can be compared.",
      );
    } else {
      setText(
        "reconciliation-subtitle",
        "The documents are ready to be compared.",
      );
    }

    setText(
      "reconciliation-status",
      reconciliationError
        ? `Could not compare: ${reconciliationError}`
        : "",
    );

    const counts = view ? view.counts : {
      documents: 0,
      claims: 0,
      consolidations: 0,
      conflicts: 0,
      pending: 0,
      unresolved: 0,
    };
    for (const name of [
      "documents",
      "claims",
      "consolidations",
      "conflicts",
      "pending",
      "unresolved",
    ]) {
      setText(`reconciliation-count-${name}`, String(counts[name]));
    }

    state.reconciliationAttention = view ? view.attention.length : 0;

    const overview = $("reconciliation-overview");
    const warnings = $("reconciliation-warnings");
    const attention = $("reconciliation-attention");
    const consolidated = $("reconciliation-consolidated");
    clearNode(overview);
    clearNode(warnings);
    clearNode(attention);
    clearNode(consolidated);
    overview.hidden = true;
    warnings.hidden = true;
    $("reconciliation-empty").hidden = true;

    if (!view) {
      clearNode($("reconciliation-sources"));
      $("reconciliation-attention-empty").hidden = false;
      $("reconciliation-consolidated-empty").hidden = false;
      setText("reconciliation-attention-count", "");
      setText("reconciliation-consolidated-count", "");
      clearNode($("reconciliation-findings"));
      setText("reconciliation-findings-count", "");
      $("reconciliation-findings-empty").hidden = false;
      clearNode($("reconciliation-groups"));
      renderNextStep();
      return;
    }

    const documentsText = plural(view.counts.documents, "document");
    const claimsText = plural(view.counts.claims, "claim", "claims");
    const consolidations = view.counts.consolidations;
    const attentionCount = view.attention.length;
    const parts = [`Compared ${documentsText} and ${claimsText}.`];
    if (consolidations) {
      parts.push(
        plural(
          consolidations,
          "claim group was joined from matching statements",
          "claim groups were joined from matching statements",
        ) + ".",
      );
    } else {
      parts.push("No claim group was joined as a duplicate statement.");
    }
    if (attentionCount) {
      parts.push(
        `${plural(
          attentionCount,
          "item needs",
          "items need",
        )} your attention.`,
      );
    } else {
      parts.push("Nothing needs your attention.");
    }
    overview.hidden = false;
    overview.textContent = parts.join(" ");

    warnings.hidden = view.report.warnings.length === 0;
    if (view.report.warnings.length) {
      warnings.append(
        el("p", {
          className: "warning-summary",
          text: `The engine left ${plural(
            view.report.warnings.length,
            "technical warning",
            "technical warnings",
          )}. See “Technical details” at the end.`,
        }),
      );
    }

    renderReconciliationSources(view);

    setText(
      "reconciliation-attention-count",
      plural(view.attention.length, "item", "items"),
    );
    $("reconciliation-attention-empty").hidden = view.attention.length > 0;
    for (const item of view.attention) {
      attention.append(renderAttentionCard(item, view));
    }

    setText(
      "reconciliation-consolidated-count",
      plural(view.report.consolidated.length, "claim group", "claim groups"),
    );
    $("reconciliation-consolidated-empty").hidden =
      view.report.consolidated.length > 0;
    for (const group of consolidationRenderGroups(view.report.consolidated)) {
      consolidated.append(renderConsolidatedCard(group, view));
    }

    renderReconciliationFindings(reconciliationFindings(view), view);
    renderReconciliationTechnical(model, view);
    renderNextStep();
  }

  function fileRejectionMessage(item) {
    const name = item.name || "File";
    if (item.code === "unsupported_type") {
      return `“${name}” is not a PDF or DOCX.`;
    }
    if (item.code === "empty_file") {
      return `“${name}” is empty. Choose a file with content.`;
    }
    if (item.code === "too_many") {
      return `“${name}” was not added: only five documents are allowed.`;
    }
    if (item.code === "missing_name") {
      return "A file has no usable name.";
    }
    return item.message;
  }

  function addFiles(fileList) {
    if (isBusy()) return;

    const result = cv.validateFiles(fileList, {
      existingCount: state.files.length,
    });
    state.alertMessages = result.rejected.map(fileRejectionMessage);

    if (result.accepted.length) {
      const hadReport =
        Boolean(state.job) ||
        state.phase === PHASE.REPORT ||
        state.phase === PHASE.ERROR;

      for (const file of result.accepted) {
        state.files.push({
          uid: `file-${state.fileSequence}`,
          file,
          name: file.name,
          size: file.size,
          kind: cv.detectDocumentKind(file),
        });
        state.fileSequence += 1;
      }

      if (hadReport) {
        state.notice =
          "The documents changed. Earlier results were cleared.";
        state.revision += 1;
        resetResults();
      } else {
        state.phase = PHASE.READY;
        state.notice = "";
        state.error = null;
      }
    }

    renderAll();
  }

  function removeFile(uid) {
    if (isBusy()) return;
    const index = state.files.findIndex((entry) => entry.uid === uid);
    if (index < 0) return;

    const hadReport = Boolean(state.job) || state.phase === PHASE.REPORT;
    state.files.splice(index, 1);
    state.alertMessages = [];

    if (hadReport) {
      state.notice = "The documents changed. Earlier results were cleared.";
      state.revision += 1;
      resetResults();
    } else if (state.phase !== PHASE.IDLE) {
      state.phase = state.files.length ? PHASE.READY : PHASE.IDLE;
    }

    if (!state.files.length) {
      state.phase = PHASE.IDLE;
      state.notice = "";
    }

    renderAll();
  }

  function clearAll() {
    if (isBusy()) return;
    state.files = [];
    state.alertMessages = [];
    state.notice = "";
    state.revision += 1;
    resetResults();
    state.phase = PHASE.IDLE;
    renderAll();
    focusElement("file-input");
  }

  function resetResults() {
    state.job = null;
    state.selectedDocumentId = null;
    state.selectedSegmentId = null;
    state.error = null;
    state.lastAnnouncedJobId = null;
    state.profile = null;
    state.tailor = {
      jobPosting: { title: "", company: "", location: "", text: "" },
      draft: null,
      generating: false,
      error: null,
      jobStatus: "",
    };
    state.profileView = null;
    state.profileState = "idle";
    state.profileError = null;
    state.profileEditing = null;
    state.conflictForm = null;
    state.review = null;
    state.profileFilter = "all";
    reconciliationRequest += 1;
    reconciliationJob = null;
    reconciliationLoading = false;
    reconciliationError = "";
    state.reconciliation = null;
    state.reconciliationAttention = 0;
    state.phase = state.files.length ? PHASE.READY : PHASE.IDLE;
  }

  async function startExtraction() {
    if (isBusy()) return;
    if (!adapter) {
      state.phase = PHASE.ERROR;
      state.error = new cv.CvError(
        "The extraction adapter is not available in this browser.",
        { code: "adapter_unavailable" },
      );
      renderAll();
      focusElement("error-heading");
      return;
    }
    if (!state.files.length) {
      state.alertMessages = ["Choose at least one document before analysing."];
      renderAll();
      focusElement("file-input");
      return;
    }

    state.revision += 1;
    const revision = state.revision;
    state.abortController?.abort();
    const controller = new AbortController();
    state.abortController = controller;

    resetResults();
    state.phase = PHASE.UPLOADING;
    state.error = null;
    state.notice = "";
    state.alertMessages = [];
    state.lastAnnouncedJobId = null;

    renderAll();
    focusElement("loading-heading");

    try {
      const created = await adapter.createExtraction(
        state.files.map((entry) => entry.file),
        { signal: controller.signal },
      );
      if (revision !== state.revision) return;

      applyJob(created, true);

      if (!cv.isTerminalJobStatus(created.status)) {
        const finalJob = await adapter.waitForExtraction(created.id, {
          signal: controller.signal,
          onUpdate: (update) => {
            if (revision !== state.revision) return;
            const wasBusy = !state.job || !cv.isTerminalJobStatus(state.job.status);
            applyJob(update, wasBusy);
          },
        });

        if (revision !== state.revision) return;
        const wasBusy = !state.job || !cv.isTerminalJobStatus(state.job.status);
        applyJob(finalJob, wasBusy);
      }
    } catch (error) {
      if (revision !== state.revision) return;
      if (error?.name === "AbortError") return;

      state.phase = PHASE.ERROR;
      state.error = error;
      state.job = null;
      state.selectedDocumentId = null;
      state.selectedSegmentId = null;
      renderAll();
      focusElement("error-heading");
    } finally {
      if (revision === state.revision) {
        state.abortController = null;
        renderControls();
      }
    }
  }

  function applyJob(job, wasBusy) {
    state.job = job;
    state.phase = PHASE.REPORT;
    renderAll();

    if (
      wasBusy &&
      cv.isTerminalJobStatus(job.status) &&
      state.lastAnnouncedJobId !== job.id
    ) {
      state.lastAnnouncedJobId = job.id;
      focusElement("report-title");
    }
  }

  function cancelExtraction() {
    if (!isBusy()) return;

    const abandonedJobId = state.job?.id || "";
    state.revision += 1;
    state.abortController?.abort();
    state.abortController = null;
    state.job = null;
    state.selectedDocumentId = null;
    state.selectedSegmentId = null;
    state.error = null;
    state.lastAnnouncedJobId = null;
    state.phase = state.files.length ? PHASE.READY : PHASE.IDLE;
    state.notice = abandonedJobId
      ? `Stopped waiting for job ${abandonedJobId}. The reader may still be processing it.`
      : "The request was stopped before a job was created.";
    state.alertMessages = [];

    renderAll();
    focusElement(state.files.length ? "ready-heading" : "file-input");
  }

  function dismissError() {
    state.error = null;
    state.notice = "";
    state.phase = state.files.length ? PHASE.READY : PHASE.IDLE;
    renderAll();
    focusElement(state.files.length ? "ready-heading" : "file-input");
  }
})();
