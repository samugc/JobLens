"use strict";
/* Canonical reconciliation schema 0.1. No profile-derived comparisons or approvals. */
(function (global, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./profile-adapter.js"));
  } else {
    global.JobLensReconciliation = factory(global.JobLensProfileAdapter);
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function (profileAdapter) {
  const SCHEMA_VERSION = "0.1";
  const RELATIONS = Object.freeze(["duplicate", "equivalent", "complementary", "more_specific",
    "less_specific", "potentially_conflicting", "contradictory", "temporal_update", "unrelated", "uncertain"]);
  const OUTCOMES = Object.freeze(["auto_consolidate", "recommend", "unresolved"]);
  class ReconciliationContractError extends Error {
    constructor(message) { super(message); this.name = "ReconciliationContractError"; }
  }
  const fail = message => { throw new ReconciliationContractError(message); };
  const object = (v, path) => { if (!v || typeof v !== "object" || Array.isArray(v)) fail(`${path}: expected object`); return v; };
  const array = (v, path) => { if (!Array.isArray(v)) fail(`${path}: expected array`); return v; };
  const string = (v, path) => { if (typeof v !== "string" || !v.length) fail(`${path}: expected string`); return v; };
  const ids = (items, key) => {
    const map = new Map();
    for (const item of items) { object(item, key); const id = string(item[key], key); if (map.has(id)) fail(`duplicate ${key}`); map.set(id, item); }
    return map;
  };
  function validateEvidence(evidence, source) {
    return array(evidence, "evidence").map(e => {
      object(e, "evidence");
      string(e.document_id, "document_id");
      if (!Number.isInteger(e.segment_index) || e.segment_index < 0 || !Number.isInteger(e.start) ||
          !Number.isInteger(e.end) || e.start < 0 || e.end < e.start || typeof e.quote !== "string") fail("invalid evidence offsets");
      object(e.locator, "locator");
      if (!["explicit_claim", "keyword_mention"].includes(e.support)) fail("invalid evidence support");
      const document = source?.documents?.find(d => d.id === e.document_id);
      const segment = document?.segments?.[e.segment_index];
      const points = Array.from(segment?.text ?? "");
      let sameLocator = false;
      try { sameLocator = Boolean(segment) && JSON.stringify(profileAdapter.normalizeLocator(e.locator, "e")) ===
        JSON.stringify(profileAdapter.normalizeLocator(segment.locator, "source")); } catch { /* invalid provenance remains unverified */ }
      const verified = Boolean(segment) && e.quote.length > 0 && e.end <= points.length &&
        points.slice(e.start, e.end).join("") === e.quote && sameLocator;
      return { evidence: e, verified, document: document || null };
    });
  }
  function normalizeReport(raw, { source } = {}) {
    object(raw, "report");
    if (raw.reconciliation_schema_version !== SCHEMA_VERSION || raw.parser_schema_version !== "1.1" ||
        raw.profile_schema_version !== "0.1") fail("unsupported reconciliation versions");
    if (!source || raw.job_id !== source.jobId) fail("report does not match extraction job");
    // The report is plain JSON. The fallback keeps the adapter usable on
    // Safari versions without structuredClone.
    const report = typeof structuredClone === "function"
      ? structuredClone(raw)
      : JSON.parse(JSON.stringify(raw));
    const documents = ids(array(report.documents, "documents"), "document_id");
    const sourceIds = new Set(source.documents.map(d => d.id));
    if (documents.size !== sourceIds.size || [...documents.keys()].some(id => !sourceIds.has(id))) fail("document provenance mismatch");
    const claims = ids(array(report.claims, "claims"), "claim_id");
    const relationships = ids(array(report.relationships, "relationships"), "relationship_id");
    ids(array(report.decisions, "decisions"), "decision_id");
    array(report.consolidated, "consolidated");
    array(report.warnings, "warnings").forEach(w => string(w, "warning"));
    const evidence = new Map();
    const verified = new Map();
    const relationshipVerified = new Map();
    const consolidationVerified = new Map();
    const references = (list, map, field) => array(list, field).forEach(id => { if (!map.has(id)) fail(`foreign ${field}`); });
    const attributes = list => array(list, "attributes").forEach(a => {
      object(a, "attribute"); string(a.name, "attribute.name");
      if (!("value" in a) || typeof a.normalized !== "string") fail("invalid attribute");
    });
    for (const c of claims.values()) {
      string(c.category, "category");string(c.subject, "subject");string(c.subject_label, "subject_label");
      attributes(c.attributes);
      if (!["explicit_claim", "keyword_mention"].includes(c.qualifier)) fail("invalid qualifier");
      const resolved = validateEvidence(c.evidence, source);
      evidence.set(c.claim_id, resolved);
      verified.set(c.claim_id, resolved.length > 0 && resolved.every(e => e.verified));
    }
    for (const r of relationships.values()) {
      references([r.left_claim_id, r.right_claim_id], claims, "relationship claims");
      string(r.relation, "relation");string(r.reason, "reason");string(r.basis, "basis");
      array(r.attributes, "relationship attributes");
      if (r.semantic !== undefined && typeof r.semantic !== "boolean") fail("invalid semantic flag");
      relationshipVerified.set(r.relationship_id, validateEvidence(r.evidence, source).every(e => e.verified));
    }
    for (const d of report.decisions) {
      string(d.outcome, "outcome");string(d.explanation, "explanation");
      string(d.category, "decision category");string(d.subject, "decision subject");
      if (typeof d.requires_user_confirmation !== "boolean") fail("invalid confirmation flag");
      const keep = array(d.keep_claim_ids, "keep_claim_ids");
      const merge = array(d.merge_claim_ids, "merge_claim_ids");
      const alternatives = d.alternative_claim_ids === undefined
        ? [] : array(d.alternative_claim_ids, "alternative_claim_ids");
      references(keep, claims, "keep_claim_ids");references(merge, claims, "merge_claim_ids");
      references(alternatives, claims, "alternative_claim_ids");
      references(d.relationship_ids, relationships, "relationship_ids");
      // Only an auto-consolidation may describe claims as merged. A
      // recommendation keeps the claims it does not choose as alternatives,
      // and an unresolved decision keeps every candidate as an alternative.
      if (d.outcome !== "auto_consolidate" && merge.length) {
        fail("only auto_consolidate may merge claims");
      }
      if (d.outcome === "auto_consolidate" && alternatives.length) {
        fail("auto_consolidate cannot retain alternatives");
      }
      if (d.approval_state !== undefined && d.approval_state !== "not_approved") {
        fail("the engine cannot approve a decision");
      }
    }
    for (const c of report.consolidated) {
      references(c.claim_ids, claims, "consolidated claim_ids");attributes(c.attributes);
      if (c.qualifiers !== undefined) {
        array(c.qualifiers, "qualifiers").forEach(q => {
          if (!["explicit_claim", "keyword_mention"].includes(q)) fail("invalid consolidated qualifier");
        });
      }
      if (c.approval_state !== undefined && c.approval_state !== "not_approved") {
        fail("the engine cannot approve a consolidated claim");
      }
      const citations = validateEvidence(c.evidence, source);
      consolidationVerified.set(c, citations.length > 0 && citations.every(e => e.verified));
    }
    // Identity is supplied by the engine. Cross-category links stay explicit;
    // similar labels and years in quotations never create new relations here.
    const groups = new Map();
    for (const c of claims.values()) {
      const key = JSON.stringify([c.category, c.subject]);
      if (!groups.has(key)) groups.set(key, {key, category:c.category, subject:c.subject, label:c.subject_label, claims:[], relationships:[], decisions:[], consolidated:[]});
      groups.get(key).claims.push(c);
    }
    for (const group of groups.values()) {
      const own = new Set(group.claims.map(c => c.claim_id));
      group.relationships = report.relationships.filter(r => own.has(r.left_claim_id) || own.has(r.right_claim_id));
      group.decisions = report.decisions.filter(d => d.keep_claim_ids.some(id=>own.has(id)) ||
        d.merge_claim_ids.some(id=>own.has(id)) ||
        (d.alternative_claim_ids || []).some(id=>own.has(id)) ||
        (d.category === group.category && d.subject === group.subject));
      group.consolidated = report.consolidated.filter(c=>c.claim_ids.some(id=>own.has(id)));
      group.blocking = group.claims.some(c=>!verified.get(c.claim_id)) || group.consolidated.some(c=>!consolidationVerified.get(c)) ||
        group.relationships.some(r=>!relationshipVerified.get(r.relationship_id) || r.semantic === true ||
        !RELATIONS.includes(r.relation) || ["uncertain", "contradictory", "potentially_conflicting"].includes(r.relation)) ||
        group.decisions.some(d=>d.outcome !== "auto_consolidate" || d.requires_user_confirmation);
    }
    return {report, groups:[...groups.values()], evidence, verified,
      counts:{entities:groups.size,claims:claims.size,consolidations:report.consolidated.length,
        conflicts:report.relationships.filter(r=>["contradictory","potentially_conflicting"].includes(r.relation)).length,
        unresolved:report.decisions.filter(d=>d.outcome === "unresolved" || !OUTCOMES.includes(d.outcome)).length, approved:0}};
  }
  class ReconciliationAdapter {
    constructor({ baseUrl = "/api/cv", fetchImpl = globalThis.fetch?.bind(globalThis) } = {}) {
      if (typeof fetchImpl !== "function") throw new Error("fetch unavailable");
      this.baseUrl = baseUrl.replace(/\/$/, "");this.fetchImpl = fetchImpl;
    }
    async createReconciliation(job, {signal} = {}) {
      const response = await this.fetchImpl(`${this.baseUrl}/reconciliations`, {
        method:"POST", credentials:"same-origin", signal,
        headers:{Accept:"application/json", "Content-Type":"application/json", "X-JobLens-Request":"1"},
        body:JSON.stringify(profileAdapter.buildProfileRequest(job)),
      });
      const raw = await response.json();
      if (!response.ok) { const e = new Error(raw.error?.message || `HTTP ${response.status}`);e.status=response.status;throw e; }
      return normalizeReport(raw, {source:profileAdapter.sourceFromJob(job)});
    }
  }
  return Object.freeze({SCHEMA_VERSION, RELATIONS, OUTCOMES, ReconciliationContractError, normalizeReport, validateEvidence, ReconciliationAdapter});
});
