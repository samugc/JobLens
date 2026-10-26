"use strict";

/*
 * JobLens CV Evidence Workspace — candidate profile review rules
 *
 * The rules mirror the review reducer of the profile engine, so the interface
 * never contradicts the backend:
 *
 *   approve  the proposal becomes approved. It is refused when the proposal
 *            has no evidence, when its evidence cannot be checked against the
 *            extracted text, or when a conflict is still open.
 *   reject   the proposal becomes rejected and stays in the state.
 *   edit     a NEW proposal is created with the edited value, in the proposed
 *            state. The edited proposal becomes superseded, so an approval is
 *            revoked, and the revision only keeps the evidence that still
 *            supports the new value.
 *
 * Conflicts are global records that proposals reference by id. They are never
 * dismissed by a single click: a resolution has to name the proposals the
 * reviewer stands behind and to record why, and it is kept in the history.
 *
 * The state lives in memory for this iteration. It is never written to
 * localStorage, never sent anywhere and never persisted.
 */
(function (global, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    global.JobLensProfileReview = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const STATUS = Object.freeze({
    PROPOSED: "proposed",
    APPROVED: "approved",
    REJECTED: "rejected",
    SUPERSEDED: "superseded",
  });

  const ACTION = Object.freeze({
    APPROVE: "approve",
    REJECT: "reject",
    EDIT: "edit",
    RESOLVE_CONFLICT: "resolve_conflict",
    USE_RECOMMENDATION: "use_recommendation",
  });

  const CATEGORY_ORDER = Object.freeze([
    "skill",
    "experience",
    "education",
    "project",
    "language",
    "certification",
  ]);

  /*
   * Word forms of a degree level, used when checking whether an edited value
   * is still supported by the quoted evidence. The engine's own lexicon stays
   * authoritative; this table only mirrors the spellings of the contract so
   * the interface can refuse an unsupported edit before it is sent.
   */
  const DEGREE_SURFACE_FORMS = Object.freeze({
    bachelor: [
      "bachelor of science",
      "bachelor of arts",
      "bachelor of engineering",
      "bachelor",
      "bachelors",
      "bachelor's",
      "bs",
      "bsc",
      "b sc",
    ],
    master: [
      "master of business administration",
      "master of science",
      "master of arts",
      "master of engineering",
      "master",
      "masters",
      "master's",
      "ms",
      "msc",
      "m sc",
      "ma",
      "m a",
    ],
    doctorate: [
      "doctor of philosophy",
      "phd",
      "ph.d",
      "ph.d.",
      "doctorate",
      "doctoral",
    ],
    associate: ["associate", "associate's", "a.s", "a.s."],
    diploma: ["diploma"],
    mba: ["mba"],
  });

  function cloneProposal(proposal) {
    return {
      ...proposal,
      value: { ...proposal.value },
      details: (proposal.details || []).map((detail) => ({ ...detail })),
      evidence: (proposal.evidence || []).map((entry) => ({ ...entry })),
      conflicts: (proposal.conflicts || []).map((conflict) => ({ ...conflict })),
      conflictIds: [...(proposal.conflictIds || [])],
    };
  }

  function createReviewState(profile) {
    return {
      sequence: 0,
      proposals: (profile?.proposals || []).map(cloneProposal),
      conflicts: (profile?.conflicts || []).map((conflict) => ({ ...conflict })),
      history: [],
      conflictResolutions: {},
    };
  }

  function findProposal(state, proposalId) {
    return state.proposals.find((proposal) => proposal.id === proposalId) || null;
  }

  function findConflict(state, conflictId) {
    return state.conflicts.find((conflict) => conflict.conflictId === conflictId) || null;
  }

  /*
   * A quotation supports an edited value when it still contains what the
   * value says. The education rule needs the subject and one spelling of the
   * degree, exactly like the engine.
   */
  function isSupported(category, value, quote) {
    const haystack = String(quote || "").toLowerCase();
    const contains = (needle) => {
      const text = String(needle || "").toLowerCase();
      return Boolean(text) && haystack.includes(text);
    };

    if (category === "skill") return contains(value.name);
    if (category === "experience") return contains(value.role);
    if (category === "project") return contains(value.name);
    if (category === "certification") return contains(value.name);
    if (category === "language") {
      if (!contains(value.language)) return false;
      if (!value.stated_level) return true;
      return contains(value.stated_level);
    }
    if (category === "education") {
      if (!contains(value.field)) return false;
      const forms = DEGREE_SURFACE_FORMS[value.level] || [];
      return forms.some((form) => haystack.includes(form));
    }
    return false;
  }

  function conflictResolution(state, conflictId) {
    return state.conflictResolutions[conflictId] || null;
  }

  /*
   * A proposal can only be approved when its evidence was checked against the
   * extracted text, when it has evidence at all, when it was not superseded,
   * and when every conflict it takes part in was resolved with a record that
   * keeps this proposal.
   */
  function canApprove(proposal, state) {
    if (!proposal) return { allowed: false, reason: "Unknown proposal." };

    if (proposal.status === STATUS.SUPERSEDED) {
      return {
        allowed: false,
        reason: "This revision was superseded by a later edit.",
      };
    }

    const evidence = Array.isArray(proposal.evidence) ? proposal.evidence : [];
    if (!evidence.length) {
      return {
        allowed: false,
        reason:
          "A proposal without evidence cannot be approved: it is not evidence-backed.",
      };
    }

    const unchecked = evidence.filter(
      (entry) => entry.resolved !== true || entry.verified !== true,
    );
    if (unchecked.length) {
      return {
        allowed: false,
        reason:
          "The evidence does not resolve to the extracted text of a loaded document.",
      };
    }

    const conflicts = Array.isArray(proposal.conflicts) ? proposal.conflicts : [];
    for (const conflict of conflicts) {
      // A conflict that reports one fact under two descriptions does not block:
      // both proposals stay visible and both may be approved.

      const resolution = conflictResolution(state, conflict.conflictId);
      if (!resolution) {
        return {
          allowed: false,
          reason:
            "Resolve the open conflict and record how it was resolved before approving this fact.",
        };
      }
      if (!resolution.kept.includes(proposal.id)) {
        return {
          allowed: false,
          reason:
            "This fact was not kept when the conflict was resolved. Reject it or record a new resolution.",
        };
      }
    }

    return { allowed: true, reason: null };
  }

  /* A stable, opaque identifier for a revision. */
  function revisionId(proposal, sequence, value) {
    const payload = [
      proposal.id,
      String(sequence),
      proposal.category,
      JSON.stringify(
        Object.entries(value)
          .map(([key, item]) => [String(key), String(item)])
          .sort((left, right) => (left[0] < right[0] ? -1 : 1)),
      ),
    ].join("|");

    let hash = 0xcbf29ce484222325n;
    const prime = 0x100000001b3n;
    const mask = 0xffffffffffffffffn;
    for (let index = 0; index < payload.length; index += 1) {
      hash ^= BigInt(payload.charCodeAt(index));
      hash = (hash * prime) & mask;
    }
    return `prop_${hash.toString(16).padStart(16, "0")}`;
  }

  function refuse(state, reason) {
    return { applied: false, state, reason, status: null, revisionId: null };
  }

  function applyReviewAction(state, action, options = {}) {
    const adapter = options.adapter;
    const kind = action?.kind;

    if (!state) return refuse(state, "A review state is required.");

    if (kind === ACTION.RESOLVE_CONFLICT) {
      const conflict = findConflict(state, action.conflictId);
      if (!conflict) return refuse(state, "Unknown conflict.");

      const kept = Array.isArray(action.kept) ? action.kept.filter(Boolean) : [];
      if (!kept.length) {
        return refuse(
          state,
          "A resolution has to name the proposals the reviewer stands behind.",
        );
      }
      const unknown = kept.filter((id) => !conflict.proposalIds.includes(id));
      if (unknown.length) {
        return refuse(
          state,
          "A resolution can only keep the proposals of that conflict.",
        );
      }

      if (conflict.kind === "conflicting_description" && kept.length !== 1) {
        return refuse(state, "Select exactly one proposal for this project contradiction.");
      }

      const note = typeof action.note === "string" ? action.note.trim() : "";
      if (!note) {
        return refuse(
          state,
          "A resolution has to record why the conflict was resolved.",
        );
      }

      const sequence = state.sequence + 1;
      const resolution = {
        conflictId: conflict.conflictId,
        kept: [...kept],
        note,
        sequence,
        source: "manual",
        strategy: null,
      };

      return {
        applied: true,
        state: {
          ...state,
          sequence,
          conflictResolutions: {
            ...state.conflictResolutions,
            [conflict.conflictId]: resolution,
          },
          history: [
            ...state.history,
            {
              sequence,
              kind: ACTION.RESOLVE_CONFLICT,
              proposal_id: null,
              revision_id: null,
              supported: null,
              detail: {
                conflict_id: conflict.conflictId,
                kept: [...kept],
                note,
                source: "manual",
              },
            },
          ],
        },
        reason: null,
        status: null,
        revisionId: null,
      };
    }

    /*
     * Taking the suggestion of the backend. It resolves the conflict and it
     * records the decision of the reviewer, but it never approves a fact: the
     * proposals stay proposed until the reviewer approves them one by one.
     */
    if (kind === ACTION.USE_RECOMMENDATION) {
      const conflict = findConflict(state, action.conflictId);
      if (!conflict) return refuse(state, "Unknown conflict.");

      const hint = conflict.resolutionHint;
      if (!hint) {
        return refuse(
          state,
          conflict.resolutionHintIssue ||
            "The backend did not suggest a resolution for this conflict.",
        );
      }

      const foreign = hint.keepProposalIds.filter(
        (id) => !conflict.proposalIds.includes(id),
      );
      if (foreign.length) {
        return refuse(
          state,
          "The suggestion names a proposal that is not part of this conflict.",
        );
      }

      const sequence = state.sequence + 1;
      const note = hint.explanation.trim()
        ? hint.explanation.trim()
        : `The backend suggested ${hint.strategy}.`;
      const resolution = {
        conflictId: conflict.conflictId,
        kept: [...hint.keepProposalIds],
        note,
        sequence,
        source: "recommendation",
        strategy: hint.strategy,
      };

      return {
        applied: true,
        state: {
          ...state,
          sequence,
          conflictResolutions: {
            ...state.conflictResolutions,
            [conflict.conflictId]: resolution,
          },
          history: [
            ...state.history,
            {
              sequence,
              kind: ACTION.USE_RECOMMENDATION,
              proposal_id: null,
              revision_id: null,
              supported: null,
              detail: {
                conflict_id: conflict.conflictId,
                kept: [...hint.keepProposalIds],
                note,
                source: "recommendation",
                strategy: hint.strategy,
              },
            },
          ],
        },
        reason: null,
        status: null,
        revisionId: null,
      };
    }

    const proposal = findProposal(state, action?.proposalId);
    if (!proposal) return refuse(state, "Unknown proposal.");

    if (kind === ACTION.APPROVE) {
      const check = canApprove(proposal, state);
      if (!check.allowed) return refuse(state, check.reason);

      const sequence = state.sequence + 1;
      return {
        applied: true,
        state: {
          ...state,
          sequence,
          proposals: state.proposals.map((item) =>
            item.id === proposal.id ? { ...item, status: STATUS.APPROVED } : item,
          ),
          history: [
            ...state.history,
            {
              sequence,
              kind: ACTION.APPROVE,
              proposal_id: proposal.id,
              revision_id: null,
              supported: null,
              detail: null,
            },
          ],
        },
        reason: null,
        status: STATUS.APPROVED,
        revisionId: null,
      };
    }

    if (kind === ACTION.REJECT) {
      if (proposal.status === STATUS.SUPERSEDED) {
        return refuse(state, "A superseded revision cannot be rejected again.");
      }

      const sequence = state.sequence + 1;
      return {
        applied: true,
        state: {
          ...state,
          sequence,
          proposals: state.proposals.map((item) =>
            item.id === proposal.id ? { ...item, status: STATUS.REJECTED } : item,
          ),
          history: [
            ...state.history,
            {
              sequence,
              kind: ACTION.REJECT,
              proposal_id: proposal.id,
              revision_id: null,
              supported: null,
              detail: null,
            },
          ],
        },
        reason: null,
        status: STATUS.REJECTED,
        revisionId: null,
      };
    }

    if (kind === ACTION.EDIT) {
      if (proposal.status === STATUS.SUPERSEDED) {
        return refuse(state, "A superseded revision cannot be edited.");
      }

      const value = action.value;
      if (!value || typeof value !== "object" || Array.isArray(value)) {
        return refuse(state, "An edit needs a value.");
      }
      if (!Object.keys(value).length) {
        return refuse(state, "An edit needs a non-empty value.");
      }

      let described = null;
      if (adapter && typeof adapter.describeValue === "function") {
        try {
          described = adapter.describeValue(proposal.category, value);
        } catch (error) {
          return refuse(state, error.message);
        }
      }

      const kept = proposal.evidence.filter((entry) =>
        isSupported(proposal.category, value, entry.quote),
      );
      const sequence = state.sequence + 1;
      const revision = {
        ...cloneProposal(proposal),
        id: revisionId(proposal, sequence, value),
        position: state.proposals.length,
        status: STATUS.PROPOSED,
        value: described ? described.value : { ...value },
        label: described ? described.label : proposal.label,
        details: described ? described.details : [],
        evidence: kept,
        conflicts: [],
        conflictIds: [],
        revision: sequence,
        revisionOf: proposal.id,
      };

      return {
        applied: true,
        state: {
          ...state,
          sequence,
          proposals: [
            ...state.proposals.map((item) =>
              item.id === proposal.id
                ? { ...item, status: STATUS.SUPERSEDED }
                : item,
            ),
            revision,
          ],
          history: [
            ...state.history,
            {
              sequence,
              kind: ACTION.EDIT,
              proposal_id: proposal.id,
              revision_id: revision.id,
              supported: kept.length > 0,
              detail: { value: described ? described.value : { ...value } },
            },
          ],
        },
        reason: null,
        status: STATUS.PROPOSED,
        revisionId: revision.id,
        supported: kept.length > 0,
      };
    }

    return refuse(state, "Unknown review action.");
  }

  function buildViewModel(profile, state, adapter) {
    if (!state || !Array.isArray(state.proposals)) {
      throw new Error("A review state is required.");
    }
    if (!adapter || typeof adapter.describeValue !== "function") {
      throw new Error("The profile adapter is required to describe values.");
    }

    const proposals = state.proposals.map((proposal) => {
      const conflicts = (proposal.conflicts || []).map((conflict) => {
        const resolution = conflictResolution(state, conflict.conflictId);
        const global = state.conflicts.find(
          (item) => item.conflictId === conflict.conflictId,
        );
        return {
          ...conflict,
          resolved: Boolean(resolution),
          resolution: resolution || null,
          kept: resolution ? resolution.kept.includes(proposal.id) : null,
          // The backend suggests, the reviewer decides.
          recommended:
            Boolean(global?.resolutionHint && global?.suggestion) && !resolution,
          blocking: global ? global.blocking : conflict.blocking,
        };
      });

      const view = {
        ...proposal,
        conflicts,
        unresolvedConflicts: conflicts.filter((conflict) => !conflict.resolved).length,
        isApproved: proposal.status === STATUS.APPROVED,
        isRejected: proposal.status === STATUS.REJECTED,
        isProposed: proposal.status === STATUS.PROPOSED,
        isSuperseded: proposal.status === STATUS.SUPERSEDED,
        isRevision: Boolean(proposal.revisionOf),
      };

      const check = canApprove(view, state);
      view.canApprove = check.allowed;
      view.approveReason = check.reason;
      return view;
    });

    const counts = {
      total: proposals.length,
      proposed: 0,
      approved: 0,
      rejected: 0,
      superseded: 0,
      unresolved: 0,
      conflicts: state.conflicts.length,
      categories: {},
    };
    for (const category of CATEGORY_ORDER) counts.categories[category] = 0;

    for (const proposal of proposals) {
      if (proposal.status === STATUS.APPROVED) counts.approved += 1;
      else if (proposal.status === STATUS.REJECTED) counts.rejected += 1;
      else if (proposal.status === STATUS.SUPERSEDED) counts.superseded += 1;
      else counts.proposed += 1;

      if (proposal.category in counts.categories) {
        counts.categories[proposal.category] += 1;
      }
    }

    const active = proposals.filter((proposal) => !proposal.isSuperseded);
    const groups = [];
    for (const category of CATEGORY_ORDER) {
      const items = active.filter((proposal) => proposal.category === category);
      if (!items.length) continue;
      groups.push({
        category,
        label: adapter.CATEGORY_META?.[category]?.label || category,
        singular: adapter.CATEGORY_META?.[category]?.singular || category,
        proposals: items,
      });
    }

    const conflicts = state.conflicts.map((conflict) => {
      const resolution = conflictResolution(state, conflict.conflictId);
      return {
        ...conflict,
        resolved: Boolean(resolution),
        resolution: resolution || null,
      };
    });
    counts.unresolved = conflicts.filter(
      (conflict) => !conflict.resolved,
    ).length;

    const history = state.history.map((event) => {
      const proposal = event.proposal_id
        ? proposals.find((item) => item.id === event.proposal_id)
        : null;
      const revision = event.revision_id
        ? proposals.find((item) => item.id === event.revision_id)
        : null;
      return {
        ...event,
        label: proposal?.label ?? null,
        revisionLabel: revision?.label ?? null,
      };
    });

    return {
      proposals,
      groups,
      active,
      superseded: proposals.filter((proposal) => proposal.isSuperseded),
      conflicts,
      counts,
      history,
    };
  }

  return Object.freeze({
    STATUS,
    ACTION,
    CATEGORY_ORDER,
    DEGREE_SURFACE_FORMS,
    createReviewState,
    applyReviewAction,
    buildViewModel,
    canApprove,
    isSupported,
    conflictResolution,
  });
});
