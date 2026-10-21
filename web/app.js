"use strict";

(() => {
  const $ = (id) => document.getElementById(id);

  const state = {
    candidates: [],
    jobs: [],
    selectedJobId: "",
    analysisRevision: 0,
  };

  const STATUS = {
    documented: {
      label: "Documented",
      cardClass: "status-documented",
      pillClass: "status-documented",
    },
    partial: {
      label: "Partial",
      cardClass: "status-partial",
      pillClass: "status-partial",
    },
    not_documented: {
      label: "Not documented",
      cardClass: "status-gap",
      pillClass: "status-gap",
    },
  };

  const SKILL_NAMES = {
    "python": "Python",
    "sql": "SQL",
    "c++": "C++",
    "pandas": "pandas",
    "numpy": "NumPy",
    "scikit-learn": "scikit-learn",
    "machine learning": "Machine learning",
    "deep learning": "Deep learning",
    "statistics": "Statistics",
    "probability": "Probability",
    "optimization": "Optimization",
    "spark": "Spark",
    "airflow": "Airflow",
    "dbt": "dbt",
    "databricks": "Databricks",
    "aws": "AWS",
    "azure": "Azure",
    "gcp": "GCP",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "git": "Git",
    "tensorflow": "TensorFlow",
    "pytorch": "PyTorch",
    "llm": "LLM",
    "nlp": "NLP",
    "rag": "RAG",
    "classification": "Classification",
    "sentiment analysis": "Sentiment analysis",
    "forecasting": "Forecasting",
  };

  const REVIEW_NAMES = {
    education: "Education",
    work_authorization: "Work authorization",
    production_experience: "Production experience",
    onsite_or_relocation: "Location / relocation",
    experience_duration: "Experience duration",
    alternative_skill_choice: "Alternative skill choice",
  };

  const FIT_BADGES = {
    EVIDENCE_GAPS: { label: "Evidence gaps", className: "badge-warn" },
    REVIEW_REQUIRED: { label: "Review required", className: "badge-review" },
    SKILL_COVERAGE_ONLY: { label: "Coverage only", className: "badge-python" },
  };

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[character]));
  }

  function setText(id, value) {
    const element = $(id);
    if (element) element.textContent = value ?? "";
  }

  function initials(name) {
    const words = String(name || "").trim().split(/\s+/).filter(Boolean);
    if (!words.length) return "?";
    return (words[0][0] + (words.length > 1 ? words[words.length - 1][0] : "")).toUpperCase();
  }

  function skillName(value) {
    return SKILL_NAMES[value] || value.replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  function reviewName(value) {
    return REVIEW_NAMES[value] || value.replaceAll("_", " ");
  }

  function sentenceCase(value) {
    const text = String(value || "").trim();
    return text ? text[0].toUpperCase() + text.slice(1) : "";
  }

  async function fetchJson(url, options) {
    const response = await fetch(url, options);
    let payload = {};
    try {
      payload = await response.json();
    } catch {
      payload = {};
    }
    if (!response.ok) {
      throw new Error(payload.error || `Request failed with status ${response.status}`);
    }
    return payload;
  }

  function selectedCandidate() {
    return state.candidates.find((candidate) => candidate.id === $("candidate").value);
  }

  function selectedJob() {
    return state.jobs.find((job) => job.id === $("example").value);
  }

  function renderCandidateNote() {
    const candidate = selectedCandidate();
    if (!candidate) {
      setText("candidate-note", "");
      return;
    }
    setText("candidate-note", `${candidate.headline}. ${candidate.note}`);
  }

  function invalidateReport() {
    state.analysisRevision += 1;
    $("report").hidden = true;
    $("empty-state").hidden = false;
    $("error-state").hidden = true;
  }

  function loadExample() {
    const job = selectedJob();
    if (!job) return;
    state.selectedJobId = job.id;
    $("title").value = job.title;
    $("company").value = job.company;
    $("location").value = job.location;
    $("description").value = job.description;
    invalidateReport();
  }

  function applyDeepLink() {
    const params = new URLSearchParams(window.location.search);
    const candidateId = params.get("candidate");
    if (candidateId && state.candidates.some((candidate) => candidate.id === candidateId)) {
      $("candidate").value = candidateId;
    }
    const jobId = params.get("job");
    if (jobId && state.jobs.some((job) => job.id === jobId)) {
      $("example").value = jobId;
    }
    renderCandidateNote();
    loadExample();
    if (params.get("analyze") === "1") {
      $("job-form").requestSubmit();
    }
  }

  function populateBootstrap(payload) {
    state.candidates = Array.isArray(payload.candidates) ? payload.candidates : [];
    state.jobs = Array.isArray(payload.jobs) ? payload.jobs : [];

    $("candidate").innerHTML = state.candidates
      .map((candidate) => `<option value="${escapeHtml(candidate.id)}">${escapeHtml(candidate.name)}</option>`)
      .join("");

    $("example").innerHTML = state.jobs
      .map((job) => `<option value="${escapeHtml(job.id)}">${escapeHtml(job.title)} · ${escapeHtml(job.company)}</option>`)
      .join("");

    if (!state.candidates.length || !state.jobs.length) {
      throw new Error("The demo data is incomplete.");
    }
    applyDeepLink();
  }

  function coverageText(coverage) {
    if (!coverage || !coverage.total_extracted) return "No explicit skills extracted";
    const percentage = Math.round((coverage.ratio || 0) * 100);
    return `${percentage}% of extracted skills have an explicit claim`;
  }

  function renderCoverage(prefix, coverage) {
    const documented = coverage?.documented ?? 0;
    const total = coverage?.total_extracted ?? 0;
    setText(`${prefix}-tally`, `${documented}/${total}`);
    const progress = $(`${prefix}-progress`);
    if (progress) {
      progress.max = 1;
      progress.value = total ? Math.max(0, Math.min(1, coverage.ratio || 0)) : 0;
    }
    setText(`${prefix}-note`, coverageText(coverage));
  }

  function renderSkillCard(item, contextOnly) {
    const meta = STATUS[item.status] || STATUS.not_documented;
    const evidence = Array.isArray(item.evidence) ? item.evidence : [];
    const evidenceMarkup = evidence
      .map((reference) => `
        <span class="evidence-chip">
          <strong>${escapeHtml(reference.id)}</strong>
          <span class="evidence-claim">“${escapeHtml(reference.claim || "Claim text unavailable")}”</span>
          <span class="evidence-ref">${escapeHtml(reference.label)} · ${escapeHtml(reference.source)}</span>
        </span>`)
      .join("");

    let evidenceBlock;
    if (evidenceMarkup) {
      evidenceBlock = `
        <div class="evidence-list">
          <span class="evidence-label">${contextOnly ? "Context evidence" : "Evidence"}</span>
          ${evidenceMarkup}
          ${item.status === "partial" ? '<p class="skill-partial">Tag-only match. Verify the claim before treating it as evidence.</p>' : ""}
        </div>`;
    } else {
      evidenceBlock = `
        <div class="evidence-list">
          <span class="evidence-label">${contextOnly ? "Context" : "Evidence"}</span>
          <p class="skill-gap">No matching claim in the fictional bank. This does not prove the candidate lacks the skill.</p>
        </div>`;
    }

    return `
      <article class="skill-card ${meta.cardClass}">
        <div class="skill-main">
          <span class="status-pill ${meta.pillClass}"><span class="status-dot"></span>${meta.label}</span>
          <h4>${escapeHtml(skillName(item.requirement))}</h4>
          <p class="skill-basis">${escapeHtml(sentenceCase(item.basis))}</p>
        </div>
        ${evidenceBlock}
      </article>`;
  }

  function renderSkills(containerId, items, contextOnly = false) {
    const container = $(containerId);
    if (!items.length) {
      container.innerHTML = `
        <div class="section-empty">
          No ${contextOnly ? "contextual" : "explicit"} skills were extracted from this posting.
          Requirements outside the current vocabulary still need manual review.
        </div>`;
      return;
    }
    container.innerHTML = items.map((item) => renderSkillCard(item, contextOnly)).join("");
  }

  function renderReviews(items) {
    const container = $("review-list");
    if (!items.length) {
      container.innerHTML = `
        <div class="section-empty">
          No degree, authorization, location or experience gate was detected in this posting.
          That does not mean those conditions are absent.
        </div>`;
      return;
    }
    container.innerHTML = items
      .map((item) => `
        <article class="review-card">
          <span class="review-category">${escapeHtml(reviewName(item.category))}</span>
          <strong>${escapeHtml(item.trigger)}</strong>
          <p class="review-reason">${escapeHtml(item.reason)}</p>
        </article>`)
      .join("");
  }

  function renderReport(payload) {
    const report = payload.report;
    const candidate = payload.candidate || {};
    const required = Array.isArray(report.required) ? report.required : [];
    const preferred = Array.isArray(report.preferred) ? report.preferred : [];
    const mentioned = Array.isArray(report.mentioned) ? report.mentioned : [];
    const reviews = Array.isArray(report.manual_review_requirements)
      ? report.manual_review_requirements
      : [];

    setText("report-title", report.role?.title || "Untitled role");
    setText("report-company", report.role?.company || "Unknown company");
    setText("report-candidate", candidate.name || "Fictional candidate");
    setText("report-headline", candidate.headline || "");
    setText("candidate-initials", initials(candidate.name));

    const fit = FIT_BADGES[report.fit_assessment?.status] || {
      label: "Evidence report",
      className: "badge-neutral",
    };
    const fitBadge = $("fit-badge");
    fitBadge.className = `badge ${fit.className}`;
    fitBadge.textContent = fit.label;

    renderCoverage("required", report.required_coverage);
    renderCoverage("preferred", report.preferred_coverage);

    const requiredGaps = required.filter((item) => item.status === "not_documented").length;
    setText("gap-tally", String(requiredGaps));
    setText(
      "gap-note",
      requiredGaps
        ? "Not documented in the fictional bank. Not a disqualification."
        : "No required gaps in the extracted set.",
    );

    setText("review-tally", String(reviews.length));
    setText(
      "review-note",
      reviews.length ? "Degree, authorization, location or experience gates." : "No explicit gates detected.",
    );

    setText("required-count", `${required.length} extracted`);
    setText("preferred-count", `${preferred.length} extracted`);
    setText("review-count", `${reviews.length} item${reviews.length === 1 ? "" : "s"}`);

    renderSkills("required-list", required);
    renderSkills("preferred-list", preferred);

    const mentionedSection = $("mentioned-section");
    if (mentioned.length) {
      mentionedSection.hidden = false;
      setText("mentioned-count", `${mentioned.length} contextual`);
      renderSkills("mentioned-list", mentioned, true);
    } else {
      mentionedSection.hidden = true;
      $("mentioned-list").innerHTML = "";
    }

    renderReviews(reviews);

    $("limits-list").innerHTML = (report.limitations || [])
      .map((note) => `<li>${escapeHtml(note)}</li>`)
      .join("");

    $("empty-state").hidden = true;
    $("error-state").hidden = true;
    $("report").hidden = false;

    const view = new URLSearchParams(window.location.search).get("view");
    if (view === "report") {
      const top = $("results").getBoundingClientRect().top + window.scrollY - 18;
      document.documentElement.scrollTop = top;
      document.body.scrollTop = top;
    } else if (window.matchMedia("(max-width: 920px)").matches) {
      $("results").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  function showError(message) {
    setText("error-message", message || "Unexpected error.");
    $("empty-state").hidden = true;
    $("report").hidden = true;
    $("error-state").hidden = false;
  }

  async function analyze(event) {
    event.preventDefault();
    const candidate = selectedCandidate();
    if (!candidate) {
      showError("Select a fictional candidate first.");
      return;
    }

    const job = {
      title: $("title").value,
      company: $("company").value,
      location: $("location").value,
      description: $("description").value,
    };
    if (!job.description.trim()) {
      showError("Paste a job description before analyzing.");
      return;
    }

    const button = $("analyze");
    const label = button.textContent;
    const revision = ++state.analysisRevision;
    button.disabled = true;
    button.textContent = "Analyzing…";
    $("results").setAttribute("aria-busy", "true");

    try {
      const payload = await fetchJson("/api/analyze", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-JobLens-Request": "1",
        },
        body: JSON.stringify({ candidate_id: candidate.id, job }),
      });
      if (revision === state.analysisRevision) {
        renderReport(payload);
      }
    } catch (error) {
      if (revision === state.analysisRevision) {
        showError(error.message);
      }
    } finally {
      button.disabled = false;
      button.textContent = label;
      $("results").setAttribute("aria-busy", "false");
    }
  }

  async function init() {
    $("job-form").addEventListener("submit", analyze);
    $("example").addEventListener("change", loadExample);
    $("load-example").addEventListener("click", loadExample);
    $("candidate").addEventListener("change", () => {
      renderCandidateNote();
      invalidateReport();
    });
    ["title", "company", "location", "description"].forEach((id) => {
      $(id).addEventListener("input", invalidateReport);
    });

    try {
      const payload = await fetchJson("/api/bootstrap");
      populateBootstrap(payload);
    } catch (error) {
      showError(
        `${error.message} Start the local demo with "python3 run_demo.py" and reload this page.`,
      );
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
