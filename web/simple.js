/* JobLens product flow.
 *
 * The browser controller owns presentation only. Every approval, edit and
 * export is validated again by the local server (see release_guard.py); the
 * client never treats its own state as permission to download.
 *
 * The pure helpers below are exported for Node tests and contain no DOM code.
 */
"use strict";

(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.JobLensProduct = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const MAX_FILES = 5;
  const MAX_FILE_BYTES = 10 * 1024 * 1024;
  const MAX_TOTAL_BYTES = 25 * 1024 * 1024;
  const MIN_JOB_LENGTH = 40;
  const MAX_JOB_LENGTH = 20000;
  const PDF_MIME = "application/pdf";
  const DOCX_MIME =
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

  const SAMPLE_JOB = [
    "Senior Data Engineer",
    "",
    "Northwind Analytics · Remote (Spain)",
    "",
    "About the role",
    "Build reliable batch and streaming data pipelines and trusted datasets for analytics.",
    "",
    "Required",
    "Python",
    "SQL",
    "Docker",
    "Kubernetes",
    "",
    "Preferred",
    "AWS",
    "Terraform",
    "",
    "Responsibilities",
    "- Build and maintain batch and streaming data pipelines.",
    "- Partner with analysts to ship trusted datasets.",
    "",
    "5+ years of professional experience.",
  ].join("\n");

  const SAMPLE_FILES = [
    { url: "/samples/alex-rivera-cv.pdf", name: "alex-rivera-cv.pdf", type: PDF_MIME },
    { url: "/samples/alex-rivera-cv-2.docx", name: "alex-rivera-cv-2.docx", type: DOCX_MIME },
  ];

  /* ---------------------------------------------------------------- pure */

  function fileKind(file) {
    const name = String((file && file.name) || "").toLowerCase();
    if (name.endsWith(".pdf")) return "pdf";
    if (name.endsWith(".docx")) return "docx";
    const type = String((file && file.type) || "");
    if (type === PDF_MIME) return "pdf";
    if (type === DOCX_MIME) return "docx";
    return null;
  }

  function fileIdentity(file) {
    const name = String((file && file.name) || "").trim().toLowerCase();
    const size = Number(file && file.size) || 0;
    const modified = Number(file && file.lastModified) || 0;
    const type = String((file && file.type) || "").toLowerCase();
    return [name, size, modified, type].join("\u0000");
  }

  function mergeFileSelection(existing, incoming) {
    const current = Array.from(existing || []);
    const additions = Array.from(incoming || []);
    const seen = new Set(current.map(fileIdentity));
    const merged = current.slice();
    let duplicates = 0;
    for (const file of additions) {
      const key = fileIdentity(file);
      if (seen.has(key)) {
        duplicates += 1;
        continue;
      }
      seen.add(key);
      merged.push(file);
    }
    const validation = validateFiles(merged);
    if (!validation.ok) {
      return { ...validation, added: 0, duplicates };
    }
    return {
      ok: true,
      files: validation.files,
      added: merged.length - current.length,
      duplicates,
    };
  }

  function validateFiles(files) {
    const list = Array.from(files || []);
    if (!list.length) {
      return { ok: false, error: "Choose at least one PDF or DOCX file." };
    }
    if (list.length > MAX_FILES) {
      return {
        ok: false,
        error: "Choose at most five CVs at a time. Remove one and try again.",
      };
    }
    const unsupported = list.find((file) => !fileKind(file));
    if (unsupported) {
      const label = (unsupported && unsupported.name) || "That file";
      return {
        ok: false,
        error: label + " is not a PDF or DOCX file. Choose a PDF or DOCX CV.",
      };
    }
    const oversized = list.find(
      (file) => (Number(file && file.size) || 0) > MAX_FILE_BYTES,
    );
    if (oversized) {
      const label = (oversized && oversized.name) || "That file";
      return {
        ok: false,
        error: label + " is larger than 10 MB. Choose a smaller CV.",
      };
    }
    const total = list.reduce((sum, file) => sum + (Number(file.size) || 0), 0);
    if (total > MAX_TOTAL_BYTES) {
      return {
        ok: false,
        error: "Those files are larger than 25 MB in total. Choose smaller CVs.",
      };
    }
    return { ok: true, files: list };
  }

  function validatePosting(text) {
    const value = typeof text === "string" ? text.trim() : "";
    if (!value) {
      return { ok: false, error: "Paste the job posting first." };
    }
    if (value.length < MIN_JOB_LENGTH) {
      return {
        ok: false,
        error: "Paste at least 40 characters of the job posting.",
      };
    }
    if (value.length > MAX_JOB_LENGTH) {
      return {
        ok: false,
        error: "The job posting is too long. Use 20,000 characters or fewer.",
      };
    }
    return { ok: true };
  }

  function draftItems(draft) {
    const sections = (draft && draft.sections) || [];
    const out = [];
    sections.forEach((section) => {
      (section.items || []).forEach((item) => {
        out.push({ section, item });
      });
    });
    return out;
  }

  function fullName(draft) {
    const value = draft && draft.candidate && draft.candidate.full_name;
    return typeof value === "string" ? value.trim() : "";
  }

  function hasFullName(draft) {
    return Boolean(fullName(draft));
  }

  function draftStats(draft) {
    const entries = draftItems(draft);
    const approved = entries.filter(
      (entry) => entry.item.review_status === "approved",
    ).length;
    const empty = entries.filter(
      (entry) => !String(entry.item.text || "").trim(),
    ).length;
    return {
      total: entries.length,
      approved,
      needsReview: entries.length - approved,
      empty,
    };
  }

  function allApproved(draft) {
    const stats = draftStats(draft);
    return stats.total > 0 && stats.approved === stats.total;
  }

  function allItemsHaveText(draft) {
    return draftStats(draft).empty === 0;
  }

  function canGenerate(state) {
    return Boolean(
      state &&
        state.source &&
        !state.busy &&
        validatePosting(state.jobText).ok,
    );
  }

  function canConfirm(state) {
    return Boolean(
      state &&
        state.draft &&
        state.checked &&
        !state.busy &&
        hasFullName(state.draft) &&
        allItemsHaveText(state.draft) &&
        draftStats(state.draft).total > 0,
    );
  }

  function canDownload(state) {
    return Boolean(
      state &&
        state.draft &&
        state.confirmed &&
        !state.busy &&
        typeof state.receipt === "string" &&
        state.receipt &&
        hasFullName(state.draft) &&
        allApproved(state.draft),
    );
  }

  function moveItem(sections, sectionIndex, itemIndex, delta) {
    if (!Array.isArray(sections)) return false;
    const section = sections[sectionIndex];
    if (!section || !Array.isArray(section.items)) return false;
    const target = itemIndex + delta;
    if (target < 0 || target >= section.items.length) return false;
    const [item] = section.items.splice(itemIndex, 1);
    section.items.splice(target, 0, item);
    return true;
  }

  function moveSection(sections, index, delta) {
    if (!Array.isArray(sections)) return false;
    const target = index + delta;
    if (target < 0 || target >= sections.length) return false;
    const [section] = sections.splice(index, 1);
    sections.splice(target, 0, section);
    return true;
  }

  function removeItem(sections, sectionIndex, itemIndex) {
    if (!Array.isArray(sections)) return null;
    const section = sections[sectionIndex];
    if (!section || !Array.isArray(section.items)) return null;
    if (itemIndex < 0 || itemIndex >= section.items.length) return null;
    const [item] = section.items.splice(itemIndex, 1);
    if (!section.items.length) {
      sections.splice(sectionIndex, 1);
    }
    return item || null;
  }

  function sourceQuotes(draft, item) {
    const evidence =
      draft &&
      draft.review &&
      draft.review.baseline &&
      draft.review.baseline.evidence;
    if (!evidence || !item) return [];
    const quotes = [];
    for (const factId of item.approved_fact_ids || []) {
      for (const entry of evidence[factId] || []) {
        const quote = entry && typeof entry.quote === "string" ? entry.quote.trim() : "";
        if (quote && !quotes.includes(quote)) quotes.push(quote);
      }
    }
    return quotes;
  }

  function itemMode(draft, item) {
    const approvals = draft && draft.review && draft.review.approvals;
    if (!approvals || !item || !item.item_id) return null;
    const approval = approvals[item.item_id];
    return approval && approval.mode ? approval.mode : null;
  }

  function reviewNotes(draft) {
    if (!draft) {
      return { omitted: 0, unmet: [], warnings: [], sourceLines: 0 };
    }
    const entries = draftItems(draft);
    const warnings = (draft.warnings || []).filter((warning) => {
      const text = String(warning || "");
      return (
        !/full name is missing/i.test(text) &&
        !/contact method/i.test(text) &&
        !/found in the source documents/i.test(text)
      );
    });
    return {
      omitted: Number(draft.omitted_count) || 0,
      unmet: Array.isArray(draft.unmet_requirements)
        ? draft.unmet_requirements.filter(Boolean)
        : [],
      warnings,
      sourceLines: entries.filter(
        (entry) => sourceQuotes(draft, entry.item).length > 0,
      ).length,
    };
  }

  function contactParts(candidate) {
    if (!candidate) return [];
    const parts = [];
    if (candidate.location) parts.push(candidate.location);
    if (candidate.email) parts.push(candidate.email);
    if (candidate.phone) parts.push(candidate.phone);
    for (const link of candidate.links || []) {
      if (typeof link === "string" && link.trim()) parts.push(link.trim());
    }
    return parts;
  }

  const CONTACT_FORM_FIELDS = [
    { key: "full_name", label: "Full name", type: "text", autocomplete: "name", required: true },
    { key: "email", label: "Email", type: "email", autocomplete: "email" },
    { key: "phone", label: "Phone", type: "tel", autocomplete: "tel" },
    { key: "location", label: "Location", type: "text", autocomplete: "address-level2" },
    { key: "github", label: "GitHub", type: "url", autocomplete: "url", link: true },
    { key: "linkedin", label: "LinkedIn", type: "url", autocomplete: "url", link: true },
    { key: "website", label: "Portfolio website", type: "url", autocomplete: "url", link: true },
  ];

  const LINK_KEYS = ["github", "linkedin", "website"];

  function stringList(value) {
    if (!Array.isArray(value)) return [];
    return value.map((item) => String(item || "").trim()).filter(Boolean);
  }

  function linkParts(candidate) {
    const parts = { github: "", linkedin: "", website: "", other: [] };
    for (const link of stringList(candidate && candidate.links)) {
      const bare = link.toLowerCase().replace(/^https?:\/\//, "").replace(/^www\./, "");
      if (bare.startsWith("github.com/") && !parts.github) parts.github = link;
      else if (bare.startsWith("linkedin.com/") && !parts.linkedin) parts.linkedin = link;
      else if (!parts.website && !bare.startsWith("github.com/") && !bare.startsWith("linkedin.com/")) {
        parts.website = link;
      } else parts.other.push(link);
    }
    return parts;
  }

  function linksFromParts(parts, other) {
    const links = [];
    for (const key of LINK_KEYS) {
      const value = String((parts && parts[key]) || "").trim();
      if (value) links.push(value);
    }
    for (const value of stringList(other)) {
      if (!links.includes(value)) links.push(value);
    }
    return links;
  }

  function contactSuggestions(draft) {
    const envelope = draft && draft.contact_suggestions;
    if (!envelope || !Array.isArray(envelope.suggestions)) return new Map();
    const byField = new Map();
    for (const item of envelope.suggestions) {
      if (item && typeof item.field === "string") byField.set(item.field, item);
    }
    return byField;
  }

  function suggestionFor(draft, field) {
    return contactSuggestions(draft).get(field) || null;
  }

  /**
   * Fill supported, non-conflicting contact values into the editable draft.
   *
   * The server deliberately keeps contact values out of the generated
   * candidate so that extraction can never approve an identity. This helper
   * turns the documented contact suggestions into visible editable values the
   * candidate must still review and confirm as part of the exact final CV.
   * Conflicting or ambiguous suggestions are never selected.
   */
  function applyContactPrefill(draft) {
    const applied = new Set();
    if (!draft) return applied;
    if (!draft.candidate) {
      draft.candidate = { full_name: "", email: "", phone: "", location: "", links: [] };
    }
    const candidate = draft.candidate;
    const suggestions = contactSuggestions(draft);
    for (const field of ["full_name", "email", "phone", "location"]) {
      const suggestion = suggestions.get(field);
      const current = typeof candidate[field] === "string" ? candidate[field].trim() : "";
      if (!current && suggestion && suggestion.status === "supported" && suggestion.selected) {
        candidate[field] = suggestion.selected;
        applied.add(field);
      }
    }
    const parts = linkParts(candidate);
    for (const key of LINK_KEYS) {
      const suggestion = suggestions.get(key);
      if (parts[key]) continue;
      if (!suggestion || suggestion.status !== "supported" || !suggestion.selected) continue;
      parts[key] = String(suggestion.selected).trim();
      applied.add(key);
    }
    candidate.links = linksFromParts(parts, parts.other);
    return applied;
  }

  function contactSuggestionDetail(draft, field) {
    const suggestion = suggestionFor(draft, field);
    if (!suggestion) return null;
    const values = (suggestion.values || [])
      .map((item) => ({
        value: String((item && item.value) || "").trim(),
        evidence: (item && Array.isArray(item.evidence) ? item.evidence : [])
          .map((entry) => ({
            quote: String((entry && entry.quote) || "").trim(),
            document_id: String((entry && entry.document_id) || ""),
          }))
          .filter((entry) => entry.quote),
      }))
      .filter((item) => item.value);
    return {
      field,
      status: String(suggestion.status || ""),
      selected: suggestion.selected ? String(suggestion.selected) : "",
      values,
    };
  }

  function decisionReport(draft) {
    const raw = draft && draft.decision_report;
    if (!raw || !Array.isArray(raw.decisions)) return null;
    const decisions = raw.decisions
      .map((item) => {
        if (!item || typeof item !== "object") return null;
        const explanation = String(item.explanation || "").trim();
        if (!explanation) return null;
        return {
          outcome: String(item.outcome || ""),
          label: String(item.label || "").trim(),
          explanation,
          supports: stringList(item.supports),
          alternatives: stringList(item.alternatives),
          documents: stringList(item.documents),
        };
      })
      .filter(Boolean);
    const unmet = (Array.isArray(raw.unmet_requirements) ? raw.unmet_requirements : [])
      .map((item) =>
        typeof item === "string"
          ? { requirement: item, explanation: "" }
          : {
              requirement: String((item && item.requirement) || "").trim(),
              explanation: String((item && item.explanation) || "").trim(),
            },
      )
      .filter((item) => item.requirement);
    const counts = { included: 0, omitted: 0, insufficient: 0 };
    for (const decision of decisions) {
      if (Object.prototype.hasOwnProperty.call(counts, decision.outcome)) {
        counts[decision.outcome] += 1;
      }
    }
    return {
      version: String(raw.decision_report_version || ""),
      counts,
      decisions,
      unmet,
    };
  }

  function formatBytes(value) {
    const bytes = Number(value) || 0;
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function fileNameFor(kind, draft) {
    const name = fullName(draft)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
    return "joblens-" + (name || "cv") + "." + kind;
  }

  function targetLabel(draft) {
    const target = (draft && draft.target_job) || {};
    const parts = [target.title, target.company].filter(
      (part) => typeof part === "string" && part.trim(),
    );
    return parts.join(" · ");
  }

  /* -------------------------------------------------------------- browser */

  function init() {
    if (typeof document === "undefined" || !document.getElementById) {
      return null;
    }
    const $ = (id) => document.getElementById(id);

    const nodes = {
      create: $("create"),
      review: $("review"),
      createTitle: $("create-title"),
      reviewTitle: $("review-title"),
      reviewSubtitle: $("review-subtitle"),
      reviewProgress: $("review-progress"),
      status: $("status"),
      reviewStatus: $("review-status"),
      drop: $("drop"),
      files: $("files"),
      filesList: $("files-list"),
      fileCount: $("file-count"),
      filesEmpty: $("files-empty"),
      fileError: $("file-error"),
      job: $("job"),
      jobTitle: $("job-title"),
      jobCompany: $("job-company"),
      jobLocation: $("job-location"),
      jobCount: $("job-count"),
      jobError: $("job-error"),
      generate: $("generate"),
      generateNote: $("generate-note"),
      sample: $("sample"),
      preview: $("preview"),
      notes: $("notes"),
      editor: $("editor"),
      accuracy: $("accuracy"),
      confirm: $("confirm"),
      confirmStatus: $("confirm-status"),
      downloadNote: $("download-note"),
      pdf: $("pdf"),
      docx: $("docx"),
      startOver: $("start-over"),
    };

    if (!nodes.files || !nodes.job || !nodes.generate || !nodes.review) {
      return null;
    }

    if (
      typeof JobLensCV === "undefined" ||
      !JobLensCV.CvApiAdapter ||
      typeof JobLensProfileAdapter === "undefined" ||
      !JobLensProfileAdapter.buildProfileRequest
    ) {
      if (nodes.status) {
        nodes.status.textContent =
          "The app could not start. Reload the page to try again.";
        nodes.status.className = "status status-error";
      }
      return null;
    }

    const api = new JobLensCV.CvApiAdapter({ baseUrl: "/api/cv" });
    const state = {
      files: [],
      source: null,
      draft: null,
      receipt: null,
      confirmed: false,
      busy: false,
      phase: "",
      uploading: false,
      uploadSeq: 0,
      generateSeq: 0,
      actionSeq: 0,
      sampleLoading: false,
      hasEdits: false,
      savedTexts: new Map(),
      textareas: new Map(),
      linkInputs: new Map(),
      prefilledContacts: new Set(),
      documentLabels: {},
      lastStatus: "",
    };

    function busy() {
      return state.busy || state.uploading || state.sampleLoading;
    }

    function setText(node, text) {
      // Avoid replacing an identical text node in a live region; some screen
      // readers announce every mutation, including no-op updates.
      if (node && node.textContent !== text) node.textContent = text;
    }

    function setStatus(text, tone) {
      state.lastStatus = text;
      if (nodes.status) {
        setText(nodes.status, text);
        nodes.status.className = "status" + (tone ? " " + tone : "");
      }
      // The upload and review screens are mutually hidden. Keep a live
      // region on each side so updates are announced wherever the user is.
      if (nodes.reviewStatus) {
        setText(nodes.reviewStatus, text);
        nodes.reviewStatus.className =
          "status review-status" + (tone ? " " + tone : "");
      }
    }

    function setFieldError(node, message) {
      if (!node) return;
      node.textContent = message || "";
      node.hidden = !message;
    }

    function setBusy(phase) {
      state.phase = phase || "";
      state.busy = Boolean(phase);
      if (nodes.generate) {
        nodes.generate.disabled = !canGenerate({
          source: state.source,
          jobText: nodes.job.value,
          busy: busy(),
        });
        nodes.generate.setAttribute("aria-busy", state.busy ? "true" : "false");
      }
      if (nodes.sample) {
        nodes.sample.disabled = busy();
      }
      renderConfirmState();
    }

    function currentJobText() {
      return nodes.job ? nodes.job.value : "";
    }

    function selectedJobFields() {
      return {
        title: nodes.jobTitle ? nodes.jobTitle.value.trim() : "",
        company: nodes.jobCompany ? nodes.jobCompany.value.trim() : "",
        location: nodes.jobLocation ? nodes.jobLocation.value.trim() : "",
      };
    }

    function renderFiles() {
      if (!nodes.filesList) return;
      nodes.filesList.replaceChildren();
      state.files.forEach((file, index) => {
        const row = element("li", "file-item");
        const kind = fileKind(file) || "file";
        const badge = element("span", "file-badge", kind.toUpperCase());
        const name = element("span", "file-name", file.name);
        name.title = file.name;
        const size = element("span", "file-size", formatBytes(file.size));
        const remove = element("button", "icon-button file-remove", "×");
        remove.type = "button";
        remove.setAttribute("aria-label", "Remove " + file.name);
        remove.title = "Remove " + file.name;
        remove.addEventListener("click", () => removeFile(index));
        row.append(badge, name, size, remove);
        nodes.filesList.append(row);
      });
      if (nodes.filesEmpty) nodes.filesEmpty.hidden = state.files.length > 0;
      if (nodes.fileCount) {
        setText(nodes.fileCount, state.files.length + " / " + MAX_FILES);
      }
      renderGenerateState();
    }

    function renderGenerateState() {
      const posting = validatePosting(currentJobText());
      if (nodes.generate) {
        nodes.generate.disabled = !canGenerate({
          source: state.source,
          jobText: currentJobText(),
          busy: busy(),
        });
      }
      if (nodes.generateNote) {
        let note;
        if (!state.files.length) {
          note = "Add a CV and a job posting to generate your draft.";
        } else if (state.uploading) {
          note = "Reading your documents…";
        } else if (!state.source) {
          note = "We could not read those files. Try a text-based PDF or DOCX.";
        } else if (!posting.ok) {
          note = posting.error;
        } else {
          note = "Ready when you are. Generation uses only what your CVs support.";
        }
        setText(nodes.generateNote, note);
      }
      if (nodes.jobCount) {
        setText(
          nodes.jobCount,
          currentJobText().length.toLocaleString() + " / 20,000",
        );
      }
    }

    function renderContactAndItems() {
      if (!nodes.editor) return;
      state.textareas = new Map();
      state.linkInputs = new Map();
      nodes.editor.replaceChildren();

      const candidate = (state.draft && state.draft.candidate) || {};
      const linkFields = linkParts(candidate);
      const otherLinks = linkFields.other;
      const prefilled = state.prefilledContacts;

      if (prefilled.size) {
        nodes.editor.append(
          element(
            "p",
            "field-note contact-prefill-note",
            "Contact details found in your CVs are filled in below for you. Check every value before you confirm this exact CV.",
          ),
        );
      }

      for (const field of CONTACT_FORM_FIELDS) {
        const { key, label, type, autocomplete, required, link } = field;
        const wrapper = element("label", "control-field");
        wrapper.setAttribute("data-field", key);
        if (prefilled.has(key)) wrapper.setAttribute("data-suggested", "true");
        const labelNode = element("span", "field-label");
        labelNode.append(document.createTextNode(label));
        if (required) {
          labelNode.append(element("em", "required", "required"));
        }
        if (prefilled.has(key)) {
          labelNode.append(element("span", "suggested-tag", "from your CV"));
        }
        const input = element("input");
        input.type = type;
        input.id = "candidate-" + key;
        input.autocomplete = autocomplete;
        input.value = link ? linkFields[key] || "" : candidate[key] || "";
        input.setAttribute("aria-label", label);
        if (required) input.setAttribute("aria-required", "true");
        if (link) {
          state.linkInputs.set(key, input);
          input.addEventListener("input", () => {
            const parts = {};
            for (const linkKey of LINK_KEYS) {
              const node = state.linkInputs.get(linkKey);
              parts[linkKey] = node ? node.value : linkFields[linkKey];
            }
            state.draft.candidate.links = linksFromParts(parts, otherLinks);
            invalidateConfirmation("contact");
            renderPreview();
            renderConfirmState();
          });
        } else {
          input.addEventListener("input", () => {
            state.draft.candidate[key] = input.value;
            if (required) {
              input.setAttribute(
                "aria-invalid",
                input.value.trim() ? "false" : "true",
              );
            }
            invalidateConfirmation("contact");
            renderPreview();
            renderConfirmState();
          });
        }
        wrapper.append(labelNode, input);

        const detail = contactSuggestionDetail(state.draft, key);
        if (detail) {
          if (detail.status === "conflict" || (detail.values.length > 1 && !detail.selected)) {
            const alternatives = detail.values.map((item) => item.value).join(" / ");
            wrapper.append(
              element(
                "span",
                "contact-conflict",
                "Your CVs show different values: " +
                  alternatives +
                  ". Nothing was chosen for you; enter the correct value.",
              ),
            );
          }
          const quotes = [];
          for (const value of detail.values) {
            if (detail.selected && value.value !== detail.selected) continue;
            for (const evidence of value.evidence) {
              if (evidence.quote && !quotes.includes(evidence.quote)) {
                quotes.push(evidence.quote);
              }
            }
          }
          if (quotes.length) {
            const source = element("details", "contact-source");
            source.append(element("summary", "contact-source-summary", "Source wording"));
            const body = element("div", "contact-source-body");
            for (const quote of quotes) {
              body.append(element("blockquote", "source-quote", quote));
            }
            source.append(body);
            wrapper.append(source);
          }
        }
        nodes.editor.append(wrapper);
      }

      const sections = (state.draft && state.draft.sections) || [];
      sections.forEach((section, sectionIndex) => {
        const group = element("div", "control-section");
        group.setAttribute("data-section-index", String(sectionIndex));
        const head = element("div", "control-section-head");
        const title = element("h4", "control-section-title", section.title);
        const tools = element("div", "section-tools");
        const up = iconButton("↑", "Move " + section.title + " section up", () =>
          reorderSection(sectionIndex, -1),
        );
        up.disabled = sectionIndex === 0;
        const down = iconButton("↓", "Move " + section.title + " section down", () =>
          reorderSection(sectionIndex, 1),
        );
        down.disabled = sectionIndex === sections.length - 1;
        tools.append(up, down);
        head.append(title, tools);
        group.append(head);

        (section.items || []).forEach((item, itemIndex) => {
          const entry = element("div", "entry");
          entry.setAttribute("data-item-id", item.item_id || "");
          const entryHead = element("div", "entry-head");
          const stateNode = element(
            "span",
            "state " +
              (item.review_status === "approved"
                ? "state-ok"
                : "state-warn"),
            item.review_status === "approved" ? "Confirmed" : "Needs review",
          );
          const itemTools = element("div", "entry-tools");
          const itemUp = iconButton("↑", "Move this " + section.title + " line up", () =>
            reorderItem(sectionIndex, itemIndex, -1),
          );
          itemUp.disabled = itemIndex === 0;
          const itemDown = iconButton(
            "↓",
            "Move this " + section.title + " line down",
            () => reorderItem(sectionIndex, itemIndex, 1),
          );
          itemDown.disabled = itemIndex === (section.items || []).length - 1;
          const remove = iconButton(
            "×",
            "Remove this " + section.title + " line",
            () => removeLine(sectionIndex, itemIndex),
            "icon-button danger",
          );
          itemTools.append(itemUp, itemDown, remove);
          entryHead.append(stateNode, itemTools);

          const textarea = element("textarea", "entry-text");
          textarea.rows = 2;
          textarea.value = item.text || "";
          textarea.setAttribute(
            "aria-label",
            section.title + " line " + (itemIndex + 1) + " wording",
          );
          textarea.addEventListener("input", () => {
            item.text = textarea.value;
            item.review_status = "needs_review";
            if (state.draft.review && state.draft.review.approvals) {
              delete state.draft.review.approvals[item.item_id];
            }
            state.hasEdits = true;
            stateNode.className = "state state-warn";
            stateNode.textContent = "Needs review";
            invalidateConfirmation("edit");
            renderPreview();
            renderConfirmState();
          });
          textarea.addEventListener("change", () =>
            saveEdit(item.item_id, textarea.value),
          );
          state.textareas.set(item.item_id, textarea);

          const source = element("details", "source-box");
          const summary = element("summary", "source-summary", "Source wording");
          const sourceBody = element("div", "source-body");
          const mode = itemMode(state.draft, item);
          const quotes = sourceQuotes(state.draft, item);
          if (mode === "candidate_attested") {
            sourceBody.append(
              element(
                "p",
                "source-note",
                "You wrote this wording. It is not presented as documentary evidence.",
              ),
            );
          } else if (quotes.length) {
            quotes.forEach((quote) => {
              sourceBody.append(element("blockquote", "source-quote", quote));
            });
          } else {
            sourceBody.append(
              element("p", "source-note", "No source quote is attached to this line."),
            );
          }
          source.append(summary, sourceBody);

          entry.append(entryHead, textarea, source);
          group.append(entry);
        });

        nodes.editor.append(group);
      });

      if (!sections.length) {
        nodes.editor.append(
          element(
            "p",
            "empty-note",
            "This draft has no content left. Start over to generate another CV.",
          ),
        );
      }
    }

    function renderPreview() {
      if (!nodes.preview) return;
      nodes.preview.replaceChildren();
      if (!state.draft) return;
      const candidate = state.draft.candidate || {};
      const name = fullName(state.draft);
      const paper = element("article", "cv-paper");
      paper.setAttribute("aria-label", "CV preview");

      // The paper is a visual preview inside the page's own heading outline.
      // Its name and section labels are styled text, not extra document headings.
      const heading = element(
        "p",
        "cv-name" + (name ? "" : " is-placeholder"),
        name || "Your name",
      );
      paper.append(heading);
      const contact = contactParts(candidate);
      if (contact.length) {
        paper.append(element("p", "cv-contact", contact.join("  ·  ")));
      }

      for (const section of state.draft.sections || []) {
        const items = (section.items || []).filter(
          (item) => String(item.text || "").trim(),
        );
        if (!items.length) continue;
        const block = element("section", "cv-section");
        block.append(element("p", "cv-section-title", section.title));
        const kind = String(section.kind || "").toLowerCase();
        if (kind === "skills" || kind === "languages" || kind === "certifications") {
          block.append(
            element(
              "p",
              "cv-inline",
              items.map((item) => item.text.trim()).join(", "),
            ),
          );
        } else if (kind === "summary") {
          items.forEach((item) => {
            block.append(element("p", "cv-body", item.text.trim()));
          });
        } else if (kind === "education") {
          items.forEach((item) => {
            const entry = element("div", "cv-entry");
            const headingText = (item.heading || "").trim();
            if (headingText && headingText.toLowerCase() !== item.text.trim().toLowerCase()) {
              entry.append(element("p", "cv-entry-heading", headingText));
            }
            entry.append(element("p", "cv-body", item.text.trim()));
            if (item.period) entry.append(element("p", "cv-small", item.period));
            if (item.location) entry.append(element("p", "cv-small", item.location));
            block.append(entry);
          });
        } else {
          items.forEach((item) => {
            const entry = element("div", "cv-entry");
            const headingText = (item.heading || "").trim();
            const subheading = (item.subheading || "").trim();
            const period = (item.period || "").trim();
            if (headingText || subheading || period) {
              const head = element("div", "cv-entry-head");
              const left = element("div", "cv-entry-left");
              if (headingText) left.append(element("p", "cv-entry-heading", headingText));
              if (subheading && subheading !== headingText) {
                left.append(element("p", "cv-entry-sub", subheading));
              }
              head.append(left);
              if (period) head.append(element("span", "cv-period", period));
              entry.append(head);
            }
            const text = item.text.trim();
            const combined = (headingText + " " + subheading).trim().toLowerCase();
            if (text && text.toLowerCase() !== combined && text.toLowerCase() !== headingText.toLowerCase()) {
              entry.append(element("p", "cv-bullet", "•  " + text));
            } else if (text && text.toLowerCase() === headingText.toLowerCase()) {
              entry.append(element("p", "cv-body", text));
            }
            if (item.location) entry.append(element("p", "cv-small", item.location));
            block.append(entry);
          });
        }
        paper.append(block);
      }
      nodes.preview.append(paper);
    }

    function renderNotes() {
      if (!nodes.notes) return;
      nodes.notes.replaceChildren();
      if (!state.draft) return;
      const notes = reviewNotes(state.draft);
      const details = element("details", "notes-box");
      const summary = element("summary", "notes-summary");
      summary.append(document.createTextNode("Why this content? "));
      if (notes.omitted) {
        summary.append(element("span", "notes-count", String(notes.omitted) + " left out"));
      }
      details.append(summary);
      const body = element("div", "notes-body");
      body.append(
        element(
          "p",
          "notes-intro",
          "This draft was built only from what your uploaded CVs support, matched to the job posting. Nothing was invented.",
        ),
      );
      if (notes.sourceLines) {
        body.append(
          element(
            "p",
            "notes-line",
            notes.sourceLines +
              " line" +
              (notes.sourceLines === 1 ? "" : "s") +
              " have source wording you can check under “Source wording”.",
          ),
        );
      }

      const report = decisionReport(state.draft);
      if (report) {
        const counts = report.counts;
        const summary = element("div", "note-item decision-summary");
        summary.append(
          element("strong", "note-title", "What this draft decided"),
        );
        summary.append(
          element(
            "p",
            "note-copy",
            counts.included +
              " included · " +
              counts.omitted +
              " left out · " +
              counts.insufficient +
              " needing your decision. These explanations come from the actual generation decisions.",
          ),
        );
        const list = element("ul", "decision-list");
        for (const decision of report.decisions) {
          const row = element(
            "li",
            "decision decision-" + (decision.outcome || "other"),
          );
          const head = element("div", "decision-head");
          const badge =
            decision.outcome === "included"
              ? "Included"
              : decision.outcome === "omitted"
                ? "Left out"
                : "Needs your decision";
          head.append(element("span", "decision-badge", badge));
          if (decision.label) head.append(element("strong", "decision-label", decision.label));
          row.append(head);
          row.append(element("p", "decision-copy", decision.explanation));
          if (decision.supports.length) {
            row.append(
              element(
                "p",
                "decision-detail",
                "Job requirement: " + decision.supports.join("; "),
              ),
            );
          }
          if (decision.alternatives.length) {
            row.append(
              element(
                "p",
                "decision-detail",
                "Values in your sources: " + decision.alternatives.join("; "),
              ),
            );
          }
          if (decision.documents.length) {
            row.append(
              element(
                "p",
                "decision-detail",
                "Source: " + decision.documents.join(", "),
              ),
            );
          }
          list.append(row);
        }
        summary.append(list);
        body.append(summary);
      }

      if (notes.omitted && !report) {
        const item = element("div", "note-item note-warn");
        item.append(element("strong", "note-title", "Left out"));
        item.append(
          element(
            "p",
            "note-copy",
            notes.omitted +
              " conflicting or uncertain detail" +
              (notes.omitted === 1 ? " was" : "s were") +
              " left out. Check your source CVs before adding anything yourself.",
          ),
        );
        body.append(item);
      }
      const unmet = report && report.unmet.length ? report.unmet.map((item) => item.requirement) : notes.unmet;
      if (unmet.length) {
        const item = element("div", "note-item");
        item.append(element("strong", "note-title", "Not found in your CVs"));
        item.append(
          element(
            "p",
            "note-copy",
            "These job requirements are not supported by your source CVs, so they were not added.",
          ),
        );
        const list = element("ul", "note-list");
        unmet.forEach((requirement) => {
          list.append(element("li", "", requirement));
        });
        item.append(list);
        body.append(item);
      }
      if (notes.warnings.length) {
        const item = element("div", "note-item");
        item.append(element("strong", "note-title", "Notes from the generator"));
        const list = element("ul", "note-list");
        notes.warnings.forEach((warning) => {
          list.append(element("li", "", warning));
        });
        item.append(list);
        body.append(item);
      }
      details.append(body);
      nodes.notes.append(details);
    }

    function renderReviewSubtitle() {
      if (!nodes.reviewSubtitle) return;
      const target = targetLabel(state.draft);
      setText(
        nodes.reviewSubtitle,
        target
          ? "Tailored for " + target + ". Check every line, edit anything, then confirm this exact version."
          : "Check every line. Edit anything. Confirm when this exact version is accurate.",
      );
    }

    function renderConfirmState() {
      const checked = Boolean(nodes.accuracy && nodes.accuracy.checked);
      const full = hasFullName(state.draft);
      const stats = draftStats(state.draft);
      const ready = canConfirm({
        draft: state.draft,
        checked,
        busy: busy(),
        saving: false,
      });

      if (nodes.reviewProgress) {
        if (state.confirmed) {
          setText(
            nodes.reviewProgress,
            "All " + stats.total + " line" + (stats.total === 1 ? "" : "s") + " confirmed",
          );
          nodes.reviewProgress.className = "pill pill-ok";
        } else if (stats.total === 0) {
          setText(nodes.reviewProgress, "No content");
          nodes.reviewProgress.className = "pill pill-warn";
        } else {
          setText(
            nodes.reviewProgress,
            stats.needsReview +
              " of " +
              stats.total +
              " line" +
              (stats.total === 1 ? "" : "s") +
              " need review",
          );
          nodes.reviewProgress.className = "pill pill-warn";
        }
      }

      if (nodes.confirm) {
        nodes.confirm.disabled = state.confirmed || !ready;
        setText(
          nodes.confirm,
          state.confirmed ? "CV confirmed" : "Confirm final CV",
        );
      }
      if (nodes.confirmStatus) {
        let statusText;
        if (state.confirmed) {
          statusText = "Confirmed. This exact version is ready to download.";
        } else if (!full) {
          statusText = "Add your full name in the contact details to continue.";
        } else if (stats.empty) {
          statusText = "Every line needs wording before you can confirm.";
        } else if (!checked) {
          statusText = "Tick the accuracy statement above to confirm.";
        } else {
          statusText = "Ready to confirm this exact version.";
        }
        setText(nodes.confirmStatus, statusText);
      }

      const downloadReady = canDownload({
        draft: state.draft,
        confirmed: state.confirmed,
        receipt: state.receipt,
        busy: busy(),
      });
      if (nodes.pdf) nodes.pdf.disabled = !downloadReady;
      if (nodes.docx) nodes.docx.disabled = !downloadReady;
      if (nodes.downloadNote) {
        let note;
        if (state.confirmed) {
          note = "Downloads are enabled for this confirmed version.";
        } else if (!full) {
          note = "Add your full name to unlock downloads.";
        } else {
          note = "Downloads unlock after you confirm this exact version.";
        }
        setText(nodes.downloadNote, note);
      }
    }

    function renderAll() {
      renderPreview();
      renderNotes();
      renderReviewSubtitle();
      renderContactAndItems();
      renderConfirmState();
    }

    function invalidateConfirmation(reason) {
      // Any change makes every in-flight confirmation or export response
      // obsolete. Bumping the action token makes the controller discard a
      // late reply instead of restoring a stale review state.
      state.actionSeq += 1;
      const wasConfirmed = state.confirmed;
      const wasPending =
        state.phase === "confirming" || state.phase === "downloading";
      state.confirmed = false;
      state.receipt = null;
      if (state.draft && state.draft.review) {
        delete state.draft.review.final_receipt;
      }
      if (nodes.accuracy) nodes.accuracy.checked = false;
      if (wasPending) {
        state.busy = false;
        state.phase = "";
        setBusy("");
      }
      if (reason && wasConfirmed) {
        setStatus(
          "Changes made. Review this version, then confirm it again before downloading.",
          "",
        );
      }
      renderConfirmState();
    }

    function showReview() {
      if (nodes.create) nodes.create.hidden = true;
      if (nodes.review) nodes.review.hidden = false;
      if (typeof document !== "undefined") document.title = "Review your CV · JobLens";
      if (nodes.reviewTitle && nodes.reviewTitle.focus) {
        nodes.reviewTitle.focus({ preventScroll: true });
      }
      scrollTop();
    }

    function showCreate() {
      if (nodes.review) nodes.review.hidden = true;
      if (nodes.create) nodes.create.hidden = false;
      if (typeof document !== "undefined") document.title = "JobLens · Your next CV";
      if (nodes.createTitle && nodes.createTitle.focus) {
        nodes.createTitle.focus({ preventScroll: true });
      }
      scrollTop();
    }

    function scrollTop() {
      try {
        if (typeof window !== "undefined" && window.scrollTo) window.scrollTo(0, 0);
      } catch (_) {
        /* ignore */
      }
    }

    async function readDocuments(files) {
      const validation = validateFiles(files);
      if (!validation.ok) {
        setFieldError(nodes.fileError, validation.error);
        setStatus(validation.error, "status-error");
        return false;
      }
      setFieldError(nodes.fileError, "");
      state.generateSeq += 1;
      state.actionSeq += 1;
      state.files = validation.files;
      state.source = null;
      state.draft = null;
      state.receipt = null;
      state.confirmed = false;
      state.hasEdits = false;
      state.savedTexts = new Map();
      state.textareas = new Map();
      state.linkInputs = new Map();
      state.prefilledContacts = new Set();
      state.documentLabels = {};
      if (nodes.accuracy) nodes.accuracy.checked = false;
      if (nodes.review) nodes.review.hidden = true;
      renderFiles();
      renderGenerateState();

      const seq = ++state.uploadSeq;
      state.uploading = true;
      setStatus(
        "Reading " +
          (files.length === 1 ? "your CV" : files.length + " CVs") +
          "…",
        "status-busy",
      );
      setBusy("");
      renderGenerateState();
      try {
        const batch = await api.createExtraction(files);
        if (seq !== state.uploadSeq) return false;
        if (!batch || batch.status === "rejected" || !(batch.documents || []).length) {
          throw new Error(
            "We could not read text from those files. Try a text-based PDF or a DOCX.",
          );
        }
        const readable = (batch.documents || []).filter(
          (document) => document.status === "extracted" || document.status === "partial",
        );
        state.source = JobLensProfileAdapter.buildProfileRequest(batch);
        state.documentLabels = {};
        for (const document of state.source.documents || []) {
          const id = String(document.document_id || "");
          if (id) {
            state.documentLabels[id] = String(
              document.filename || "Uploaded CV " + (Number(document.index) + 1),
            );
          }
        }
        state.uploading = false;
        setBusy("");
        renderGenerateState();
        if (!readable.length) {
          setStatus(
            "The files were read, but no usable text was found. Try a text-based PDF or DOCX.",
            "status-error",
          );
        } else {
          setStatus(
            "Documents read. Paste the job posting, then generate your CV.",
            "status-success",
          );
        }
        return true;
      } catch (error) {
        if (seq !== state.uploadSeq) return false;
        state.source = null;
        state.uploading = false;
        setBusy("");
        renderGenerateState();
        const message = friendlyError(error);
        setFieldError(nodes.fileError, message);
        setStatus(message, "status-error");
        return false;
      }
    }

    async function addDocuments(files) {
      const merged = mergeFileSelection(state.files, files);
      if (!merged.ok) {
        setFieldError(nodes.fileError, merged.error);
        setStatus(merged.error, "status-error");
        return false;
      }
      if (!merged.added) {
        setFieldError(nodes.fileError, "");
        setStatus("Those CVs are already selected.", "");
        return true;
      }
      return readDocuments(merged.files);
    }

    async function generate() {
      if (busy()) return;
      const posting = validatePosting(currentJobText());
      if (!state.source) {
        if (!state.files.length) {
          setStatus("Add at least one CV first.", "status-error");
          if (nodes.drop && nodes.drop.focus) nodes.drop.focus();
        } else {
          setStatus(
            "Your documents are not ready yet. Wait for them to be read, or remove and re-add a text-based PDF or DOCX.",
            "status-error",
          );
        }
        return;
      }
      if (!posting.ok) {
        setFieldError(nodes.jobError, posting.error);
        setStatus(posting.error, "status-error");
        if (nodes.job && nodes.job.focus) nodes.job.focus();
        return;
      }
      setFieldError(nodes.jobError, "");
      state.generateSeq += 1;
      state.actionSeq += 1;
      const seq = state.generateSeq;
      state.draft = null;
      state.receipt = null;
      state.confirmed = false;
      state.hasEdits = false;
      state.prefilledContacts = new Set();
      if (nodes.accuracy) nodes.accuracy.checked = false;
      setBusy("generating");
      setStatus("Writing your draft from your CVs…", "status-busy");
      try {
        const result = await post("draft", {
          source: state.source,
          text: currentJobText(),
        });
        if (seq !== state.generateSeq) return;
        if (!result || !result.draft) {
          throw new Error("The draft came back empty. Try generating again.");
        }
        state.draft = result.draft;
        const fields = selectedJobFields();
        if (!state.draft.target_job) state.draft.target_job = {};
        if (fields.title) state.draft.target_job.title = fields.title;
        if (fields.company) state.draft.target_job.company = fields.company;
        state.draft.candidate = state.draft.candidate || {
          full_name: null,
          email: null,
          phone: null,
          location: null,
          links: [],
        };
        state.prefilledContacts = applyContactPrefill(state.draft);
        state.savedTexts = new Map(
          draftItems(state.draft).map((entry) => [entry.item.item_id, entry.item.text]),
        );
        state.busy = false;
        state.phase = "";
        setBusy("");
        renderAll();
        showReview();
        setStatus(
          state.prefilledContacts.size
            ? "Draft ready. Contact details found in your CVs are filled in for review. Review every line, then confirm this exact version."
            : "Draft ready. Review every line, add your contact details, then confirm.",
          "status-success",
        );
      } catch (error) {
        if (seq !== state.generateSeq) return;
        state.busy = false;
        state.phase = "";
        setBusy("");
        setStatus(friendlyError(error), "status-error");
        if (nodes.job && nodes.job.focus) nodes.job.focus();
      }
    }

    async function saveEdit(itemId, text) {
      if (!state.draft || !itemId) return;
      if (state.savedTexts.get(itemId) === text) return;
      try {
        // The edit route validates the baseline and records the changed
        // wording. The local draft stays authoritative for later edits; the
        // final confirmation validates the whole current draft again.
        await post("cv-drafts/edit", {
          draft: state.draft,
          item_id: itemId,
          text,
        });
        state.savedTexts.set(itemId, text);
      } catch (error) {
        setStatus(
          "Your wording is kept in this page, but it was not saved to the local review yet. Confirm the final CV to validate it, or try editing again. " +
            friendlyError(error),
          "status-error",
        );
      }
    }

    function reorderItem(sectionIndex, itemIndex, delta) {
      if (!state.draft || !state.draft.sections) return;
      const item = state.draft.sections[sectionIndex].items[itemIndex];
      if (!moveItem(state.draft.sections, sectionIndex, itemIndex, delta)) return;
      state.hasEdits = true;
      invalidateConfirmation("move");
      renderPreview();
      renderContactAndItems();
      renderConfirmState();
      const textarea = item && state.textareas.get(item.item_id);
      if (textarea && textarea.focus) textarea.focus();
    }

    function reorderSection(sectionIndex, delta) {
      if (!state.draft || !state.draft.sections) return;
      const section = state.draft.sections[sectionIndex];
      if (!moveSection(state.draft.sections, sectionIndex, delta)) return;
      state.hasEdits = true;
      invalidateConfirmation("move");
      renderPreview();
      renderContactAndItems();
      renderConfirmState();
      const firstItem = section && section.items && section.items[0];
      const textarea = firstItem && state.textareas.get(firstItem.item_id);
      if (textarea && textarea.focus) textarea.focus();
    }

    function removeLine(sectionIndex, itemIndex) {
      if (!state.draft || !state.draft.sections) return;
      const section = state.draft.sections[sectionIndex];
      if (!section) return;
      const removed = removeItem(state.draft.sections, sectionIndex, itemIndex);
      if (!removed) return;
      state.hasEdits = true;
      invalidateConfirmation("remove");
      renderPreview();
      renderNotes();
      renderContactAndItems();
      renderConfirmState();
      setStatus("Line removed. Confirm the current version again before downloading.", "");
    }

    async function confirm() {
      if (!state.draft) return;
      if (busy()) return;
      if (!nodes.accuracy || !nodes.accuracy.checked) {
        if (nodes.confirmStatus) {
          setText(nodes.confirmStatus, "Tick the accuracy statement first.");
        }
        if (nodes.accuracy && nodes.accuracy.focus) nodes.accuracy.focus();
        return;
      }
      if (!hasFullName(state.draft)) {
        if (nodes.confirmStatus) {
          setText(
            nodes.confirmStatus,
            "Add your full name in the contact details before confirming.",
          );
        }
        focusField("full_name");
        return;
      }
      if (!allItemsHaveText(state.draft)) {
        if (nodes.confirmStatus) {
          setText(
            nodes.confirmStatus,
            "Every line needs wording before you can confirm.",
          );
        }
        setStatus("Every line needs wording before you can confirm.", "status-error");
        return;
      }
      const token = ++state.actionSeq;
      const draftRef = state.draft;
      setBusy("confirming");
      setStatus("Confirming this exact version…", "status-busy");
      if (nodes.confirmStatus) setText(nodes.confirmStatus, "Confirming…");
      try {
        const result = await post("confirm", {
          draft: draftRef,
          confirmed: true,
          attested: true,
        });
        if (token !== state.actionSeq || draftRef !== state.draft) return;
        if (!result || !result.draft) {
          throw new Error("The server did not return a confirmed draft.");
        }
        state.draft = result.draft;
        state.receipt =
          (result.draft.review && result.draft.review.final_receipt) || null;
        state.confirmed = Boolean(state.receipt);
        if (nodes.accuracy) nodes.accuracy.checked = state.confirmed;
        state.busy = false;
        state.phase = "";
        setBusy("");
        renderAll();
        if (state.confirmed) {
          setStatus(
            "This version is confirmed. Download it as PDF or DOCX.",
            "status-success",
          );
        } else {
          setStatus(
            "The server did not confirm this version. Review it and try again.",
            "status-error",
          );
        }
      } catch (error) {
        if (token !== state.actionSeq || draftRef !== state.draft) return;
        state.busy = false;
        state.phase = "";
        state.confirmed = false;
        state.receipt = null;
        if (nodes.accuracy) nodes.accuracy.checked = false;
        setBusy("");
        renderConfirmState();
        const message = friendlyError(error);
        if (nodes.confirmStatus) setText(nodes.confirmStatus, message);
        setStatus(message, "status-error");
        if (error && error.code === "missing_contact") focusField("full_name");
      }
    }

    function focusField(key) {
      const input =
        typeof document !== "undefined" && document.getElementById
          ? document.getElementById("candidate-" + key)
          : null;
      if (input && input.focus) input.focus();
    }

    async function download(kind) {
      if (!canDownload({
        draft: state.draft,
        confirmed: state.confirmed,
        receipt: state.receipt,
        busy: busy(),
      })) {
        setStatus(
          "Confirm this exact version before downloading.",
          "status-error",
        );
        return;
      }
      const token = ++state.actionSeq;
      const draftRef = state.draft;
      setBusy("downloading");
      setStatus("Preparing your " + kind.toUpperCase() + "…", "status-busy");
      try {
        let response;
        try {
          response = await fetch("/api/cv/cv-drafts/export/" + kind, {
            method: "POST",
            cache: "no-store",
            headers: {
              "Content-Type": "application/json",
              "X-JobLens-Request": "1",
            },
            body: JSON.stringify({
              draft: draftRef,
              confirmed: true,
              contact: draftRef.candidate,
            }),
          });
        } catch (_) {
          throw httpError(
            "Could not reach the local server. Check that it is running, then try again.",
            "network",
          );
        }
        if (token !== state.actionSeq || draftRef !== state.draft) return;
        if (!response.ok) {
          let failure = {};
          try {
            failure = await response.json();
          } catch (_) {
            failure = {};
          }
          throw httpError(
            failure.error || "The download could not be prepared.",
            failure.code,
          );
        }
        const blob = await response.blob();
        if (token !== state.actionSeq || draftRef !== state.draft) return;
        if (typeof URL !== "undefined" && URL.createObjectURL) {
          const url = URL.createObjectURL(blob);
          const link = element("a");
          link.href = url;
          link.download = fileNameFor(kind, state.draft);
          link.setAttribute("download", link.download);
          document.body.append(link);
          link.click();
          link.remove();
          if (URL.revokeObjectURL) {
            // Give Safari and slower download managers time to start reading
            // the blob before the object URL is released.
            setTimeout(() => URL.revokeObjectURL(url), 30000);
          }
        }
        state.busy = false;
        state.phase = "";
        setBusy("");
        setStatus("Your " + kind.toUpperCase() + " download is ready.", "status-success");
      } catch (error) {
        if (token !== state.actionSeq || draftRef !== state.draft) return;
        state.busy = false;
        state.phase = "";
        setBusy("");
        if (
          error &&
          (error.code === "draft_changed" ||
            /confirm the current version/i.test(error.message || ""))
        ) {
          state.confirmed = false;
          state.receipt = null;
          if (nodes.accuracy) nodes.accuracy.checked = false;
          renderConfirmState();
          setStatus(
            "This draft changed. Confirm the current version again before downloading.",
            "status-error",
          );
        } else {
          setStatus(friendlyError(error), "status-error");
        }
      }
    }

    async function trySample() {
      if (busy()) return;
      if (
        state.files.length ||
        state.source ||
        (nodes.job && String(nodes.job.value || "").trim())
      ) {
        const confirmed =
          typeof window === "undefined" ||
          typeof window.confirm !== "function" ||
          window.confirm(
            "Replace the documents and job description already loaded with the sample CVs?",
          );
        if (!confirmed) return;
      }
      const token = state.uploadSeq;
      state.sampleLoading = true;
      setBusy("");
      setStatus("Loading the sample CVs…", "status-busy");
      try {
        const files = [];
        for (const sample of SAMPLE_FILES) {
          const response = await fetch(sample.url, { cache: "no-store" });
          if (!response.ok) {
            throw new Error("The sample files could not be loaded.");
          }
          const blob = await response.blob();
          files.push(new File([blob], sample.name, { type: sample.type }));
        }
        if (state.uploadSeq !== token) {
          state.sampleLoading = false;
          return;
        }
        if (nodes.job) nodes.job.value = SAMPLE_JOB;
        if (nodes.jobTitle) nodes.jobTitle.value = "Senior Data Engineer";
        if (nodes.jobCompany) nodes.jobCompany.value = "Northwind Analytics";
        if (nodes.jobLocation) nodes.jobLocation.value = "Remote · Spain";
        setFieldError(nodes.jobError, "");
        state.sampleLoading = false;
        setBusy("");
        renderGenerateState();
        const ready = await readDocuments(files);
        if (ready && state.source) {
          await generate();
        }
      } catch (error) {
        state.sampleLoading = false;
        setBusy("");
        setStatus(
          "The sample could not be loaded. Check that the local server is running and try again.",
          "status-error",
        );
      }
    }

    async function startOver() {
      state.uploadSeq += 1;
      state.generateSeq += 1;
      state.actionSeq += 1;
      state.files = [];
      state.source = null;
      state.draft = null;
      state.receipt = null;
      state.confirmed = false;
      state.hasEdits = false;
      state.savedTexts = new Map();
      state.textareas = new Map();
      state.linkInputs = new Map();
      state.prefilledContacts = new Set();
      state.documentLabels = {};
      state.busy = false;
      state.phase = "";
      state.uploading = false;
      state.sampleLoading = false;
      if (nodes.files) {
        try {
          nodes.files.value = "";
        } catch (_) {
          /* ignore */
        }
      }
      if (nodes.job) nodes.job.value = "";
      if (nodes.jobTitle) nodes.jobTitle.value = "";
      if (nodes.jobCompany) nodes.jobCompany.value = "";
      if (nodes.jobLocation) nodes.jobLocation.value = "";
      if (nodes.accuracy) nodes.accuracy.checked = false;
      if (nodes.preview) nodes.preview.replaceChildren();
      if (nodes.notes) nodes.notes.replaceChildren();
      if (nodes.editor) nodes.editor.replaceChildren();
      setFieldError(nodes.fileError, "");
      setFieldError(nodes.jobError, "");
      renderFiles();
      renderGenerateState();
      renderConfirmState();
      showCreate();
      setStatus("Choose your CVs to get started.", "");
    }

    function removeFile(index) {
      const next = state.files.slice();
      next.splice(index, 1);
      state.uploadSeq += 1;
      state.generateSeq += 1;
      state.actionSeq += 1;
      state.source = null;
      state.draft = null;
      state.receipt = null;
      state.confirmed = false;
      state.hasEdits = false;
      state.savedTexts = new Map();
      state.textareas = new Map();
      state.linkInputs = new Map();
      state.prefilledContacts = new Set();
      state.documentLabels = {};
      if (nodes.review) nodes.review.hidden = true;
      if (!next.length) {
        state.files = [];
        state.uploading = false;
        state.busy = false;
        state.phase = "";
        renderFiles();
        renderGenerateState();
        setStatus("Choose your CVs to get started.", "");
        return;
      }
      readDocuments(next);
    }

    function post(route, body) {
      return fetch("/api/cv/" + route, {
        method: "POST",
        cache: "no-store",
        headers: {
          "Content-Type": "application/json",
          "X-JobLens-Request": "1",
        },
        body: JSON.stringify(body),
      })
        .catch(() => {
          throw httpError(
            "Could not reach the local server. Check that it is running, then try again.",
            "network",
          );
        })
        .then(async (response) => {
          const raw = await response.text();
          let payload = {};
          if (raw) {
            try {
              payload = JSON.parse(raw);
            } catch (_) {
              payload = {};
            }
          }
          if (!response.ok) {
            throw httpError(
              typeof payload.error === "string"
                ? payload.error
                : "The request could not be completed. Try again.",
              payload.code,
            );
          }
          return payload;
        });
    }

    function httpError(message, code) {
      const error = new Error(message);
      error.code = code || "";
      return error;
    }

    function friendlyError(error) {
      if (!error) return "Something went wrong. Try again.";
      if (
        error.code === "network" ||
        error.code === "network_error" ||
        /failed to fetch|networkerror|load failed/i.test(error.message || "")
      ) {
        return "Could not reach the local server. Check that it is running, then try again.";
      }
      if (error.code === "session_expired") {
        return "This draft belongs to an earlier local server session. Start over and generate a fresh draft.";
      }
      if (error.code === "missing_contact") {
        return "Enter your full name in the contact details before confirming.";
      }
      if (error.code === "draft_changed") {
        return "This draft changed. Review the current version and confirm it again.";
      }
      return error.message || "Something went wrong. Try again.";
    }

    function element(tag, className, text) {
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    }

    function iconButton(symbol, label, handler, className) {
      const button = element("button", className || "icon-button", symbol);
      button.type = "button";
      button.setAttribute("aria-label", label);
      button.title = label;
      button.addEventListener("click", handler);
      return button;
    }

    /* Listeners */
    if (nodes.files) {
      nodes.files.addEventListener("change", () => {
        const files = Array.from(nodes.files.files || []);
        if (!files.length) return;
        addDocuments(files);
        // Reset the native picker so the same file can be selected again after
        // removal; the custom file list is the visible source of truth.
        try {
          nodes.files.value = "";
        } catch (_) {
          /* ignore */
        }
      });
    }

    if (nodes.drop) {
      let dragDepth = 0;
      nodes.drop.addEventListener("dragenter", (event) => {
        event.preventDefault();
        dragDepth += 1;
        nodes.drop.className = "dropzone is-dragging";
      });
      nodes.drop.addEventListener("dragover", (event) => {
        event.preventDefault();
      });
      nodes.drop.addEventListener("dragleave", (event) => {
        event.preventDefault();
        dragDepth = Math.max(0, dragDepth - 1);
        if (!dragDepth) nodes.drop.className = "dropzone";
      });
      nodes.drop.addEventListener("drop", (event) => {
        event.preventDefault();
        dragDepth = 0;
        nodes.drop.className = "dropzone";
        const files = event.dataTransfer && event.dataTransfer.files;
        if (files && files.length) addDocuments(files);
      });
    }

    if (nodes.job) {
      nodes.job.addEventListener("input", () => {
        setFieldError(nodes.jobError, "");
        renderGenerateState();
      });
      nodes.job.addEventListener("blur", () => {
        const posting = validatePosting(nodes.job.value);
        if (nodes.job.value.trim() && !posting.ok) {
          setFieldError(nodes.jobError, posting.error);
        }
      });
    }

    if (nodes.generate) nodes.generate.addEventListener("click", generate);
    if (nodes.sample) nodes.sample.addEventListener("click", trySample);
    if (nodes.startOver) nodes.startOver.addEventListener("click", startOver);
    if (nodes.confirm) nodes.confirm.addEventListener("click", confirm);
    if (nodes.pdf) nodes.pdf.addEventListener("click", () => download("pdf"));
    if (nodes.docx) nodes.docx.addEventListener("click", () => download("docx"));
    if (nodes.accuracy) {
      nodes.accuracy.addEventListener("change", () => {
        if (!nodes.accuracy.checked && state.confirmed) {
          state.confirmed = false;
          state.receipt = null;
          if (state.draft && state.draft.review) {
            delete state.draft.review.final_receipt;
          }
        }
        renderConfirmState();
      });
    }

    renderFiles();
    renderGenerateState();
    renderConfirmState();
    setStatus("Choose your CVs to get started.", "");

    return {
      state,
      readDocuments,
      addDocuments,
      generate,
      confirm,
      download,
      trySample,
      startOver,
      renderAll,
    };
  }

  return {
    MAX_FILES,
    MAX_FILE_BYTES,
    MAX_TOTAL_BYTES,
    MIN_JOB_LENGTH,
    MAX_JOB_LENGTH,
    PDF_MIME,
    DOCX_MIME,
    SAMPLE_JOB,
    SAMPLE_FILES,
    fileKind,
    fileIdentity,
    mergeFileSelection,
    validateFiles,
    validatePosting,
    draftItems,
    fullName,
    hasFullName,
    draftStats,
    allApproved,
    allItemsHaveText,
    canGenerate,
    canConfirm,
    canDownload,
    moveItem,
    moveSection,
    removeItem,
    sourceQuotes,
    itemMode,
    reviewNotes,
    contactParts,
    CONTACT_FORM_FIELDS,
    linkParts,
    linksFromParts,
    contactSuggestions,
    suggestionFor,
    applyContactPrefill,
    contactSuggestionDetail,
    decisionReport,
    formatBytes,
    fileNameFor,
    targetLabel,
    init,
  };
});

if (typeof document !== "undefined" && document.getElementById) {
  const boot = function () {
    if (typeof JobLensProduct !== "undefined") JobLensProduct.init();
  };
  if (document.readyState === "loading" && document.addEventListener) {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
}
